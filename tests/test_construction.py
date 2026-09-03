from __future__ import annotations

import json
from pathlib import Path

import pytest

from poly.construction import (
    WORKSPACE_MANIFEST,
    ConstructionError,
    ConstructionPlanner,
    ConstructionPlanningProvider,
    _positive_depth,
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
from poly.model import ActionSpec, Inventory, Node, Plan, PlanningRequest
from poly.runtime import Executor, LocalActionRunner, RunResult, RunStatus
from poly.workspace import validate_manifest_value


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
    assert read_workspace_definition(tmp_path)["workspace"] == {
        "id": "example",
        "name": "Example",
        "root-node": "root",
    }

    add = planner.plan_add(tmp_path, "service-api", "services/api", ("maven/module",))
    assert not (tmp_path / "services" / "api").exists()
    added = _execute(tmp_path, add)
    definition = read_workspace_definition(tmp_path)

    assert added.status is RunStatus.SUCCEEDED
    assert definition["nodes"] == [
        {"id": "root", "kind": "workspace", "path": "."},
        {
            "id": "service-api",
            "kind": "module",
            "natures": ["maven/module"],
            "parent": "root",
            "path": "services/api",
        },
    ]


def test_constructor_rejects_unsafe_or_duplicate_nodes(tmp_path: Path) -> None:
    planner = ConstructionPlanner()
    _execute(tmp_path, planner.plan_init(tmp_path, "Example"))
    _execute(tmp_path, planner.plan_add(tmp_path, "service", "service"))

    with pytest.raises(ConstructionError, match="duplicate node identifier"):
        planner.plan_add(tmp_path, "service", "another")
    with pytest.raises(ConstructionError, match="path collision"):
        planner.plan_add(tmp_path, "other", "service")
    with pytest.raises(ConstructionError, match="safe relative path"):
        planner.plan_add(tmp_path, "unsafe", "../outside")
    reconcile = planner.plan_init(tmp_path, "Again")
    assert reconcile.actions[0].operation == "poly/construction/reconcile"
    assert _execute(tmp_path, reconcile).status is RunStatus.SUCCEEDED


def test_workspace_manifest_validation_and_handler_failures(tmp_path: Path) -> None:
    with pytest.raises(ConstructionError, match="not initialized"):
        read_workspace_definition(tmp_path)

    manifest = tmp_path / WORKSPACE_MANIFEST
    manifest.write_text(json.dumps({"schema": "wrong"}))
    with pytest.raises(ConstructionError, match="unsupported workspace schema"):
        read_workspace_definition(tmp_path)

    manifest.write_text(
        json.dumps(
            {
                "schema": "poly.workspace/v1",
                "workspace": {"id": "example", "root-node": "root"},
                "nodes": [{"id": "root", "kind": "workspace", "path": "."}],
            }
        )
    )
    lock = tmp_path / "poly.lock.yaml"
    digest = validate_manifest_value(tmp_path, json.loads(manifest.read_text())).digest
    lock.write_text(
        json.dumps(
            {
                "schema": "poly.workspace-lock/v1",
                "manifest-digest": digest,
                "sources": {},
            }
        )
    )
    plan = ConstructionPlanner().plan_add(tmp_path, "service", "service")
    manifest.write_text("invalid: [yaml")
    result = _execute(tmp_path, plan)

    assert result.status is RunStatus.FAILED
    assert result.actions[0].attempt is not None
    assert "cannot read workspace file" in result.actions[0].attempt.summary


def test_constructor_driver_uses_public_execution_contract() -> None:
    registration = constructor_driver()
    registration.validate()
    assert registration.planners[0].name == registration.manifest.name
    assert registration.handlers[0].name == registration.manifest.name


@pytest.mark.parametrize("value", ["0", "-1", "many"])
def test_positive_depth_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ConstructionError, match="positive integer"):
        _positive_depth(value)


def test_positive_depth_accepts_positive_integer() -> None:
    assert _positive_depth("3") == 3


def test_constructor_add_carries_repository_depth() -> None:
    proposal = ConstructionPlanningProvider().propose(
        PlanningRequest(
            "add",
            Inventory((Node("root", ".", ("poly/workspace",)),)),
            (),
            {
                "poly.node.id": "service",
                "poly.node.path": "services/service",
                "poly.node.kind": "repository",
                "poly.source.url": "https://example.invalid/repo.git",
                "poly.source.depth": "3",
            },
        )
    )
    assert proposal.actions[0].environment["poly.node.spec"] == (
        '{"id": "service", "kind": "repository", "parent": "root", '
        '"path": "services/service", "source": {"depth": 3, '
        '"driver": "git", "url": "https://example.invalid/repo.git"}}'
    )


def test_constructor_rejects_git_source_on_module() -> None:
    proposal = ConstructionPlanningProvider().propose(
        PlanningRequest(
            "add",
            Inventory((Node("root", ".", ("poly/workspace",)),)),
            (),
            {
                "poly.node.id": "service",
                "poly.node.path": "services/service",
                "poly.node.kind": "module",
                "poly.source.url": "https://example.invalid/repo.git",
            },
        )
    )
    assert proposal.rejected


def test_action_spec_rejects_empty_command() -> None:
    with pytest.raises(ValueError, match="executable"):
        ActionSpec("bad", "driver", "run", "operation", (), command=())


def test_constructor_plans_initialization_from_an_empty_context_without_side_effects(
    tmp_path: Path,
) -> None:
    request = PlanningRequest("init", Inventory(), (), {"poly.name": "Empty Context"})
    proposal = ConstructionPlanningProvider().propose(request)

    assert proposal.actions[0].operation == "poly/construction/init"
    assert proposal.actions[0].environment["poly.workspace.id"] == "empty-context"
    assert not (tmp_path / WORKSPACE_MANIFEST).exists()
