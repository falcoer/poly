"""Sequential execution of frozen Poly plans."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from poly.driver import DriverProtocolError, DriverRegistry, ExecutionContext
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


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
            result = handler.execute(action, context)
        except (DriverProtocolError, OSError, RuntimeError, ValueError) as error:
            return ActionAttempt(False, str(error))
        return ActionAttempt(result.success, result.summary, details=result.details)

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


@dataclass(frozen=True, slots=True)
class ActionResult:
    action_id: str
    state: ActionState
    attempt: ActionAttempt | None = None
    blocked_by: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunResult:
    plan_id: str
    status: RunStatus
    actions: tuple[ActionResult, ...]
    events: tuple[RunEvent, ...]
    available_constraints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Executor:
    """Execute only the actions already present in a plan."""

    runner: ActionRunner

    def execute(self, plan: Plan, context: ExecutionContext) -> RunResult:
        if plan.status is PlanStatus.EMPTY:
            return RunResult(plan.id, RunStatus.EMPTY, (), (), _constraint_keys(plan))
        if plan.status is not PlanStatus.EXECUTABLE:
            blocked_results = tuple(
                ActionResult(
                    action.id,
                    ActionState.BLOCKED,
                    blocked_by=tuple(sorted(constraint.key for constraint in action.requires)),
                )
                for action in plan.actions
            )
            planned_events = tuple(
                RunEvent(index, ActionState.PLANNED, result.action_id)
                for index, result in enumerate(blocked_results, start=1)
            )
            blocked_events = planned_events + tuple(
                RunEvent(
                    len(planned_events) + index,
                    ActionState.BLOCKED,
                    result.action_id,
                    "plan is not executable",
                )
                for index, result in enumerate(blocked_results, start=1)
            )
            return RunResult(
                plan.id,
                RunStatus.BLOCKED,
                blocked_results,
                blocked_events,
                _constraint_keys(plan),
            )

        available = {constraint.key for constraint in plan.initial_constraints}
        remaining = {action.id: action for action in plan.actions}
        results: dict[str, ActionResult] = {}
        events = [
            RunEvent(index, ActionState.PLANNED, action.id)
            for index, action in enumerate(plan.actions, start=1)
        ]

        def transition(action_id: str, state: ActionState, message: str = "") -> None:
            events.append(RunEvent(len(events) + 1, state, action_id, message))

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
                        action_id, ActionState.BLOCKED, blocked_by=missing
                    )
                    transition(action_id, ActionState.BLOCKED, ", ".join(missing))
                break

            action_id = ready[0]
            action = remaining.pop(action_id)
            transition(action_id, ActionState.READY)
            transition(action_id, ActionState.RUNNING)
            try:
                attempt = self.runner.run(action, context)
            except Exception as error:  # executor boundary: a driver must not abort the run
                attempt = ActionAttempt(
                    False, f"action runner raised {type(error).__name__}: {error}"
                )
            if attempt.success:
                available.update(constraint.key for constraint in action.produces)
                state = ActionState.SUCCEEDED
            else:
                state = ActionState.FAILED
            results[action_id] = ActionResult(action_id, state, attempt)
            transition(action_id, state, attempt.summary)

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
        )


def _constraint_keys(plan: Plan) -> tuple[str, ...]:
    return tuple(sorted(constraint.key for constraint in plan.initial_constraints))


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
