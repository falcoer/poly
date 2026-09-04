"""Sequential execution of frozen Poly plans."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from io import StringIO
from types import MappingProxyType
from typing import Protocol, runtime_checkable

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


class RunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    EMPTY = "empty"


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
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
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
        run_directory = str(context.run_directory)
        command = tuple(
            argument.replace("${POLY_RUN_DIRECTORY}", run_directory) for argument in action.command
        )
        environment = os.environ.copy()
        environment.update(context.environment)
        environment.update(
            {
                key: value.replace("${POLY_RUN_DIRECTORY}", run_directory)
                for key, value in action.environment.items()
            }
        )
        try:
            process = subprocess.run(
                command,
                cwd=context.workspace,
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


@dataclass(frozen=True, slots=True)
class RunResult:
    plan_id: str
    status: RunStatus
    actions: tuple[ActionResult, ...]
    events: tuple[RunEvent, ...]
    available_constraints: tuple[str, ...]
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class Executor:
    """Execute only the actions already present in a plan."""

    runner: ActionRunner
    event_listener: Callable[[RunEvent], None] | None = None
    wall_clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    monotonic_clock: Callable[[], float] = time.monotonic

    def execute(self, plan: Plan, context: ExecutionContext) -> RunResult:
        run_started_monotonic = self.monotonic_clock()
        if plan.status is PlanStatus.EMPTY:
            return RunResult(plan.id, RunStatus.EMPTY, (), (), _constraint_keys(plan), 0)
        if plan.status is not PlanStatus.EXECUTABLE:
            blocked_results = tuple(
                ActionResult(
                    action.id,
                    ActionState.BLOCKED,
                    blocked_by=tuple(sorted(constraint.key for constraint in action.requires)),
                    completed_at=_timestamp(self.wall_clock()),
                )
                for action in plan.actions
            )
            planned_events = tuple(
                RunEvent(
                    index,
                    ActionState.PLANNED,
                    result.action_id,
                    occurred_at=_timestamp(self.wall_clock()),
                )
                for index, result in enumerate(blocked_results, start=1)
            )
            blocked_events = planned_events + tuple(
                RunEvent(
                    len(planned_events) + index,
                    ActionState.BLOCKED,
                    result.action_id,
                    "plan is not executable",
                    result.completed_at or _timestamp(self.wall_clock()),
                )
                for index, result in enumerate(blocked_results, start=1)
            )
            if self.event_listener is not None:
                for event in blocked_events:
                    self.event_listener(event)
            return RunResult(
                plan.id,
                RunStatus.BLOCKED,
                blocked_results,
                blocked_events,
                _constraint_keys(plan),
                max(0, round((self.monotonic_clock() - run_started_monotonic) * 1000)),
            )

        available = {constraint.key for constraint in plan.initial_constraints}
        remaining = {action.id: action for action in plan.actions}
        results: dict[str, ActionResult] = {}
        events = [
            RunEvent(
                index,
                ActionState.PLANNED,
                action.id,
                occurred_at=_timestamp(self.wall_clock()),
            )
            for index, action in enumerate(plan.actions, start=1)
        ]
        if self.event_listener is not None:
            for event in events:
                self.event_listener(event)

        def transition(
            action_id: str,
            state: ActionState,
            message: str = "",
            occurred_at: str | None = None,
            value: ActionValue | None = None,
        ) -> None:
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

        while remaining:
            ready = sorted(
                action_id
                for action_id, action in remaining.items()
                if {constraint.key for constraint in action.requires}.issubset(available)
            )
            if not ready:
                for action_id in sorted(remaining):
                    action = remaining[action_id]
                    missing = tuple(
                        sorted(
                            constraint.key
                            for constraint in action.requires
                            if constraint.key not in available
                        )
                    )
                    results[action_id] = ActionResult(
                        action_id,
                        ActionState.BLOCKED,
                        blocked_by=missing,
                        completed_at=_timestamp(self.wall_clock()),
                    )
                    transition(
                        action_id,
                        ActionState.BLOCKED,
                        ", ".join(missing),
                        results[action_id].completed_at,
                    )
                break

            action_id = ready[0]
            action = remaining.pop(action_id)
            transition(action_id, ActionState.READY)
            started_wall = self.wall_clock()
            started_at = _timestamp(started_wall)
            action_started_monotonic = self.monotonic_clock()
            transition(action_id, ActionState.RUNNING, occurred_at=started_at)
            try:
                attempt = self.runner.run(action, context)
            except Exception as error:  # executor boundary: a driver must not abort the run
                attempt = ActionAttempt(
                    False, f"action runner raised {type(error).__name__}: {error}"
                )
            completed_at = _timestamp(self.wall_clock())
            duration_ms = max(0, round((self.monotonic_clock() - action_started_monotonic) * 1000))
            if attempt.success:
                available.update(constraint.key for constraint in action.produces)
                state = ActionState.SUCCEEDED
            else:
                state = ActionState.FAILED
            results[action_id] = ActionResult(
                action_id,
                state,
                attempt,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
            )
            transition(action_id, state, attempt.summary, completed_at, attempt.value)

        ordered_results = tuple(results[action.id] for action in plan.actions)
        states = {result.state for result in ordered_results}
        status = (
            RunStatus.FAILED
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
            max(0, round((self.monotonic_clock() - run_started_monotonic) * 1000)),
        )


def _constraint_keys(plan: Plan) -> tuple[str, ...]:
    return tuple(sorted(constraint.key for constraint in plan.initial_constraints))


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
