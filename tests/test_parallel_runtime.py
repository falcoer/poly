from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event, Lock, Thread
from types import ModuleType
from typing import Any, cast

import pytest
from ruamel.yaml import YAML

import poly.runtime as runtime
from poly.driver import DriverExecutionResult, DriverRegistry, ExecutionContext
from poly.model import ActionSpec, Constraint, Plan, PlanStatus
from poly.persistence import StateStore
from poly.reporting import construction_document, render
from poly.runtime import (
    ActionAttempt,
    ActionState,
    Executor,
    LocalActionRunner,
    RunStatus,
    WorkerMode,
    resolve_worker_configuration,
)


def _action(
    action_id: str,
    *,
    requires: tuple[str, ...] = (),
    produces: tuple[str, ...] = (),
    resources: tuple[str, ...] = (),
    safe: bool = True,
) -> ActionSpec:
    return ActionSpec(
        action_id,
        "plugin-driver",
        "verify",
        "fixture/verify",
        ("node",),
        requires=frozenset(Constraint(value) for value in requires),
        produces=frozenset(Constraint(value) for value in produces),
        execution_resources=frozenset(resources),
        concurrency_safe=safe,
    )


def _plan(actions: tuple[ActionSpec, ...]) -> Plan:
    return Plan("stable-plan", "verify", ("node",), actions, (), (), PlanStatus.EXECUTABLE)


def _context(tmp_path: Path) -> ExecutionContext:
    return ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / "stable-plan")


def test_frontier_is_frozen_and_next_level_waits_for_every_ready_action(
    tmp_path: Path,
) -> None:
    initial_front = Barrier(2)
    sibling_completed = Event()
    calls: list[str] = []
    lock = Lock()

    class Runner:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            with lock:
                calls.append(action.id)
            if action.id in {"a", "d"}:
                initial_front.wait(timeout=5)
            if action.id == "d":
                sibling_completed.set()
            if action.id == "b":
                assert sibling_completed.is_set()
            return ActionAttempt(True, action.id)

    plan = _plan(
        (
            _action("a", produces=("a/done",)),
            _action("b", requires=("a/done",)),
            _action("d"),
        )
    )
    result = Executor(Runner(), jobs=2).execute(plan, _context(tmp_path))

    assert set(calls[:2]) == {"a", "d"}
    assert calls[2] == "b"
    assert [event.action_id for event in result.events if event.state is ActionState.READY] == [
        "a",
        "d",
        "b",
    ]


def test_worker_limit_is_never_exceeded(tmp_path: Path) -> None:
    first_pair = Barrier(2)
    lock = Lock()
    active = 0
    maximum = 0

    class Runner:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            if action.id in {"a", "b"}:
                first_pair.wait(timeout=5)
            with lock:
                active -= 1
            return ActionAttempt(True, action.id)

    result = Executor(Runner(), jobs=2).execute(
        _plan((_action("a"), _action("b"), _action("c"))), _context(tmp_path)
    )

    assert result.status is RunStatus.SUCCEEDED
    assert maximum == 2
    assert result.workers.effective == 2


def test_resources_serialize_conflicts_while_independent_actions_overlap(
    tmp_path: Path,
) -> None:
    overlap = Barrier(2)
    first_released = Event()

    class Runner:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            if action.id in {"same-a", "other"}:
                overlap.wait(timeout=5)
            if action.id == "same-a":
                first_released.set()
            if action.id == "same-b":
                assert first_released.is_set()
            return ActionAttempt(True, action.id)

    Executor(Runner(), jobs=3).execute(
        _plan(
            (
                _action("same-a", resources=("repository:one",)),
                _action("same-b", resources=("repository:one",)),
                _action("other", resources=("repository:two",)),
            )
        ),
        _context(tmp_path),
    )


