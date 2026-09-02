from __future__ import annotations

from pathlib import Path

import pytest

from poly.model import ActionClaim, ActionSpec, Plan, PlanStatus
from poly.prepared import (
    PreparedPlanError,
    compose_plans,
    plan_from_document,
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
