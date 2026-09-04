from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

from poly.application import InspectionSnapshot, PlanningSnapshot
from poly.control_plane import ControllerDescriptor
from poly.driver import ActionValue, DriverInventoryItem, OutputReference
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
    controllers_document,
    document_with_outputs,
    drivers_document,
    inspection_document,
    planning_document,
    render,
    render_cli,
    render_cli_completion,
    render_cli_event,
    render_cli_start,
    run_document,
)
from poly.runtime import ActionAttempt, ActionResult, ActionState, RunEvent, RunResult, RunStatus


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
        3723000,
    )

    document = run_document(planning, result)
    value = json.loads(render(document, "json"))
    action = value["run"]["actions"][0]

    assert action["state"] == "succeeded"
    assert action["attempt"]["stdout"] == "output"
    assert "stdout: output" in render(document, "text")


def test_interactive_renderer_has_command_statuses_and_distinct_completion(
    tmp_path: Path,
) -> None:
    _, planning = _snapshots(tmp_path)
    result = RunResult(
        "plan",
        RunStatus.SUCCEEDED,
        (
            ActionResult(
                "verify:node",
                ActionState.SUCCEEDED,
                ActionAttempt(True, "verified", 0, "details", ""),
            ),
        ),
        (),
        (),
        3723000,
    )
    document = run_document(planning, result)

    concise = render_cli(
        document,
        "poly verify --select node",
        color=False,
        exit_code=0,
    )
    verbose = render_cli(
        document,
        "poly verify --select node -vv",
        verbosity=2,
        color=True,
        exit_code=0,
    )
    quiet = render_cli(
        document,
        "poly verify --select node -q",
        verbosity=-1,
        color=False,
        exit_code=0,
    )

    assert concise.splitlines()[0] == "VERIFYING node ..."
    assert concise.splitlines()[1].startswith("        PLAN")
    assert "                ✓ OK       verify:node" in concise
    assert concise.splitlines()[-2].startswith("        ✓ SUCCESS  poly verify")
    assert "01h 02m 03s" in concise
    assert "Schema: poly.report/v1" in verbose
    assert "        COMMAND  poly verify --select node -vv" in verbose
    assert "\x1b[32m" in verbose
    assert "COMMAND" not in quiet
    assert quiet.splitlines()[-2].startswith("        ✓ SUCCESS")


def test_interactive_renderer_distinguishes_failure_blocking_and_logs(tmp_path: Path) -> None:
    _, planning = _snapshots(tmp_path)
    result = RunResult(
        "plan",
        RunStatus.FAILED,
        (
            ActionResult(
                "verify:node",
                ActionState.FAILED,
                ActionAttempt(False, "verification failed", 2, "", "broken"),
            ),
            ActionResult("follow-up", ActionState.BLOCKED, None, ("verify:node",)),
        ),
        (),
        (),
    )

    output = render_cli(
        run_document(planning, result),
        "poly verify --select node -v",
        verbosity=1,
        color=False,
        exit_code=1,
    )

    assert "✗ KO       verify:node (fixture/verify)" in output
    assert "· verification failed" in output
    assert "stderr: broken" in output
    assert "⚠ WARN     follow-up · blocked by" in output
    assert output.splitlines()[-2].startswith("        ✗ FAILURE  poly verify")


def test_interactive_renderer_reports_none_for_an_empty_plan(tmp_path: Path) -> None:
    _, planning = _snapshots(tmp_path)
    empty_plan = Plan("empty-plan", "verify", ("node",), (), (), (), PlanStatus.EMPTY)
    empty_planning = PlanningSnapshot(
        planning.inspection,
        planning.request,
        (),
        (),
        empty_plan,
    )
    result = RunResult("empty-plan", RunStatus.EMPTY, (), (), ())

    output = render_cli(
        run_document(empty_planning, result),
        "poly verify --select node",
        color=True,
        exit_code=0,
    )

    assert "\x1b[90m· NONE     poly verify\x1b[0m" in output
    assert "SUCCESS" not in output
    assert "FAILURE" not in output