def test_unsafe_handlers_and_structural_actions_are_conservatively_serialized(
    tmp_path: Path,
) -> None:
    first_started = Event()
    release_first = Event()
    second_started = Event()
    result: list[RunStatus] = []

    class Runner:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            if action.id == "structural":
                first_started.set()
                release_first.wait(timeout=5)
            else:
                second_started.set()
            return ActionAttempt(True, action.id)

    structural = replace(_action("structural", safe=False), changes_structure=True)

    def execute() -> None:
        execution = Executor(Runner(), jobs=4).execute(
            _plan((structural, _action("legacy-handler", safe=False))), _context(tmp_path)
        )
        result.append(execution.status)

    thread = Thread(target=execute)
    thread.start()
    assert first_started.wait(timeout=5)
    assert not second_started.is_set()
    release_first.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert result == [RunStatus.SUCCEEDED]


def test_failure_exception_and_only_failed_descendants_are_contained(tmp_path: Path) -> None:
    siblings = Barrier(3)

    class Runner:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            if action.id in {"failed", "raised", "independent"}:
                siblings.wait(timeout=5)
            if action.id == "failed":
                return ActionAttempt(False, "expected failure")
            if action.id == "raised":
                raise RuntimeError("isolated boom")
            return ActionAttempt(True, action.id)

    result = Executor(Runner(), jobs=3).execute(
        _plan(
            (
                _action("failed", produces=("failed/done",)),
                _action("raised"),
                _action("descendant", requires=("failed/done",)),
                _action("independent"),
            )
        ),
        _context(tmp_path),
    )

    assert [item.state for item in result.actions] == [
        ActionState.FAILED,
        ActionState.FAILED,
        ActionState.BLOCKED,
        ActionState.SUCCEEDED,
    ]
    assert result.actions[2].blocked_by == ("failed/done",)
    assert result.actions[1].attempt is not None
    assert "RuntimeError" in result.actions[1].attempt.summary


def test_interruption_stops_admission_and_returns_a_complete_report(tmp_path: Path) -> None:
    started = Barrier(2)

    class Runner:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            if action.id in {"interrupt", "sibling"}:
                started.wait(timeout=5)
            if action.id == "interrupt":
                raise KeyboardInterrupt
            return ActionAttempt(True, action.id)

    plan = _plan(
        (
            _action("interrupt", produces=("continue",)),
            _action("next", requires=("continue",)),
            _action("sibling", produces=("sibling/done",)),
            _action("later", requires=("sibling/done",)),
        )
    )
    result = Executor(Runner(), jobs=2).execute(plan, _context(tmp_path))

    assert result.status is RunStatus.INTERRUPTED
    assert len(result.actions) == 4
    assert result.actions[0].state is ActionState.INTERRUPTED
    assert result.actions[2].state is ActionState.SUCCEEDED
    assert result.actions[1].state is ActionState.INTERRUPTED
    assert result.actions[3].state is ActionState.INTERRUPTED
    document = construction_document(tmp_path, plan, result)
    store = StateStore(tmp_path)
    store.save_run(result.plan_id, document)
    loaded_run = store.load_report(result.plan_id)["run"]
    assert isinstance(loaded_run, dict)
    assert loaded_run["status"] == "interrupted"


