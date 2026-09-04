from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from poly.driver import (
    DriverExecutionResult,
    DriverRegistry,
    ExecutionContext,
    OutputReference,
)
from poly.model import ActionSpec, Constraint, Plan, PlanStatus
from poly.runtime import (
    ActionAttempt,
    ActionRunner,
    ActionState,
    Executor,
    LocalActionRunner,
    RunEvent,
    RunStatus,
)


@dataclass
class StubRunner:
    attempts: dict[str, ActionAttempt]
    calls: list[str]

    def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
        assert context.workspace.is_dir()
        self.calls.append(action.id)
        return self.attempts[action.id]


def _action(
    action_id: str,
    *,
    requires: tuple[str, ...] = (),
    produces: tuple[str, ...] = (),
) -> ActionSpec:
    return ActionSpec(
        action_id,
        "fixture",
        "verify",
        "fixture/verify",
        ("node",),
        requires=frozenset(Constraint(key) for key in requires),
        produces=frozenset(Constraint(key) for key in produces),
    )


def _plan(actions: tuple[ActionSpec, ...], status: PlanStatus = PlanStatus.EXECUTABLE) -> Plan:
    return Plan("plan", "verify", ("node",), actions, (), (), status)


def test_executor_runs_ready_actions_and_blocks_failed_dependants(tmp_path: Path) -> None:
    actions = (
        _action("a", produces=("a/done",)),
        _action("b", requires=("a/done",), produces=("b/done",)),
        _action("c", requires=("b/done",)),
        _action("d"),
    )
    runner = StubRunner(
        {
            "a": ActionAttempt(True, "a ok"),
            "b": ActionAttempt(False, "b failed", 3, stderr="failure"),
            "d": ActionAttempt(True, "d ok"),
        },
        [],
    )
    run_directory = tmp_path / ".poly" / "runs" / "plan"
    context = ExecutionContext(tmp_path, run_directory)

    plan = _plan(actions)
    result = Executor(runner).execute(plan, context)

    assert isinstance(runner, ActionRunner)
    assert runner.calls == ["a", "b", "d"]
    assert result.status is RunStatus.FAILED
    assert [item.state for item in result.actions] == [
        ActionState.SUCCEEDED,
        ActionState.FAILED,
        ActionState.BLOCKED,
        ActionState.SUCCEEDED,
    ]
    assert result.actions[2].blocked_by == ("b/done",)
    assert result.available_constraints == ("a/done",)
    assert tuple(action.id for action in plan.actions) == ("a", "b", "c", "d")
    assert [event.sequence for event in result.events] == list(range(1, len(result.events) + 1))


def test_executor_publishes_each_event_as_it_happens(tmp_path: Path) -> None:
    runner = StubRunner({"action": ActionAttempt(True, "done")}, [])
    context = ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / "plan")
    events: list[RunEvent] = []

    result = Executor(runner, events.append).execute(_plan((_action("action"),)), context)

    assert events == list(result.events)
    assert [event.state for event in events] == [
        ActionState.PLANNED,
        ActionState.READY,
        ActionState.RUNNING,
        ActionState.SUCCEEDED,
    ]


def test_executor_does_not_run_empty_or_invalid_plans(tmp_path: Path) -> None:
    runner = StubRunner({}, [])
    context = ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / "plan")

    empty = Executor(runner).execute(_plan((), PlanStatus.EMPTY), context)
    blocked = Executor(runner).execute(
        _plan((_action("blocked", requires=("missing",)),), PlanStatus.BLOCKED),
        context,
    )

    assert empty.status is RunStatus.EMPTY
    assert blocked.status is RunStatus.BLOCKED
    assert blocked.actions[0].state is ActionState.BLOCKED
    assert runner.calls == []


def test_executor_contains_runner_exceptions(tmp_path: Path) -> None:
    class RaisingRunner:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            raise RuntimeError(f"boom {action.id}")

    context = ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / "plan")
    result = Executor(RaisingRunner()).execute(_plan((_action("broken"),)), context)

    assert result.status is RunStatus.FAILED
    assert result.actions[0].attempt is not None
    assert "RuntimeError" in result.actions[0].attempt.summary