def test_streaming_renderer_separates_start_events_logs_and_completion(tmp_path: Path) -> None:
    _, planning = _snapshots(tmp_path)
    result = RunResult(
        "plan",
        RunStatus.SUCCEEDED,
        (
            ActionResult(
                "verify:node",
                ActionState.SUCCEEDED,
                ActionAttempt(True, "verified", 0, "details", ""),
            ),
        ),
        (),
        (),
    )
    document = run_document(planning, result)

    start = render_cli_start(
        planning_document(planning), "poly verify -v", verbosity=1, color=False
    )
    running = render_cli_event(
        RunEvent(3, ActionState.RUNNING, "verify:node"),
        planning.plan.actions[0],
        verbosity=1,
        color=False,
    )
    succeeded = render_cli_event(
        RunEvent(4, ActionState.SUCCEEDED, "verify:node", "verified"),
        planning.plan.actions[0],
        verbosity=1,
        color=False,
    )
    completion = render_cli_completion(document, verbosity=1, color=False, exit_code=0)

    assert start.startswith("VERIFYING node ...\n")
    assert "COMMAND  poly verify -v" in start
    assert "PLAN     plan · 1 action(s) · executable" in start
    assert "> RUNNING  verify:node (fixture/verify)" in running
    assert "✓ OK       verify:node (fixture/verify) · verified" in succeeded
    assert "stdout: details" in completion
    assert "✓ SUCCESS  poly verify" in completion


def test_inspection_completion_uses_cli_verb_instead_of_none(tmp_path: Path) -> None:
    inspection, _ = _snapshots(tmp_path)

    output = render_cli(inspection_document(inspection), "poly inspect", color=False, exit_code=0)

    assert "✓ SUCCESS  poly inspect" in output
    assert "poly None" not in output


def test_command_outputs_are_rendered_and_preserved(tmp_path: Path) -> None:
    inspection, _ = _snapshots(tmp_path)
    target = tmp_path / "inspection.json"
    document = document_with_outputs(
        inspection_document(inspection),
        (OutputReference("file", str(target), "Inspection report", "application/json"),),
    )

    output = render_cli(document, "poly inspect --output inspection.json", color=False)

    assert "> OUTPUT" in output
    assert f"Inspection report: {target}" in output
    assert document["outputs"] == [
        {
            "kind": "file",
            "target": str(target),
            "label": "Inspection report",
            "media_type": "application/json",
        }
    ]


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


def test_source_add_heading_uses_sanitized_authored_url_and_ref(tmp_path: Path) -> None:
    _, planning = _snapshots(tmp_path)
    request = PlanningRequest(
        "add",
        planning.inspection.inventory,
        ("node",),
        {
            "poly.node.id": "service",
            "poly.source.url": "https://user:secret@example.test/repo.git",
            "poly.source.ref": "develop",
        },
    )
    add_planning = PlanningSnapshot(
        planning.inspection, request, planning.applicable_actions, (), planning.plan
    )

    output = render_cli(planning_document(add_planning), "poly add service", color=False)

    assert "ADDING service from https://example.test/repo.git (ref: develop) ..." in output
    assert "secret" not in output


def test_scalar_values_and_outputs_render_without_losing_structured_data(
    tmp_path: Path,
) -> None:
    _, planning = _snapshots(tmp_path)
    outputs = (
        OutputReference("file", r"D:\test\quality report.html", media_type="text/html"),
        OutputReference("file", r"D:\test\quality report.html", media_type="text/html"),
        OutputReference("url", "https://example.test/report/1", "Quality report"),
    )
    result = RunResult(
        "plan",
        RunStatus.FAILED,
        (
            ActionResult(
                "verify:node",
                ActionState.FAILED,
                ActionAttempt(
                    False,
                    "diagnostic retained",
                    details={"reason": "threshold"},
                    value=ActionValue(82.4, "coverage"),
                    outputs=outputs,
                ),
                started_at="2026-09-02T12:00:00.000Z",
                completed_at="2026-09-02T12:00:00.125Z",
                duration_ms=125,
            ),
        ),
        (RunEvent(1, ActionState.FAILED, "verify:node", occurred_at="2026-09-02T12:00:00.125Z"),),
        (),
    )
    document = run_document(planning, result)

    plain = render_cli(document, "poly verify", exit_code=1)
    linked = render_cli(document, "poly verify", exit_code=1, hyperlinks=True)
    structured = json.loads(render(document, "json"))

    assert "· coverage: 82.4" in plain
    assert plain.index("FAILURE") < plain.index("> OUTPUT")
    assert plain.count(r"D:\test\quality report.html") == 1
    assert "\x1b]8;;file:///D:/test/quality%20report.html" in linked
    assert "\x1b]8;;https://example.test/report/1" in linked
    assert "\x1b]8" not in plain
    assert structured["run"]["actions"][0]["duration_ms"] == 125
    assert structured["run"]["actions"][0]["attempt"]["outputs"][2]["kind"] == "url"
    assert structured["run"]["events"][0]["occurred_at"].endswith("Z")


