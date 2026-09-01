from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from poly.application import InspectionSnapshot, PlanningSnapshot
from poly.control_plane import ControllerDescriptor
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

    assert "✗ KO       verify:node (fixture/verify) · verification failed" in output
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