def test_concurrent_handler_streams_and_persisted_outputs_are_action_isolated(
    tmp_path: Path,
) -> None:
    overlap = Barrier(2)

    class Handler:
        def execute(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
            overlap.wait(timeout=5)
            print(f"stdout:{action.id}")
            print(f"stderr:{action.id}", file=sys.stderr)
            return DriverExecutionResult(True, action.id, {"action": action.id})

    class Registry:
        def action_handler(self, driver: str) -> Handler:
            assert driver == "plugin-driver"
            return Handler()

    result = Executor(LocalActionRunner(cast(DriverRegistry, Registry())), jobs=2).execute(
        _plan((_action("a"), _action("b"))), _context(tmp_path)
    )

    assert [cast(ActionAttempt, item.attempt).stdout for item in result.actions] == [
        "stdout:a\n",
        "stdout:b\n",
    ]
    assert [cast(ActionAttempt, item.attempt).stderr for item in result.actions] == [
        "stderr:a\n",
        "stderr:b\n",
    ]
    action_root = _context(tmp_path).run_directory / "actions"
    stdout_files = sorted(path.read_text() for path in action_root.glob("*/stdout.txt"))
    assert stdout_files == ["stdout:a\n", "stdout:b\n"]
    assert len(tuple(action_root.glob("*/details.json"))) == 2
    assert all(item.output_directory is not None for item in result.actions)


def test_global_events_follow_real_completion_order_with_one_sequence(tmp_path: Path) -> None:
    both_started = Barrier(2)
    allow_first = Event()
    completion_order: list[str] = []

    class Runner:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            both_started.wait(timeout=5)
            if action.id == "a":
                allow_first.wait(timeout=5)
            else:
                completion_order.append("b")
                allow_first.set()
            if action.id == "a":
                completion_order.append("a")
            return ActionAttempt(True, action.id)

    result = Executor(Runner(), jobs=2).execute(
        _plan((_action("a"), _action("b"))), _context(tmp_path)
    )
    terminals = [event.action_id for event in result.events if event.state is ActionState.SUCCEEDED]

    assert completion_order == ["b", "a"]
    assert terminals == ["b", "a"]
    assert [event.sequence for event in result.events] == list(range(1, len(result.events) + 1))
    for action_id in ("a", "b"):
        states = [event.state for event in result.events if event.action_id == action_id]
        assert states.index(ActionState.RUNNING) < states.index(ActionState.SUCCEEDED)


def test_jobs_one_preserves_sequential_admission_and_plan_identity(tmp_path: Path) -> None:
    calls: list[str] = []

    class Runner:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            calls.append(action.id)
            return ActionAttempt(True, action.id)

    plan = _plan(
        (
            _action("a", produces=("a/done",)),
            _action("b", requires=("a/done",)),
            _action("d"),
        )
    )
    sequential = Executor(Runner(), jobs=1).execute(plan, _context(tmp_path))
    parallel = Executor(Runner(), jobs=4).execute(plan, _context(tmp_path))

    assert calls[:3] == ["a", "b", "d"]
    assert sequential.plan_id == parallel.plan_id == plan.id
    assert [item.action_id for item in parallel.actions] == ["a", "b", "d"]


def test_auto_capacity_uses_visible_minimum_and_conservative_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime, "_process_cpu_count", lambda: 8)
    monkeypatch.setattr(runtime, "_affinity_cpu_count", lambda: 4)
    monkeypatch.setattr(runtime, "_cgroup_cpu_quota", lambda: 2)
    monkeypatch.setattr(runtime, "_windows_affinity_cpu_count", lambda: None)
    automatic = resolve_worker_configuration("auto")

    assert automatic.requested_mode is WorkerMode.AUTO
    assert automatic.requested is None
    assert automatic.effective == 2
    assert resolve_worker_configuration("auto", 1).effective == 1

    monkeypatch.setattr(runtime, "_process_cpu_count", lambda: None)
    monkeypatch.setattr(runtime, "_affinity_cpu_count", lambda: None)
    monkeypatch.setattr(runtime, "_cgroup_cpu_quota", lambda: None)
    assert runtime.automatic_worker_capacity() == 1


@pytest.mark.parametrize("requested, limit", [(True, None), ("many", None), (0, None), (1, 0)])
def test_invalid_worker_configuration_is_rejected(requested: int | str, limit: int | None) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        resolve_worker_configuration(requested, limit)


def test_capacity_probes_handle_errors_and_cgroup_quotas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> int:
        raise OSError("unavailable")

    def unavailable_affinity(pid: int) -> set[int]:
        raise OSError("unavailable")

    monkeypatch.setattr(os, "process_cpu_count", unavailable, raising=False)
    monkeypatch.setattr(os, "sched_getaffinity", unavailable_affinity, raising=False)
    assert runtime._process_cpu_count() is None
    assert runtime._affinity_cpu_count() is None

    class CgroupPath:
        def __init__(self, value: str) -> None:
            self.value = value

        def is_file(self) -> bool:
            return self.value.endswith("cpu.max")

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "ascii"
            return "150000 100000"

    monkeypatch.setattr("poly.runtime.Path", CgroupPath)
    assert runtime._cgroup_cpu_quota() == 1