def test_narrow_action_detail_wraps_at_the_third_indent(tmp_path: Path) -> None:
    _, planning = _snapshots(tmp_path)
    event = RunEvent(
        1,
        ActionState.SUCCEEDED,
        "verify:node",
        "a deliberately long detail that must wrap safely",
    )

    output = render_cli_event(event, planning.plan.actions[0], width=48)

    assert output.splitlines()[0].startswith("                ✓ OK")
    assert any(line.startswith("                        · ") for line in output.splitlines()[1:])
    assert all(len(line) <= 48 for line in output.splitlines())


def test_terminal_renderer_neutralizes_controls_in_summaries(tmp_path: Path) -> None:
    _, planning = _snapshots(tmp_path)
    event = RunEvent(1, ActionState.FAILED, "verify:node", "bad\x1b[31m\nsummary")

    output = render_cli_event(event, planning.plan.actions[0])

    assert "\x1b[31m" not in output
    assert "bad?[31m?summary" in output


def test_driver_inventory_has_stable_semantic_parity_in_every_format(tmp_path: Path) -> None:
    inventory = (
        DriverInventoryItem(
            "driver.example",
            "1.2.3",
            "installed:poly-driver-example",
            "1.0",
            ("inspect", "plan"),
            ("example-run",),
            "loaded",
            "example=example:driver",
        ),
        DriverInventoryItem(
            "broken",
            None,
            "installed:broken",
            None,
            (),
            (),
            "rejected",
            "broken=missing:driver",
            "ModuleNotFoundError: missing",
        ),
    )
    document = drivers_document(tmp_path, inventory)

    assert json.loads(render(document, "json")) == document
    assert _decode_yaml(render(document, "yaml")) == document
    assert _decode_xml(ET.fromstring(render(document, "xml"))) == document
    text = render(document, "text")
    assert "driver.example 1.2.3 [loaded]" in text
    assert "broken - [rejected]" in text
    assert "diagnostic: ModuleNotFoundError: missing" in text
    concise = render_cli(document, "poly drivers", color=False)
    assert "1 loaded driver(s) · 1 rejected" in concise
    assert "driver.example 1.2.3 · installed:poly-driver-example · API 1.0" in concise
    assert "capabilities=inspect,plan · verbs=example-run" in concise
    assert "diagnostic: ModuleNotFoundError: missing" in concise


def test_renderer_rejects_unknown_format(tmp_path: Path) -> None:
    inspection, _ = _snapshots(tmp_path)

    try:
        render(inspection_document(inspection), "toml")
    except ValueError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("unknown format was accepted")


def test_controller_report_exposes_capabilities(tmp_path: Path) -> None:
    document = controllers_document(
        tmp_path,
        (
            ControllerDescriptor(
                "local", "linux", frozenset(("process.execute", "workspace.construct"))
            ),
        ),
    )

    value = json.loads(render(document, "json"))

    assert value["controllers"][0]["capabilities"] == [
        "process.execute",
        "workspace.construct",
    ]
    assert "Controllers: 1" in render(document, "text")


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


def _decode_yaml(value: str) -> object:
    return YAML(typ="safe").load(StringIO(value))
