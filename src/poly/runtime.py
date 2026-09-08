"""Bounded execution of immutable Poly plan frontiers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from io import StringIO
from pathlib import Path
from threading import RLock, local
from types import MappingProxyType
from typing import Any, Protocol, TextIO, cast, runtime_checkable

from poly.driver import (
    ActionValue,
    DriverProtocolError,
    DriverRegistry,
    ExecutionContext,
    OutputReference,
)
from poly.model import ActionSpec, JsonValue, Plan, PlanStatus


class ActionState(StrEnum):
    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"


class RunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"
    EMPTY = "empty"


class WorkerMode(StrEnum):
    EXPLICIT = "explicit"
    AUTO = "auto"


@dataclass(frozen=True, slots=True)
class WorkerConfiguration:
    requested_mode: WorkerMode = WorkerMode.EXPLICIT
    requested: int | None = 1
    effective: int = 1


@dataclass(frozen=True, slots=True)
class ActionAttempt:
    success: bool
    summary: str = ""
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    details: dict[str, JsonValue] = field(default_factory=dict)
    value: ActionValue | None = None
    outputs: tuple[OutputReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))
        object.__setattr__(self, "outputs", tuple(self.outputs))


@runtime_checkable
class ActionRunner(Protocol):
    def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt: ...


class _ThreadCapture:
    """Route writes from one handler thread without redirecting other threads."""

    def __init__(self, base: TextIO) -> None:
        self.base = base
        self.targets = local()

    def write(self, value: str) -> int:
        target = getattr(self.targets, "stream", None)
        return (target or self.base).write(value)

    def flush(self) -> None:
        target = getattr(self.targets, "stream", None)
        (target or self.base).flush()

    def __getattr__(self, name: str) -> object:
        return getattr(self.base, name)


_capture_lock = RLock()
_capture_users = 0
_stdout_router: _ThreadCapture | None = None
_stderr_router: _ThreadCapture | None = None
_capture_stdout_base: TextIO | None = None
_capture_stderr_base: TextIO | None = None


@contextmanager
def _capture_handler_streams() -> Iterator[tuple[StringIO, StringIO]]:
    global _capture_stderr_base, _capture_stdout_base, _capture_users
    global _stderr_router, _stdout_router
    stdout = StringIO()
    stderr = StringIO()
    with _capture_lock:
        if _capture_users == 0:
            _capture_stdout_base = sys.stdout
            _capture_stderr_base = sys.stderr
            _stdout_router = _ThreadCapture(sys.stdout)
            _stderr_router = _ThreadCapture(sys.stderr)
            sys.stdout = cast(TextIO, _stdout_router)
            sys.stderr = cast(TextIO, _stderr_router)
        assert _stdout_router is not None and _stderr_router is not None
        _capture_users += 1
        _stdout_router.targets.stream = stdout
        _stderr_router.targets.stream = stderr
    try:
        yield stdout, stderr
    finally:
        with _capture_lock:
            assert _stdout_router is not None and _stderr_router is not None
            del _stdout_router.targets.stream
            del _stderr_router.targets.stream
            _capture_users -= 1
            if _capture_users == 0:
                assert _capture_stdout_base is not None and _capture_stderr_base is not None
                sys.stdout = _capture_stdout_base
                sys.stderr = _capture_stderr_base
                _stdout_router = None
                _stderr_router = None
                _capture_stdout_base = None
                _capture_stderr_base = None


@dataclass(frozen=True, slots=True)
class LocalActionRunner:
    """Run explicit commands locally, or delegate command-less actions to a handler."""

    registry: DriverRegistry | None = None
    timeout_seconds: float | None = None

    def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
        if action.command is not None:
            return self._run_process(action, context)
        if self.registry is None:
            return ActionAttempt(False, "action has neither a command nor a driver handler")
        try:
            handler = self.registry.action_handler(action.driver)
            with _capture_handler_streams() as (stdout, stderr):
                result = handler.execute(action, context)
        except (DriverProtocolError, OSError, RuntimeError, ValueError) as error:
            return ActionAttempt(False, str(error))
        return ActionAttempt(
            result.success,
            result.summary,
            stdout=stdout.getvalue(),
            stderr=stderr.getvalue(),
            details=result.details,
            value=result.value,
            outputs=result.outputs,
        )

    def _run_process(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
        assert action.command is not None
        replacements = {
            "${POLY_RUN_DIRECTORY}": str(context.run_directory),
            "${POLY_ACTION_DIRECTORY}": str(context.action_directory or context.run_directory),
        }

        def expand(value: str) -> str:
            for marker, replacement in replacements.items():
                value = value.replace(marker, replacement)
            return value

        command = tuple(expand(argument) for argument in action.command)
        environment = os.environ.copy()
        environment.update(context.environment)
        environment.update({key: expand(value) for key, value in action.environment.items()})
        workspace = context.workspace.resolve()
        working_directory = (workspace / Path(action.working_directory)).resolve()
        try:
            working_directory.relative_to(workspace)
        except ValueError:
            return ActionAttempt(
                False,
                f"action working directory escapes workspace: {action.working_directory}",
            )
        if not working_directory.is_dir():
            return ActionAttempt(
                False,
                f"action working directory does not exist: {action.working_directory}",
            )
        try:
            process = subprocess.run(
                command,
                cwd=working_directory,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            return ActionAttempt(
                False,
                f"command timed out after {self.timeout_seconds} seconds",
                stdout=_timeout_text(error.stdout),
                stderr=_timeout_text(error.stderr),
            )
        except OSError as error:
            return ActionAttempt(False, f"unable to start command: {error}")
        return ActionAttempt(
            process.returncode == 0,
            "command completed" if process.returncode == 0 else "command failed",
            process.returncode,
            process.stdout,
            process.stderr,
        )


@dataclass(frozen=True, slots=True, order=True)
class RunEvent:
    sequence: int
    state: ActionState
    action_id: str
    message: str = ""
    occurred_at: str = field(default_factory=lambda: _timestamp(datetime.now(UTC)))
    value: ActionValue | None = None


@dataclass(frozen=True, slots=True)
class ActionResult:
    action_id: str
    state: ActionState
    attempt: ActionAttempt | None = None
    blocked_by: tuple[str, ...] = ()
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    output_directory: str | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    plan_id: str
    status: RunStatus
    actions: tuple[ActionResult, ...]
    events: tuple[RunEvent, ...]
    available_constraints: tuple[str, ...]
    duration_ms: int = 0
    workers: WorkerConfiguration = WorkerConfiguration()


@dataclass(frozen=True, slots=True)
class _CompletedAction:
    result: ActionResult
    produced: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Executor:
    """Execute frozen, deterministic frontiers with bounded admission."""

    runner: ActionRunner
    event_listener: Callable[[RunEvent], None] | None = None
    wall_clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    monotonic_clock: Callable[[], float] = time.monotonic
    jobs: int | str = 1
    worker_limit: int | None = None

    def execute(self, plan: Plan, context: ExecutionContext) -> RunResult:
        run_started_monotonic = self.monotonic_clock()
        workers = resolve_worker_configuration(self.jobs, self.worker_limit)
        events: list[RunEvent] = []
        event_lock = RLock()

        def transition(
            action_id: str,
            state: ActionState,
            message: str = "",
            occurred_at: str | None = None,
            value: ActionValue | None = None,
        ) -> None:
            with event_lock:
                event = RunEvent(
                    len(events) + 1,
                    state,
                    action_id,
                    message,
                    occurred_at or _timestamp(self.wall_clock()),
                    value,
                )
                events.append(event)
                if self.event_listener is not None:
                    self.event_listener(event)

        if plan.status is PlanStatus.EMPTY:
            return RunResult(plan.id, RunStatus.EMPTY, (), (), _constraint_keys(plan), 0, workers)

        for action in plan.actions:
            transition(action.id, ActionState.PLANNED)

        if plan.status is not PlanStatus.EXECUTABLE:
            blocked_results = []
            for action in plan.actions:
                completed_at = _timestamp(self.wall_clock())
                result = ActionResult(
                    action.id,
                    ActionState.BLOCKED,
                    blocked_by=tuple(sorted(item.key for item in action.requires)),
                    completed_at=completed_at,
                )
                blocked_results.append(result)
                transition(action.id, ActionState.BLOCKED, "plan is not executable", completed_at)
            return RunResult(
                plan.id,
                RunStatus.BLOCKED,
                tuple(blocked_results),
                tuple(events),
                _constraint_keys(plan),
                _elapsed_ms(self.monotonic_clock, run_started_monotonic),
                workers,
            )

        available = {constraint.key for constraint in plan.initial_constraints}
        remaining = {action.id: action for action in plan.actions}
        results: dict[str, ActionResult] = {}
        interrupted = False
        pool = ThreadPoolExecutor(max_workers=workers.effective, thread_name_prefix="poly-action")
        try:
            while remaining and not interrupted:
                frontier = tuple(
                    action
                    for action in plan.actions
                    if action.id in remaining
                    and {item.key for item in action.requires}.issubset(available)
                )
                if workers.effective == 1:
                    frontier = frontier[:1]
                if not frontier:
                    self._block_remaining(plan, remaining, available, results, transition)
                    break
                for action in frontier:
                    transition(action.id, ActionState.READY)
                interrupted = self._execute_frontier(
                    pool,
                    frontier,
                    context,
                    results,
                    available,
                    transition,
                    workers.effective,
                )
                for action in frontier:
                    remaining.pop(action.id, None)
            if interrupted:
                self._interrupt_remaining(plan, remaining, results, transition)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

        ordered_results = tuple(results[action.id] for action in plan.actions)
        states = {result.state for result in ordered_results}
        status = (
            RunStatus.INTERRUPTED
            if ActionState.INTERRUPTED in states
            else RunStatus.FAILED
            if ActionState.FAILED in states
            else RunStatus.BLOCKED
            if ActionState.BLOCKED in states
            else RunStatus.SUCCEEDED
        )
        return RunResult(
            plan.id,
            status,
            ordered_results,
            tuple(events),
            tuple(sorted(available)),
            _elapsed_ms(self.monotonic_clock, run_started_monotonic),
            workers,
        )

    def _execute_frontier(
        self,
        pool: ThreadPoolExecutor,
        frontier: tuple[ActionSpec, ...],
        context: ExecutionContext,
        results: dict[str, ActionResult],
        available: set[str],
        transition: Callable[..., None],
        limit: int,
    ) -> bool:
        queued = list(frontier)
        running: dict[Future[_CompletedAction], ActionSpec] = {}
        held_resources: set[str] = set()
        serial_running = False
        interrupted = False

        while queued or running:
            if not interrupted:
                for action in tuple(queued):
                    if len(running) >= limit:
                        break
                    serial = _requires_serial_execution(action)
                    if (serial and running) or serial_running:
                        continue
                    if action.execution_resources & held_resources:
                        continue
                    queued.remove(action)
                    try:
                        action_context = context.for_action(action.id)
                        assert action_context.action_directory is not None
                        action_context.action_directory.mkdir(parents=True, exist_ok=True)
                    except KeyboardInterrupt:
                        interrupted = True
                        queued.insert(0, action)
                        break
                    except BaseException as error:
                        completed_at = _timestamp(self.wall_clock())
                        attempt = ActionAttempt(
                            False,
                            f"action preparation raised {type(error).__name__}: {error}",
                        )
                        results[action.id] = ActionResult(
                            action.id,
                            ActionState.FAILED,
                            attempt,
                            completed_at=completed_at,
                        )
                        transition(action.id, ActionState.FAILED, attempt.summary, completed_at)
                        continue
                    held_resources.update(action.execution_resources)
                    serial_running = serial_running or serial
                    running[pool.submit(self._run_action, action, action_context, transition)] = (
                        action
                    )
            if not running:
                break
            try:
                completed, _ = wait(tuple(running), return_when="FIRST_COMPLETED")
            except KeyboardInterrupt:
                interrupted = True
                continue
            for future in completed:
                action = running.pop(future)
                held_resources.difference_update(action.execution_resources)
                serial_running = any(_requires_serial_execution(item) for item in running.values())
                try:
                    completed_action = future.result()
                except KeyboardInterrupt:
                    interrupted = True
                    completed_at = _timestamp(self.wall_clock())
                    result = ActionResult(
                        action.id, ActionState.INTERRUPTED, completed_at=completed_at
                    )
                    transition(
                        action.id,
                        ActionState.INTERRUPTED,
                        "execution interrupted",
                        completed_at,
                    )
                    results[action.id] = result
                except BaseException as error:
                    attempt = ActionAttempt(
                        False, f"action runner raised {type(error).__name__}: {error}"
                    )
                    completed_at = _timestamp(self.wall_clock())
                    result = ActionResult(
                        action.id,
                        ActionState.FAILED,
                        attempt,
                        completed_at=completed_at,
                    )
                    transition(action.id, ActionState.FAILED, attempt.summary, completed_at)
                    results[action.id] = result
                else:
                    results[action.id] = completed_action.result
                    available.update(completed_action.produced)

        if interrupted:
            for action in queued:
                completed_at = _timestamp(self.wall_clock())
                results[action.id] = ActionResult(
                    action.id, ActionState.INTERRUPTED, completed_at=completed_at
                )
                transition(
                    action.id,
                    ActionState.INTERRUPTED,
                    "not admitted after interruption",
                    completed_at,
                )
        return interrupted

    def _run_action(
        self,
        action: ActionSpec,
        action_context: ExecutionContext,
        transition: Callable[..., None],
    ) -> _CompletedAction:
        assert action_context.action_directory is not None
        started_at = _timestamp(self.wall_clock())
        action_started_monotonic = self.monotonic_clock()
        transition(action.id, ActionState.RUNNING, "", started_at)
        try:
            attempt = self.runner.run(action, action_context)
        except Exception as error:
            attempt = ActionAttempt(False, f"action runner raised {type(error).__name__}: {error}")
        completed_at = _timestamp(self.wall_clock())
        duration_ms = _elapsed_ms(self.monotonic_clock, action_started_monotonic)
        try:
            _persist_action_attempt(action_context.action_directory, attempt)
        except OSError as error:
            attempt = ActionAttempt(
                False,
                f"unable to persist isolated action output: {error}",
                stdout=attempt.stdout,
                stderr=attempt.stderr,
            )
        state = ActionState.SUCCEEDED if attempt.success else ActionState.FAILED
        result = ActionResult(
            action.id,
            state,
            attempt,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            output_directory=action_context.action_directory.relative_to(
                action_context.run_directory
            ).as_posix(),
        )
        transition(action.id, state, attempt.summary, completed_at, attempt.value)
        produced = tuple(item.key for item in action.produces) if attempt.success else ()
        return _CompletedAction(result, produced)

    def _block_remaining(
        self,
        plan: Plan,
        remaining: dict[str, ActionSpec],
        available: set[str],
        results: dict[str, ActionResult],
        transition: Callable[..., None],
    ) -> None:
        for action in plan.actions:
            if action.id not in remaining:
                continue
            missing = tuple(
                sorted(item.key for item in action.requires if item.key not in available)
            )
            completed_at = _timestamp(self.wall_clock())
            results[action.id] = ActionResult(
                action.id,
                ActionState.BLOCKED,
                blocked_by=missing,
                completed_at=completed_at,
            )
            transition(action.id, ActionState.BLOCKED, ", ".join(missing), completed_at)

    def _interrupt_remaining(
        self,
        plan: Plan,
        remaining: dict[str, ActionSpec],
        results: dict[str, ActionResult],
        transition: Callable[..., None],
    ) -> None:
        for action in plan.actions:
            if action.id not in remaining or action.id in results:
                continue
            completed_at = _timestamp(self.wall_clock())
            results[action.id] = ActionResult(
                action.id, ActionState.INTERRUPTED, completed_at=completed_at
            )
            transition(
                action.id,
                ActionState.INTERRUPTED,
                "not admitted after interruption",
                completed_at,
            )


def resolve_worker_configuration(
    requested: int | str, policy_limit: int | None = None
) -> WorkerConfiguration:
    if policy_limit is not None and (isinstance(policy_limit, bool) or policy_limit < 1):
        raise ValueError("worker limit must be a positive integer")
    if requested == "auto":
        effective = automatic_worker_capacity()
        if policy_limit is not None:
            effective = min(effective, policy_limit)
        return WorkerConfiguration(WorkerMode.AUTO, None, max(1, effective))
    if isinstance(requested, bool):
        raise ValueError("jobs must be 'auto' or a positive integer")
    try:
        value = int(requested)
    except (TypeError, ValueError) as error:
        raise ValueError("jobs must be 'auto' or a positive integer") from error
    if value < 1 or str(value) != str(requested):
        raise ValueError("jobs must be 'auto' or a positive integer")
    effective = min(value, policy_limit) if policy_limit is not None else value
    return WorkerConfiguration(WorkerMode.EXPLICIT, value, effective)


def automatic_worker_capacity() -> int:
    """Return process-visible capacity, conservatively falling back to one."""

    candidates = [
        _process_cpu_count(),
        _affinity_cpu_count(),
        _cgroup_cpu_quota(),
        _windows_affinity_cpu_count(),
    ]
    positive = [value for value in candidates if value is not None and value > 0]
    return max(1, min(positive)) if positive else 1


def _process_cpu_count() -> int | None:
    function = getattr(os, "process_cpu_count", None)
    if function is None:
        return None
    try:
        return cast(int | None, function())
    except OSError:
        return None


def _affinity_cpu_count() -> int | None:
    function = getattr(os, "sched_getaffinity", None)
    if function is None:
        return None
    try:
        return len(function(0))
    except OSError:
        return None


def _cgroup_cpu_quota() -> int | None:
    try:
        unified = Path("/sys/fs/cgroup/cpu.max")
        if unified.is_file():
            quota_text, period_text = unified.read_text(encoding="ascii").split()[:2]
            if quota_text != "max":
                quota = int(quota_text)
                period = int(period_text)
                return max(1, quota // period)
        quota_path = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
        period_path = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if quota_path.is_file() and period_path.is_file():
            quota = int(quota_path.read_text(encoding="ascii"))
            period = int(period_path.read_text(encoding="ascii"))
            if quota > 0 and period > 0:
                return max(1, quota // period)
    except (OSError, ValueError):
        return None
    return None


def _windows_affinity_cpu_count() -> int | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        process_mask = ctypes.c_size_t()
        system_mask = ctypes.c_size_t()
        windows_dll = cast(Any, ctypes.WinDLL)  # type: ignore[attr-defined]
        kernel32 = windows_dll("kernel32", use_last_error=True)
        process = kernel32.GetCurrentProcess()
        if not kernel32.GetProcessAffinityMask(
            process, ctypes.byref(process_mask), ctypes.byref(system_mask)
        ):
            return None
        return process_mask.value.bit_count()
    except (AttributeError, OSError, ValueError):
        return None


def _requires_serial_execution(action: ActionSpec) -> bool:
    return not action.concurrency_safe


def _persist_action_attempt(directory: Path, attempt: ActionAttempt) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "stdout.txt").write_text(attempt.stdout, encoding="utf-8")
    (directory / "stderr.txt").write_text(attempt.stderr, encoding="utf-8")
    details: dict[str, JsonValue] = {
        "success": attempt.success,
        "summary": attempt.summary,
        "exit_code": attempt.exit_code,
        "details": dict(attempt.details),
    }
    (directory / "details.json").write_text(
        json.dumps(details, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _constraint_keys(plan: Plan) -> tuple[str, ...]:
    return tuple(sorted(constraint.key for constraint in plan.initial_constraints))


def _elapsed_ms(clock: Callable[[], float], started: float) -> int:
    return max(0, round((clock() - started) * 1000))


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