def test_system_exit_and_output_persistence_errors_remain_action_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ExitingRunner:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            raise SystemExit("driver exit")

    exited = Executor(ExitingRunner()).execute(_plan((_action("exit"),)), _context(tmp_path))
    assert exited.actions[0].state is ActionState.FAILED
    assert exited.actions[0].attempt is not None
    assert "SystemExit" in exited.actions[0].attempt.summary

    def cannot_persist(directory: Path, attempt: ActionAttempt) -> None:
        raise OSError("read-only output")

    monkeypatch.setattr(runtime, "_persist_action_attempt", cannot_persist)

    class SuccessfulRunner:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            return ActionAttempt(True, "was successful", stdout="retained")

    failed = Executor(SuccessfulRunner()).execute(
        _plan((_action("persistence"),)), _context(tmp_path)
    )
    assert failed.actions[0].state is ActionState.FAILED
    assert failed.actions[0].attempt is not None
    assert "unable to persist" in failed.actions[0].attempt.summary
    assert failed.actions[0].attempt.stdout == "retained"


def test_windows_affinity_count_and_posix_affinity_are_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Value:
        value = 0

        def __init__(self) -> None:
            self.value = 0

    class Kernel:
        @staticmethod
        def GetCurrentProcess() -> int:
            return 1

        @staticmethod
        def GetProcessAffinityMask(process: object, process_mask: Any, system_mask: Any) -> bool:
            process_mask._obj.value = 0b1011
            system_mask._obj.value = 0b1111
            return True

    class Reference:
        def __init__(self, value: Value) -> None:
            self._obj = value

    def byref(value: Value) -> Reference:
        return Reference(value)

    def windows_dll(name: str, use_last_error: bool) -> Kernel:
        return Kernel()

    fake_ctypes = ModuleType("ctypes")
    fake_ctypes.c_size_t = Value  # type: ignore[attr-defined]
    fake_ctypes.byref = byref  # type: ignore[attr-defined]
    fake_ctypes.WinDLL = windows_dll  # type: ignore[attr-defined]

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    assert runtime._windows_affinity_cpu_count() == 3

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {0, 2, 4}, raising=False)
    assert runtime._affinity_cpu_count() == 3


def test_json_yaml_and_xml_reports_record_requested_and_effective_workers(
    tmp_path: Path,
) -> None:
    plan = _plan((_action("action"),))

    class Runner:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            return ActionAttempt(True, "done")

    result = Executor(Runner(), jobs=4, worker_limit=2).execute(plan, _context(tmp_path))
    document = construction_document(tmp_path, plan, result)
    json_value = json.loads(render(document, "json"))
    yaml_value = YAML(typ="safe").load(render(document, "yaml"))
    xml_value = render(document, "xml")

    for value in (json_value, yaml_value):
        assert value["run"]["workers"] == {
            "requested_mode": "explicit",
            "requested": 4,
            "effective": 2,
        }
        assert value["run"]["plan_id"] == plan.id
    assert '<field name="workers" type="object">' in xml_value
    assert '<field name="effective" type="number">2</field>' in xml_value


def test_scheduler_uses_stable_action_identity_not_plugin_object_identity(
    tmp_path: Path,
) -> None:
    plan = _plan((_action("stable"),))

    class IdentityA:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            return ActionAttempt(True, f"{action.driver}:{action.id}")

    class IdentityB:
        def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
            return ActionAttempt(True, f"{action.driver}:{action.id}")

    first = Executor(IdentityA(), jobs=2).execute(plan, _context(tmp_path))
    second = Executor(IdentityB(), jobs=2).execute(plan, _context(tmp_path))

    assert first.actions[0].attempt == second.actions[0].attempt
    assert [(event.action_id, event.state) for event in first.events] == [
        (event.action_id, event.state) for event in second.events
    ]
