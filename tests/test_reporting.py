from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from poly.application import InspectionSnapshot, PlanningSnapshot
from poly.model import (
    ActionSpec,
    Inventory,
    Node,
    Plan,
    PlanningRequest,
    PlanStatus,
)
from poly.reporting import (
    action_catalog_document,
    inspection_document,
    planning_document,
    render,
    run_document,
)
from poly.runtime import ActionAttempt, ActionResult, ActionState, RunResult, RunStatus


def _snapshots(tmp_path: Path) -> tuple[InspectionSnapshot, PlanningSnapshot]:
    inventory = Inventory((Node("node", ".", ("fixture/project",), {"count": 1}),))
    inspection = InspectionSnapshot(tmp_path, inventory, (), ("verify",))
    action = ActionSpec(
        "verify:node",
        "fixture",
        "verify",
        "fixture/verify",
        ("node",),
        ("node",),
        command=("verify",),
    )
    request = PlanningRequest("verify", inventory, ("node",))
    plan = Plan("plan", "verify", ("node",), (action,), (), (), PlanStatus.EXECUTABLE)
    return inspection, PlanningSnapshot(inspection, request, (action,), (), plan)


def test_documents_distinguish_available_applicable_planned_and_ready(tmp_path: Path) -> None:
    inspection, planning = _snapshots(tmp_path)

    inspected = inspection_document(inspection)
    planned = planning_document(planning)
    catalog = action_catalog_document((planning,))
    planned_value = json.loads(render(planned, "json"))
    catalog_value = json.loads(render(catalog, "json"))

    assert inspected["available_verbs"] == ["verify"]
    assert planned_value["applicable_actions"][0]["id"] == "verify:node"
    assert planned_value["plan"]["planned_actions"][0]["id"] == "verify:node"
    assert planned_value["plan"]["ready_action_ids"] == ["verify:node"]
    assert catalog_value["verbs"][0]["plan_status"] == "executable"


def test_run_document_keeps_attempt_logs_and_state(tmp_path: Path) -> None:
    _, planning = _snapshots(tmp_path)
    result = RunResult(
        "plan",
        RunStatus.SUCCEEDED,
        (
            ActionResult(
                "verify:node",
                ActionState.SUCCEEDED,
                ActionAttempt(True, "ok", 0, "output", ""),
            ),
        ),
        (),
        (),
    )

    document = run_document(planning, result)
    value = json.loads(render(document, "json"))
    action = value["run"]["actions"][0]

    assert action["state"] == "succeeded"
    assert action["attempt"]["stdout"] == "output"
    assert "stdout: output" in render(document, "text")


def test_json_yaml_and_xml_render_the_same_canonical_document(tmp_path: Path) -> None:
    _, planning = _snapshots(tmp_path)
    document = planning_document(planning)

    json_value = json.loads(render(document, "json"))
    yaml_value = render(document, "yaml")
    xml_value = _decode_xml(ET.fromstring(render(document, "xml")))

    assert json_value == document
    assert '"kind": "plan"' in yaml_value
    assert '"ready_action_ids":' in yaml_value
    assert xml_value == document


def test_renderer_rejects_unknown_format(tmp_path: Path) -> None:
    inspection, _ = _snapshots(tmp_path)

    try:
        render(inspection_document(inspection), "toml")
    except ValueError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("unknown format was accepted")


def _decode_xml(element: ET.Element) -> object:
    kind = element.attrib["type"]
    if kind == "object":
        return {child.attrib["name"]: _decode_xml(child) for child in element}
    if kind == "array":
        return [_decode_xml(child) for child in element]
    if kind == "null":
        return None
    if kind == "boolean":
        return element.text == "true"
    if kind == "number":
        text = element.text or "0"
        return float(text) if "." in text else int(text)
    return element.text or ""
