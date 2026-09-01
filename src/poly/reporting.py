"""Canonical report documents and format renderers."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from poly.application import InspectionSnapshot, PlanningSnapshot
from poly.control_plane import ControllerDescriptor
from poly.driver import DriverManifest, InspectionDiagnostic
from poly.model import (
    ActionSpec,
    JsonValue,
    Node,
    Plan,
    RejectedCandidate,
)
from poly.runtime import ActionResult, RunEvent, RunResult

type ReportDocument = dict[str, JsonValue]
REPORT_SCHEMA = "poly.report/v1"


def inspection_document(snapshot: InspectionSnapshot) -> ReportDocument:
    return {
        "schema": REPORT_SCHEMA,
        "kind": "inspection",
        "workspace": str(snapshot.workspace),
        "available_verbs": list(snapshot.available_verbs),
        "inventory": {"nodes": [_node_document(node) for node in snapshot.inventory.nodes]},
        "diagnostics": [
            _inspection_diagnostic_document(diagnostic) for diagnostic in snapshot.diagnostics
        ],
    }


def planning_document(snapshot: PlanningSnapshot, *, kind: str = "plan") -> ReportDocument:
    document = inspection_document(snapshot.inspection)
    document["kind"] = kind
    document["request"] = {
        "verb": snapshot.request.verb,
        "selected_node_ids": list(snapshot.request.selected_node_ids),
        "parameters": dict(snapshot.request.parameters),
    }
    document["applicable_actions"] = [
        _action_document(action) for action in snapshot.applicable_actions
    ]
    document["rejected_candidates"] = [
        _rejected_document(candidate) for candidate in snapshot.rejected
    ]
    document["plan"] = _plan_document(snapshot.plan)
    return document


def action_catalog_document(snapshots: Sequence[PlanningSnapshot]) -> ReportDocument:
    if not snapshots:
        raise ValueError("an action catalog requires at least one planning snapshot")
    inspection = snapshots[0].inspection
    document = inspection_document(inspection)
    document["kind"] = "actions"
    document["verbs"] = [
        {
            "verb": snapshot.request.verb,
            "selected_node_ids": list(snapshot.request.selected_node_ids),
            "applicable_actions": [
                _action_document(action) for action in snapshot.applicable_actions
            ],
            "rejected_candidates": [
                _rejected_document(candidate) for candidate in snapshot.rejected
            ],
            "plan_status": snapshot.plan.status.value,
            "ready_action_ids": list(snapshot.plan.ready_action_ids),
        }
        for snapshot in snapshots
    ]
    return document


def run_document(snapshot: PlanningSnapshot, result: RunResult) -> ReportDocument:
    document = planning_document(snapshot, kind="run")
    document["run"] = {
        "plan_id": result.plan_id,
        "status": result.status.value,
        "available_constraints": list(result.available_constraints),
        "actions": [_action_result_document(action) for action in result.actions],
        "events": [_event_document(event) for event in result.events],
    }
    return document


def construction_document(workspace: Path, plan: Plan, result: RunResult) -> ReportDocument:
    return {
        "schema": REPORT_SCHEMA,
        "kind": "construction",
        "workspace": str(workspace.resolve()),
        "available_verbs": ["add", "init"],
        "inventory": {"nodes": []},
        "diagnostics": [],
        "applicable_actions": [_action_document(action) for action in plan.actions],
        "rejected_candidates": [],
        "plan": _plan_document(plan),
        "run": {
            "plan_id": result.plan_id,
            "status": result.status.value,
            "available_constraints": list(result.available_constraints),
            "actions": [_action_result_document(action) for action in result.actions],
            "events": [_event_document(event) for event in result.events],
        },
    }


def controllers_document(
    workspace: Path, descriptors: tuple[ControllerDescriptor, ...]
) -> ReportDocument:
    return {
        "schema": REPORT_SCHEMA,
        "kind": "controllers",
        "workspace": str(workspace.resolve()),
        "available_verbs": [],
        "inventory": {"nodes": []},
        "diagnostics": [],
        "controllers": [descriptor.to_dict() for descriptor in descriptors],
    }


def drivers_document(workspace: Path, manifests: tuple[DriverManifest, ...]) -> ReportDocument:
    return {
        "schema": REPORT_SCHEMA,
        "kind": "drivers",
        "workspace": str(workspace.resolve()),
        "available_verbs": [],
        "inventory": {"nodes": []},
        "diagnostics": [],
        "drivers": [
            {
                "name": manifest.name,
                "version": manifest.version,
                "api_version": manifest.api_version,
                "capabilities": _string_values(
                    sorted(item.value for item in manifest.capabilities)
                ),
                "description": manifest.description,
            }
            for manifest in manifests
        ],
    }


def render(document: ReportDocument, format_name: str) -> str:
    if format_name == "json":
        return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if format_name == "yaml":
        return "---\n" + _yaml(document) + "\n"
    if format_name == "xml":
        root = ET.Element("poly-report")
        _xml_value(root, document)
        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n"
    if format_name == "text":
        return _text(document)
    raise ValueError(f"unsupported report format: {format_name}")


def render_cli(
    document: ReportDocument,
    command: str,
    *,
    verbosity: int = 0,
    color: bool = False,
    exit_code: int = 0,
) -> str:
    """Render a compact interactive view without changing the canonical report."""

    lines: list[str] = []
    if verbosity >= 0:
        lines.append(_styled(f"› COMMAND  {command}", "cyan", color))

    if verbosity >= 2:
        lines.extend(_text(document).rstrip().splitlines())
    elif verbosity >= 0:
        _concise_document(lines, document, verbosity, color)

    lines.append(_styled("─" * 72, "muted", color))
    lines.append(_completion_line(document, exit_code, color))
    return "\n".join(lines) + "\n"


def _concise_document(
    lines: list[str], document: ReportDocument, verbosity: int, color: bool
) -> None:
    diagnostics = document.get("diagnostics", [])
    for diagnostic in diagnostics if isinstance(diagnostics, list) else []:
        if isinstance(diagnostic, dict):
            message = diagnostic.get("message")
            lines.append(_styled(f"⚠ WARN     {message}", "yellow", color))

    plan = document.get("plan")
    if isinstance(plan, dict):
        planned = plan.get("planned_actions", [])
        count = len(planned) if isinstance(planned, list) else 0
        lines.append(
            _styled(
                f"› PLAN     {plan.get('id')} · {count} action(s) · {plan.get('status')}",
                "cyan",
                color,
            )
        )
        plan_diagnostics = plan.get("diagnostics", [])
        for diagnostic in plan_diagnostics if isinstance(plan_diagnostics, list) else []:
            if isinstance(diagnostic, dict):
                lines.append(
                    _styled(f"⚠ WARN     {diagnostic.get('message')}", "yellow", color)
                )

    run = document.get("run")
    if isinstance(run, dict):
        actions = run.get("actions", [])
        for action in actions if isinstance(actions, list) else []:
            if isinstance(action, dict):
                _concise_action(lines, action, verbosity, color)
        return

    kind = str(document.get("kind", "report"))
    if kind == "drivers":
        _concise_named_items(lines, document.get("drivers"), "driver", verbosity, color)
    elif kind == "controllers":
        _concise_named_items(
            lines, document.get("controllers"), "controller", verbosity, color
        )
    elif kind == "inspection":
        inventory = document.get("inventory", {})
        nodes = inventory.get("nodes", []) if isinstance(inventory, dict) else []
        count = len(nodes) if isinstance(nodes, list) else 0
        lines.append(_styled(f"✓ OK       inspection · {count} node(s)", "green", color))
        if verbosity >= 1:
            for node in nodes if isinstance(nodes, list) else []:
                if isinstance(node, dict):
                    lines.append(f"           {node.get('id')} · {node.get('path')}")
    elif kind == "actions":
        catalogs = document.get("verbs", [])
        for catalog in catalogs if isinstance(catalogs, list) else []:
            if isinstance(catalog, dict):
                applicable = catalog.get("applicable_actions", [])
                count = len(applicable) if isinstance(applicable, list) else 0
                lines.append(
                    _styled(
                        f"✓ OK       {catalog.get('verb')} · {count} applicable action(s)",
                        "green",
                        color,
                    )
                )


def _concise_named_items(
    lines: list[str],
    value: JsonValue | None,
    noun: str,
    verbosity: int,
    color: bool,
) -> None:
    items = value if isinstance(value, list) else []
    lines.append(_styled(f"✓ OK       {len(items)} {noun}(s)", "green", color))
    if verbosity >= 1:
        for item in items:
            if isinstance(item, dict):
                version = f" {item.get('version')}" if item.get("version") else ""
                lines.append(f"           {item.get('name')}{version}")


def _concise_action(
    lines: list[str], action: dict[str, JsonValue], verbosity: int, color: bool
) -> None:
    state = str(action.get("state", "unknown"))
    marker, label, tone = _state_style(state)
    line = f"{marker} {label:<8} {action.get('action_id')}"
    attempt = action.get("attempt")
    if isinstance(attempt, dict) and (verbosity >= 1 or state != "succeeded"):
        summary = attempt.get("summary")
        if summary:
            line += f" · {str(summary).replace(chr(10), ' ')}"
    blocked = action.get("blocked_by")
    if blocked:
        line += f" · blocked by {_compact(blocked)}"
    lines.append(_styled(line, tone, color))

    if isinstance(attempt, dict) and verbosity >= 1:
        for stream_name in ("stdout", "stderr"):
            stream = attempt.get(stream_name)
            if stream:
                for output_line in str(stream).rstrip().splitlines():
                    lines.append(f"           {stream_name}: {output_line}")


def _completion_line(document: ReportDocument, exit_code: int, color: bool) -> str:
    request = document.get("request", {})
    verb = request.get("verb") if isinstance(request, dict) else document.get("kind", "command")
    run = document.get("run", {})
    actions = run.get("actions", []) if isinstance(run, dict) else []
    counts: dict[str, int] = {}
    for action in actions if isinstance(actions, list) else []:
        if isinstance(action, dict):
            state = str(action.get("state", "unknown"))
            counts[state] = counts.get(state, 0) + 1
    result = " · ".join(f"{value} {state}" for state, value in sorted(counts.items()))
    suffix = f" · {result}" if result else ""
    if exit_code == 0:
        return _styled(f"✓ SUCCESS  poly {verb}{suffix}", "green", color)
    return _styled(f"✗ FAILURE  poly {verb}{suffix}", "red", color)


def _state_style(state: str) -> tuple[str, str, str]:
    if state == "succeeded":
        return "✓", "OK", "green"
    if state == "failed":
        return "✗", "KO", "red"
    if state in {"blocked", "skipped"}:
        return "⚠", "WARN", "yellow"
    return "›", state.upper(), "cyan"


def _styled(value: str, tone: str, enabled: bool) -> str:
    if not enabled:
        return value
    codes = {"green": "32", "red": "31", "yellow": "33", "cyan": "36", "muted": "90"}
    return f"\x1b[{codes[tone]}m{value}\x1b[0m"


def _node_document(node: Node) -> ReportDocument:
    return {
        "id": node.id,
        "path": node.path,
        "natures": list(node.natures),
        "metadata": _json_mapping(node.metadata),
        "relations": [
            {"kind": relation.kind, "target": relation.target} for relation in node.relations
        ],
    }


def _inspection_diagnostic_document(diagnostic: InspectionDiagnostic) -> ReportDocument:
    return {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "path": diagnostic.path,
    }


def _action_document(action: ActionSpec) -> ReportDocument:
    return {
        "id": action.id,
        "driver": action.driver,
        "verb": action.verb,
        "operation": action.operation,
        "node_ids": list(action.node_ids),
        "requested_node_ids": list(action.requested_node_ids),
        "requires": _string_values(constraint.key for constraint in action.requires),
        "produces": _string_values(constraint.key for constraint in action.produces),
        "claims": [
            {"operation": claim.operation, "scope": claim.scope} for claim in sorted(action.claims)
        ],
        "command": list(action.command) if action.command is not None else None,
        "environment": dict(action.environment),
        "changes_structure": action.changes_structure,
        "required_capability": action.required_capability,
    }


def _rejected_document(candidate: RejectedCandidate) -> ReportDocument:
    return {
        "driver": candidate.driver,
        "operation": candidate.operation,
        "reason": candidate.reason,
        "node_ids": list(candidate.node_ids),
        "missing": list(candidate.missing),
    }


def _plan_document(plan: Plan) -> ReportDocument:
    return {
        "id": plan.id,
        "verb": plan.verb,
        "status": plan.status.value,
        "selected_node_ids": list(plan.selected_node_ids),
        "initial_constraints": _string_values(
            constraint.key for constraint in plan.initial_constraints
        ),
        "planned_actions": [_action_document(action) for action in plan.actions],
        "ready_action_ids": list(plan.ready_action_ids),
        "diagnostics": [
            {
                "code": diagnostic.code,
                "message": diagnostic.message,
                "action_id": diagnostic.action_id,
            }
            for diagnostic in plan.diagnostics
        ],
    }


def _action_result_document(result: ActionResult) -> ReportDocument:
    attempt = result.attempt
    return {
        "action_id": result.action_id,
        "state": result.state.value,
        "blocked_by": list(result.blocked_by),
        "attempt": None
        if attempt is None
        else {
            "success": attempt.success,
            "summary": attempt.summary,
            "exit_code": attempt.exit_code,
            "stdout": attempt.stdout,
            "stderr": attempt.stderr,
            "details": _json_mapping(attempt.details),
        },
    }


def _event_document(event: RunEvent) -> ReportDocument:
    return {
        "sequence": event.sequence,
        "state": event.state.value,
        "action_id": event.action_id,
        "message": event.message,
    }


def _json_mapping(value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: _json_value(item) for key, item in value.items()}


def _json_value(value: JsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _string_values(values: Iterable[str]) -> list[JsonValue]:
    return [value for value in values]


def _yaml(value: object, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, Mapping):
        if not value:
            return prefix + "{}"
        lines: list[str] = []
        for key, item in value.items():
            rendered_key = json.dumps(str(key), ensure_ascii=False)
            if _is_scalar(item) or _is_empty_collection(item):
                lines.append(f"{prefix}{rendered_key}: {_yaml_scalar(item)}")
            else:
                lines.append(f"{prefix}{rendered_key}:")
                lines.append(_yaml(item, indent + 2))
        return "\n".join(lines)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not value:
            return prefix + "[]"
        lines = []
        for item in value:
            if _is_scalar(item) or _is_empty_collection(item):
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
            else:
                lines.append(f"{prefix}-")
                lines.append(_yaml(item, indent + 2))
        return "\n".join(lines)
    return prefix + _yaml_scalar(value)


def _yaml_scalar(value: object) -> str:
    if isinstance(value, Mapping) and not value:
        return "{}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) and not value:
        return "[]"
    return json.dumps(value, ensure_ascii=False)


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _is_empty_collection(value: object) -> bool:
    return isinstance(value, (Mapping, list, tuple)) and not value


def _xml_value(parent: ET.Element, value: object) -> None:
    if isinstance(value, Mapping):
        parent.set("type", "object")
        for key, item in value.items():
            field = ET.SubElement(parent, "field", name=str(key))
            _xml_value(field, item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parent.set("type", "array")
        for item in value:
            child = ET.SubElement(parent, "item")
            _xml_value(child, item)
        return
    if value is None:
        parent.set("type", "null")
    elif isinstance(value, bool):
        parent.set("type", "boolean")
        parent.text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        parent.set("type", "number")
        parent.text = str(value)
    else:
        parent.set("type", "string")
        parent.text = str(value)


def _text(document: ReportDocument) -> str:
    lines = [f"Poly {document['kind']} report", f"Schema: {document['schema']}"]
    verbs_value = document.get("available_verbs", [])
    verbs = verbs_value if isinstance(verbs_value, list) else []
    lines.append(f"Available verbs: {', '.join(str(verb) for verb in verbs) or '-'}")
    inventory = document.get("inventory", {})
    nodes_value = inventory.get("nodes", []) if isinstance(inventory, dict) else []
    nodes = nodes_value if isinstance(nodes_value, list) else []
    lines.append(f"Nodes: {len(nodes)}")
    for node in nodes:
        if isinstance(node, dict):
            natures_value = node.get("natures", [])
            natures_items = natures_value if isinstance(natures_value, list) else []
            natures = ", ".join(str(item) for item in natures_items)
            lines.append(f"  {node.get('id')} [{natures}] {node.get('path')}")
            if node.get("metadata"):
                lines.append(f"    metadata: {_compact(node.get('metadata'))}")
            if node.get("relations"):
                lines.append(f"    relations: {_compact(node.get('relations'))}")
    diagnostics = document.get("diagnostics", [])
    for diagnostic in diagnostics if isinstance(diagnostics, list) else []:
        if isinstance(diagnostic, dict):
            lines.append(f"Diagnostic {diagnostic.get('code')}: {diagnostic.get('message')}")
    _text_planning(lines, document)
    _text_controllers(lines, document)
    _text_run(lines, document)
    return "\n".join(lines) + "\n"


def _text_planning(lines: list[str], document: ReportDocument) -> None:
    applicable = document.get("applicable_actions")
    if isinstance(applicable, list):
        lines.append(f"Applicable actions: {len(applicable)}")
        for action in applicable:
            if isinstance(action, dict):
                _text_action(lines, action, "  ")
    rejected = document.get("rejected_candidates")
    if isinstance(rejected, list):
        lines.append(f"Rejected candidates: {len(rejected)}")
        for candidate in rejected:
            if isinstance(candidate, dict):
                lines.append(
                    f"  {candidate.get('driver')} {candidate.get('operation')}: "
                    f"{candidate.get('reason')}"
                )
    plan = document.get("plan")
    if isinstance(plan, dict):
        lines.append(f"Plan: {plan.get('id')} [{plan.get('status')}]")
        planned = plan.get("planned_actions", [])
        lines.append(f"Planned actions: {len(planned) if isinstance(planned, list) else 0}")
        for action in planned if isinstance(planned, list) else []:
            if isinstance(action, dict):
                _text_action(lines, action, "  ")
        ready = plan.get("ready_action_ids", [])
        ready_text = (
            ", ".join(str(action_id) for action_id in ready) if isinstance(ready, list) else ""
        )
        lines.append(f"Ready actions: {ready_text or '-'}")
        plan_diagnostics = plan.get("diagnostics", [])
        for diagnostic in plan_diagnostics if isinstance(plan_diagnostics, list) else []:
            if isinstance(diagnostic, dict):
                lines.append(
                    f"Plan diagnostic {diagnostic.get('code')}: {diagnostic.get('message')}"
                )
    catalogs = document.get("verbs")
    if isinstance(catalogs, list):
        for catalog in catalogs:
            if isinstance(catalog, dict):
                applicable = catalog.get("applicable_actions", [])
                ready = catalog.get("ready_action_ids", [])
                applicable_count = len(applicable) if isinstance(applicable, list) else 0
                ready_count = len(ready) if isinstance(ready, list) else 0
                lines.append(
                    f"Verb {catalog.get('verb')}: {applicable_count} applicable, "
                    f"{ready_count} ready"
                )
                for action in applicable if isinstance(applicable, list) else []:
                    if isinstance(action, dict):
                        _text_action(lines, action, "  ")


def _text_run(lines: list[str], document: ReportDocument) -> None:
    run = document.get("run")
    if not isinstance(run, dict):
        return
    lines.append(f"Run: {run.get('status')}")
    actions = run.get("actions", [])
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        lines.append(f"  {action.get('action_id')}: {action.get('state')}")
        if action.get("blocked_by"):
            lines.append(f"    blocked by: {_compact(action.get('blocked_by'))}")
        attempt = action.get("attempt")
        if isinstance(attempt, dict):
            lines.append(f"    {attempt.get('summary')} (exit={attempt.get('exit_code')})")
            if attempt.get("stdout"):
                lines.append(f"    stdout: {attempt['stdout']}")
            if attempt.get("stderr"):
                lines.append(f"    stderr: {attempt['stderr']}")
            if attempt.get("details"):
                lines.append(f"    details: {_compact(attempt.get('details'))}")
    events = run.get("events", [])
    if isinstance(events, list):
        lines.append(f"Events: {len(events)}")
        for event in events:
            if isinstance(event, dict):
                lines.append(
                    f"  {event.get('sequence')}. {event.get('action_id')} "
                    f"{event.get('state')} {event.get('message')}"
                )


def _text_controllers(lines: list[str], document: ReportDocument) -> None:
    controllers = document.get("controllers")
    if not isinstance(controllers, list):
        return
    lines.append(f"Controllers: {len(controllers)}")
    for controller in controllers:
        if isinstance(controller, dict):
            lines.append(
                f"  {controller.get('name')} [{controller.get('platform')}] "
                f"{_compact(controller.get('capabilities'))}"
            )


def _text_action(lines: list[str], action: dict[str, JsonValue], prefix: str) -> None:
    lines.append(f"{prefix}{action.get('id')} ({action.get('operation')})")
    lines.append(f"{prefix}  nodes: {_compact(action.get('node_ids'))}")
    if action.get("requires"):
        lines.append(f"{prefix}  requires: {_compact(action.get('requires'))}")
    if action.get("produces"):
        lines.append(f"{prefix}  produces: {_compact(action.get('produces'))}")
    if action.get("command"):
        lines.append(f"{prefix}  command: {_compact(action.get('command'))}")


def _compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
