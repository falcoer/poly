from __future__ import annotations

import json
from pathlib import Path

import pytest

from poly.construction import (
    WORKSPACE_MANIFEST,
    ConstructionError,
    ConstructionPlanner,
    constructor_driver,
    read_workspace_definition,
)
from poly.control_plane import (
    ControllerDescriptor,
    ControlPlane,
    ControlPlaneActionRunner,
    LocalController,
)
from poly.driver import DriverRegistry, ExecutionContext
from poly.model import Plan
from poly.runtime import Executor, LocalActionRunner, RunResult, RunStatus


def _execute(workspace: Path, plan: Plan) -> RunResult:
    registry = DriverRegistry()
    registry.register(constructor_driver())
    local = LocalController(
        ControllerDescriptor("local", "test", frozenset(("workspace.construct",))),
        LocalActionRunner(registry),
    )
    runner = ControlPlaneActionRunner(ControlPlane((local,)))
    return Executor(runner).execute(
        plan, ExecutionContext(workspace, workspace / ".poly" / "runs" / plan.id)
    )


def test_init_and_add_are_frozen_plans_executed_by_common_runtime(tmp_path: Path) -> None:
    planner = ConstructionPlanner()
    init = planner.plan_init(tmp_path, "Example")

    assert not (tmp_path / WORKSPACE_MANIFEST).exists()
    assert init.actions[0].changes_structure
    assert init.actions[0].required_capability == "workspace.construct"
    initialized = _execute(tmp_path, init)

    assert initialized.status is RunStatus.SUCCEEDED
    assert read_workspace_definition(tmp_path)["name"] == "Example"

    add = planner.plan_add(tmp_path, "service-api", "services/api", ("maven/module",))
    assert not (tmp_path / "services" / "api").exists()
    added = _execute(tmp_path, add)
    definition = read_workspace_definition(tmp_path)

    assert added.status is RunStatus.SUCCEEDED
    assert (tmp_path / "services" / "api").is_dir()
    assert definition["nodes"] == [
        {"id": "service-api", "natures": ["maven/module"], "path": "services/api"}
    ]


def test_constructor_rejects_unsafe_or_duplicate_nodes(tmp_path: Path) -> None:
    planner = ConstructionPlanner()
    _execute(tmp_path, planner.plan_init(tmp_path, "Example"))
    _execute(tmp_path, planner.plan_add(tmp_path, "service", "service"))

    with pytest.raises(ConstructionError, match="already exists"):
        planner.plan_add(tmp_path, "service", "another")
    with pytest.raises(ConstructionError, match="path already exists"):
        planner.plan_add(tmp_path, "other", "service")
    with pytest.raises(ConstructionError, match="workspace-relative"):
        planner.plan_add(tmp_path, "unsafe", "../outside")
    with pytest.raises(ConstructionError, match="already initialized"):
        planner.plan_init(tmp_path, "Again")


def test_workspace_manifest_validation_and_handler_failures(tmp_path: Path) -> None:
    with pytest.raises(ConstructionError, match="not initialized"):
        read_workspace_definition(tmp_path)

    manifest = tmp_path / WORKSPACE_MANIFEST
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"schema": "wrong"}))
    with pytest.raises(ConstructionError, match="unsupported schema"):
        read_workspace_definition(tmp_path)

    manifest.write_text(json.dumps({"schema": "poly.workspace/v1", "name": "Example", "nodes": []}))
    plan = ConstructionPlanner().plan_add(tmp_path, "service", "service")
    manifest.write_text("invalid json")
    result = _execute(tmp_path, plan)

    assert result.status is RunStatus.FAILED
    assert result.actions[0].attempt is not None
    assert "cannot read workspace manifest" in result.actions[0].attempt.summary


def test_constructor_driver_uses_public_execution_contract() -> None:
    registration = constructor_driver()
    registration.validate()
    assert registration.handlers[0].name == registration.manifest.name
