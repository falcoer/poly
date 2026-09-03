from __future__ import annotations

from pathlib import Path

import pytest

from poly.application import InspectionSnapshot, PlanningSnapshot
from poly.model import (
    ActionClaim,
    ActionSpec,
    Constraint,
    Inventory,
    Plan,
    PlanDiagnostic,
    PlanningRequest,
    PlanStatus,
)
from poly.prepared import (
    PreparedPlanError,
    compose_plans,
    plan_from_document,
    prepare_document,
    workspace_fingerprint,
)


def _plan(identifier: str, action: ActionSpec) -> Plan:
    return Plan(identifier, action.verb, (), (action,), (), (), PlanStatus.EXECUTABLE)


def test_composition_detects_duplicate_actions_and_claims() -> None:
    first = ActionSpec(
        "same",
        "driver.one",
        "add",
        "create",
        (),
        claims=frozenset((ActionClaim("create", "node:api"),)),
    )
    second = ActionSpec(
        "same",
        "driver.two",
        "remove",
        "create",
        (),
        claims=frozenset((ActionClaim("create", "node:api"),)),
    )

    composed = compose_plans((_plan("one", first), _plan("two", second)))

    assert composed.status is PlanStatus.CONFLICT
    assert {item.code for item in composed.diagnostics} == {
        "action.duplicate-id",
        "claim.conflict",
    }


def test_composition_preserves_provider_diagnostics_and_completion_markers() -> None:
    first = ActionSpec("z-parent", "driver.one", "add", "create", ())
    second = ActionSpec("a-child", "driver.two", "add", "create", ())
    rejected = Plan(
        "one",
        "add",
        (),
        (first,),
        (),
        (
            PlanDiagnostic("action.wrong-verb", "invalid provider action", first.id),
            PlanDiagnostic("action.unknown-node", "unknown node", first.id),
            PlanDiagnostic("action.outside-selection", "outside selection", first.id),
        ),
        PlanStatus.CONFLICT,
    )

    composed = compose_plans((rejected, _plan("two", second)))

    assert composed.status is PlanStatus.CONFLICT
    assert {diagnostic.code for diagnostic in composed.diagnostics} == {
        "action.outside-selection",
        "action.unknown-node",
        "action.wrong-verb",
    }
    parent = next(action for action in composed.actions if action.id == first.id)
    child = next(action for action in composed.actions if action.id == second.id)
    completion = Constraint(f"poly/prepared-complete:{first.id}")
    assert completion in parent.produces
    assert completion not in child.requires


def test_composition_orders_overlapping_actions_but_keeps_independent_work_ready() -> None:
    first = ActionSpec("first", "driver.one", "update", "update", ("shared",))
    second = ActionSpec("second", "driver.two", "verify", "verify", ("shared",))
    independent = ActionSpec("independent", "driver.two", "verify", "verify", ("other",))

    composed = compose_plans(
        (
            _plan("one", first),
            Plan("two", "verify", (), (second, independent), (), (), PlanStatus.EXECUTABLE),
        )
    )

    actions = {action.id: action for action in composed.actions}
    completion = Constraint("poly/prepared-complete:first")
    assert completion in actions["second"].requires
    assert completion not in actions["independent"].requires


def test_composition_recomputes_graph_diagnostics() -> None:
    required = Constraint("artifact:ready")
    consumer = ActionSpec(
        "consumer",
        "driver.one",
        "publish",
        "publish",
        (),
        requires=frozenset((required,)),
    )
    producer = ActionSpec(
        "producer",
        "driver.two",
        "build",
        "build",
        (),
        produces=frozenset((required,)),
    )
    blocked = Plan(
        "one",
        "publish",
        (),
        (consumer,),
        (),
        (PlanDiagnostic("constraint.missing", "missing artifact", consumer.id),),
        PlanStatus.BLOCKED,
    )

    composed = compose_plans((_plan("two", producer), blocked))

    assert composed.status is PlanStatus.EXECUTABLE
    assert composed.diagnostics == ()


def test_plan_decoder_rejects_non_plan_documents() -> None:
    with pytest.raises(PreparedPlanError, match="has no plan"):
        plan_from_document({"schema": "poly.report/v1", "kind": "inspection"})

    with pytest.raises(PreparedPlanError, match="invalid prepared plan"):
        plan_from_document(
            {
                "schema": "poly.report/v1",
                "kind": "prepared-plan",
                "plan": {"planned_actions": "invalid", "diagnostics": []},
            }
        )


def test_workspace_fingerprint_tracks_only_authored_composition(tmp_path: Path) -> None:
    initial = workspace_fingerprint(tmp_path)
    generated = tmp_path / ".poly" / "state"
    generated.mkdir(parents=True)
    (generated / "inventory.json").write_text("generated", encoding="utf-8")
    assert workspace_fingerprint(tmp_path) == initial

    (tmp_path / "poly.yaml").write_text("schema: poly.workspace/v1\n", encoding="utf-8")
    assert workspace_fingerprint(tmp_path) != initial


def test_legacy_prepare_document_accumulates_and_detects_staleness(tmp_path: Path) -> None:
    inventory = Inventory()
    inspection = InspectionSnapshot(tmp_path.resolve(), inventory, (), ())
    request = PlanningRequest("add", inventory, (), {}, workspace=tmp_path.resolve())
    source_plan = Plan("source", "add", (), (), (), (), PlanStatus.EMPTY)
    snapshot = PlanningSnapshot(inspection, request, (), (), source_plan)

    first = prepare_document(snapshot, "poly add --prepare")
    assert first["kind"] == "prepared-plan"
    prepared = first.get("prepared")
    requests = first.get("requests")
    assert isinstance(prepared, dict)
    assert isinstance(requests, list)
    assert prepared["commands"] == ["poly add --prepare"]
    assert len(requests) == 1

    second = prepare_document(snapshot, "poly add --prepare", first)
    prepared = second.get("prepared")
    requests = second.get("requests")
    assert isinstance(prepared, dict)
    assert isinstance(requests, list)
    assert prepared["commands"] == ["poly add --prepare", "poly add --prepare"]
    assert len(requests) == 2

    (tmp_path / "poly.yaml").write_text("schema: poly.workspace/v1\n", encoding="utf-8")
    with pytest.raises(PreparedPlanError, match="prepared plan is stale"):
        prepare_document(snapshot, "poly add --prepare", second)
