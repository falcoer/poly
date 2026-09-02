from __future__ import annotations

import json
from pathlib import Path

import pytest

from poly.persistence import LEGACY_STATE_SCHEMA, STATE_SCHEMA, StateError, StateStore
from poly.reporting import ReportDocument


def _document(kind: str = "inspection") -> ReportDocument:
    return {
        "schema": "poly.report/v1",
        "kind": kind,
        "available_verbs": ["status"],
        "inventory": {"nodes": []},
        "diagnostics": [],
    }


def test_store_persists_and_recovers_inventory_plan_and_run(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    inventory = _document()
    plan = _document("plan")
    run = _document("run")

    inventory_path = store.save_inventory(inventory)
    plan_path = store.save_plan("run-1", plan)

    assert store.load_inventory() == inventory
    assert store.load_report("run-1") == plan
    report_path = store.save_run("run-1", run)
    assert store.load_report("run-1") == run
    assert inventory_path == tmp_path / ".poly" / "state" / "inventory.json"
    assert plan_path.name == "plan.json"
    assert report_path.name == "report.json"
    envelope = json.loads(report_path.read_text())
    assert envelope["state_schema"] == STATE_SCHEMA


def test_store_owns_one_disposable_prepared_plan(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    plan = _document("prepared-plan")

    path = store.save_prepared_plan(plan)
    assert path == tmp_path / ".poly" / "state" / "plan.json"
    assert store.load_prepared_plan() == plan
    assert store.clear_prepared_plan()
    assert not store.clear_prepared_plan()
    with pytest.raises(StateError, match="does not exist"):
        store.load_prepared_plan()


def test_store_migrates_legacy_envelopes_and_raw_reports(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    legacy = store.runs_directory / "legacy" / "report.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps(
            {
                "state_schema": LEGACY_STATE_SCHEMA,
                "kind": "run",
                "payload": _document("run"),
            }
        )
    )

    assert store.load_report("legacy") == _document("run")
    assert json.loads(legacy.read_text())["state_schema"] == STATE_SCHEMA

    raw = store.runs_directory / "raw" / "plan.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps(_document("plan")))
    assert store.load_report("raw") == _document("plan")
    assert json.loads(raw.read_text())["state_schema"] == STATE_SCHEMA


def test_store_rejects_invalid_paths_and_schemas(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    with pytest.raises(StateError, match="invalid run id"):
        store.load_report("../outside")
    with pytest.raises(StateError, match="does not exist"):
        store.load_report("missing")

    invalid = store.state_directory / "inventory.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text(json.dumps({"state_schema": "poly.state/v99"}))
    with pytest.raises(StateError, match="unsupported state schema"):
        store.load_inventory()

    invalid.write_text("not json")
    with pytest.raises(StateError, match="cannot read state"):
        store.load_inventory()