def test_local_runner_executes_explicit_command_and_expands_run_directory(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / ".poly" / "runs" / "plan"
    action = ActionSpec(
        "process",
        "fixture",
        "verify",
        "fixture/process",
        ("node",),
        command=(
            sys.executable,
            "-c",
            "import os; print(os.environ['RUN_DIR'])",
        ),
        environment={"RUN_DIR": "${POLY_RUN_DIRECTORY}"},
    )

    attempt = LocalActionRunner().run(action, ExecutionContext(tmp_path, run_directory))

    assert attempt.success
    assert attempt.exit_code == 0
    assert attempt.stdout.strip() == str(run_directory)


def test_local_runner_reports_missing_commands_and_handlers(tmp_path: Path) -> None:
    context = ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / "plan")
    command = ActionSpec(
        "missing-command",
        "fixture",
        "verify",
        "fixture/process",
        ("node",),
        command=("poly-command-that-does-not-exist",),
    )
    handler = _action("missing-handler")

    command_attempt = LocalActionRunner().run(command, context)
    handler_attempt = LocalActionRunner().run(handler, context)

    assert not command_attempt.success
    assert "unable to start" in command_attempt.summary
    assert not handler_attempt.success
    assert "neither a command" in handler_attempt.summary


def test_local_runner_captures_handler_streams_and_structured_result(tmp_path: Path) -> None:
    class Handler:
        def execute(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
            print(f"working on {action.id}")
            print("diagnostic", file=sys.stderr)
            return DriverExecutionResult(
                True,
                "complete",
                value="1.2.3",
                outputs=(OutputReference("file", "report.txt"),),
            )

    class Registry:
        def action_handler(self, driver: str) -> Handler:
            assert driver == "fixture"
            return Handler()

    context = ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / "plan")
    runner = LocalActionRunner(cast(DriverRegistry, Registry()))
    attempt = runner.run(_action("captured"), context)

    assert attempt.stdout == "working on captured\n"
    assert attempt.stderr == "diagnostic\n"
    assert attempt.value is not None and attempt.value.value == "1.2.3"
    assert attempt.outputs[0].target == "report.txt"


def test_executor_records_utc_instants_and_monotonic_duration(tmp_path: Path) -> None:
    start = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    wall_values = iter(
        (start, start + timedelta(milliseconds=1), start + timedelta(milliseconds=2), start)
    )
    monotonic_values = iter((10.0, 10.125, 10.250, 10.300))
    runner = StubRunner({"action": ActionAttempt(True, "done")}, [])
    context = ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / "plan")

    result = Executor(
        runner,
        wall_clock=lambda: next(wall_values),
        monotonic_clock=lambda: next(monotonic_values),
    ).execute(_plan((_action("action"),)), context)

    action = result.actions[0]
    assert action.started_at == "2026-09-02T12:00:00.002Z"
    assert action.completed_at == "2026-09-02T12:00:00.000Z"
    assert action.duration_ms == 125
    assert result.duration_ms == 300
    assert all(event.occurred_at.endswith("Z") for event in result.events)
    assert [event.sequence for event in result.events] == [1, 2, 3, 4]


def test_executor_total_duration_covers_all_actions(tmp_path: Path) -> None:
    start = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    monotonic_values = iter((10.0, 10.100, 10.200, 10.300, 10.301, 10.302))
    runner = StubRunner(
        {
            "first": ActionAttempt(True, "done"),
            "second": ActionAttempt(True, "done"),
        },
        [],
    )
    context = ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / "plan")

    result = Executor(
        runner,
        wall_clock=lambda: start,
        monotonic_clock=lambda: next(monotonic_values),
    ).execute(_plan((_action("first"), _action("second"))), context)

    assert result.actions[0].duration_ms == 100
    assert result.actions[1].duration_ms == 1
    assert result.duration_ms == 302
