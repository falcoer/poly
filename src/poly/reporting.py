"""Canonical report documents and format renderers."""

from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from poly.application import InspectionSnapshot, PlanningSnapshot
from poly.control_plane import ControllerDescriptor
from poly.driver import (
    DriverInventoryItem,
    DriverManifest,
    InspectionDiagnostic,
    OutputReference,
)
from poly.model import (
    ActionSpec,
    JsonValue,
    Node,
    Plan,
    RejectedCandidate,
)
from poly.runtime import ActionResult, ActionState, RunEvent, RunResult

type ReportDocument = dict[str, JsonValue]
REPORT_SCHEMA = "poly.report/v1"
_SECTION_INDENT = "        "
_DETAIL_INDENT = "                "
_LOG_INDENT = "                        "
_FALLBACK_WIDTH = 72


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
        "drivers": [_driver_document(item) for item in snapshot.drivers],
    }


def document_with_outputs(
    document: ReportDocument, outputs: Sequence[OutputReference]
) -> ReportDocument:
    """Return a report document exposing explicit command deliverables."""

    enriched = dict(document)
    enriched["outputs"] = [_output_document(output) for output in outputs]
    return enriched


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
    document["plan"] = plan_document(snapshot.plan)
    return document


def plan_document(plan: Plan) -> ReportDocument:
    """Serialize the canonical frozen plan for persistence and execution."""

    return _plan_document(plan)


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


def prepared_run_document(document: ReportDocument, result: RunResult) -> ReportDocument:
    """Attach an execution result to an already persisted prepared-plan document."""

    run = dict(document)
    run["kind"] = "run"
    run["run"] = {
        "plan_id": result.plan_id,
        "status": result.status.value,
        "available_constraints": list(result.available_constraints),
        "actions": [_action_result_document(action) for action in result.actions],
        "events": [_event_document(event) for event in result.events],
    }
    return run


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


def drivers_document(workspace: Path, inventory: tuple[DriverInventoryItem, ...]) -> ReportDocument:
    return {
        "schema": REPORT_SCHEMA,
        "kind": "drivers",
        "workspace": str(workspace.resolve()),
        "available_verbs": [],
        "inventory": {"nodes": []},
        "diagnostics": [],
        "drivers": [_driver_document(item) for item in inventory],
    }


def _driver_document(item: DriverInventoryItem) -> ReportDocument:
    return {
        "name": item.identity,
        "version": item.version,
        "origin": item.origin,
        "api_version": item.api_version,
        "capabilities": list(item.capabilities),
        "verbs": list(item.verbs),
        "status": item.status,
        "entry_point": item.entry_point,
        "diagnostic": item.diagnostic,
        "description": item.description,
        "natures": list(item.natures),
        "facades": list(item.facades),
    }


def natures_document(workspace: Path, manifests: tuple[DriverManifest, ...]) -> ReportDocument:
    contributors: dict[str, list[str]] = {}
    for manifest in manifests:
        for nature in manifest.natures:
            contributors.setdefault(nature, []).append(manifest.name)
    return {
        "schema": REPORT_SCHEMA,
        "kind": "natures",
        "workspace": str(workspace.resolve()),
        "available_verbs": [],
        "inventory": {"nodes": []},
        "diagnostics": [],
        "natures": [
            {"name": nature, "drivers": _string_values(sorted(contributors[nature]))}
            for nature in sorted(contributors)
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
    width: int = _FALLBACK_WIDTH,
    hyperlinks: bool = False,
) -> str:
    """Render a compact interactive view without changing the canonical report."""

    lines: list[str] = []
    separator = _styled("─" * _usable_width(width), "muted", color)
    if verbosity >= 0:
        lines.append(separator)
        lines.append(_command_heading(document))
        if verbosity >= 1:
            lines.append(f"{_SECTION_INDENT}COMMAND  {command}")

    if verbosity >= 2:
        lines.extend(
            f"{_SECTION_INDENT}{_safe_visible(line)}"
            for line in _text(document).rstrip().splitlines()
        )
    elif verbosity >= 0:
        _concise_document(lines, document, verbosity, color, width)

    lines.append(separator)
    lines.append(f"{_SECTION_INDENT}{_completion_line(document, exit_code, color)}")
    _append_outputs(lines, document, hyperlinks=hyperlinks)
    lines.append(separator)
    return "\n".join(lines) + "\n"


def render_cli_start(
    document: ReportDocument,
    command: str,
    *,
    verbosity: int = 0,
    color: bool = False,
    width: int = _FALLBACK_WIDTH,
) -> str:
    """Render the portion known before execution starts."""

    if verbosity < 0:
        return ""
    lines = [
        _styled("─" * _usable_width(width), "muted", color),
        _command_heading(document),
    ]
    if verbosity >= 1:
        lines.append(f"{_SECTION_INDENT}COMMAND  {command}")
    _concise_plan(lines, document, color)
    return "\n".join(lines) + "\n"


def render_cli_event(
    event: RunEvent,
    action: ActionSpec | None,
    *,
    verbosity: int = 0,
    color: bool = False,
    width: int = _FALLBACK_WIDTH,
) -> str:
    """Render an execution transition suitable for immediate terminal output."""

    if verbosity < 0 or event.state not in {
        ActionState.RUNNING,
        ActionState.SUCCEEDED,
        ActionState.FAILED,
        ActionState.BLOCKED,
    }:
        return ""
    marker, label, tone = _state_style(event.state.value)
    line = f"{marker} {label:<8} {_safe_visible(event.action_id)}"
    if action is not None:
        line += f" ({_safe_visible(action.operation)})"
    if event.value is not None:
        rendered_value = (
            f"{event.value.label}: {event.value.value}"
            if event.value.label
            else str(event.value.value)
        )
        line += f" · {_safe_visible(rendered_value)}"
    elif event.message:
        suffix = "blocked by " if event.state is ActionState.BLOCKED else ""
        line += f" · {suffix}{_safe_visible(event.message)}"
    return _render_action_lines(line, tone, color, width)


def render_cli_progress(
    completed: int,
    total: int,
    *,
    failed: bool = False,
    blocked: bool = False,
    color: bool = False,
    width: int = _FALLBACK_WIDTH,
) -> str:
    """Render one adaptive global plan progress row."""

    bounded_total = max(1, total)
    bounded_completed = min(max(0, completed), bounded_total)
    percentage = bounded_completed * 100 // bounded_total
    label = "PLAN KO" if failed else "PLAN WARN" if blocked else "PLAN"
    prefix = f"{_SECTION_INDENT}{label:<10}"
    suffix = f"{bounded_completed}/{bounded_total} actions · {percentage:3d} %"
    available = _usable_width(width)
    bar_width = available - _display_width(prefix) - _display_width(suffix) - 3
    if bar_width >= 5:
        filled = percentage * bar_width // 100
        bar = "█" * filled + "─" * (bar_width - filled)
        line = f"{prefix}[{bar}] {suffix}"
    else:
        compact_label = "KO" if failed else "WARN" if blocked else "PLAN"
        compact = f"{compact_label} {bounded_completed}/{bounded_total} {percentage}%"
        indent = " " * min(len(_SECTION_INDENT), max(0, available - _display_width(compact)))
        line = indent + compact
    tone = "red" if failed else "yellow" if blocked else "cyan"
    return _styled(line, tone, color) + "\n"


def render_cli_completion(
    document: ReportDocument,
    *,
    verbosity: int = 0,
    color: bool = False,
    exit_code: int = 0,
    width: int = _FALLBACK_WIDTH,
    hyperlinks: bool = False,
) -> str:
    """Render logs/details and the final frame after streamed execution."""

    lines: list[str] = []
    if verbosity >= 2:
        lines.extend(
            f"{_SECTION_INDENT}{_safe_visible(line)}"
            for line in _text(document).rstrip().splitlines()
        )
    elif verbosity >= 1:
        _append_run_logs(lines, document)
    separator = _styled("─" * _usable_width(width), "muted", color)
    lines.append(separator)
    lines.append(f"{_SECTION_INDENT}{_completion_line(document, exit_code, color)}")
    _append_outputs(lines, document, hyperlinks=hyperlinks)
    lines.append(separator)
    return "\n".join(lines) + "\n"


def _command_heading(document: ReportDocument) -> str:
    request = document.get("request", {})
    kind = str(document.get("kind", "command"))
    verb = str(request.get("verb", kind)) if isinstance(request, dict) else kind
    labels = {
        "add": "ADDING",
        "actions": "LISTING ACTIONS",
        "bootstrap": "BOOTSTRAPPING",
        "build": "BUILDING",
        "clean": "CLEANING",
        "controllers": "LISTING CONTROLLERS",
        "drivers": "LISTING DRIVERS",
        "hydrate": "HYDRATING",
        "init": "INITIALIZING",
        "inspection": "INSPECTING",
        "install": "INSTALLING",
        "lock": "LOCKING",
        "nature-add": "ADDING NATURES TO",
        "nature-remove": "REMOVING NATURES FROM",
        "natures": "LISTING NATURES",
        "package": "PACKAGING",
        "plan": "PLANNING",
        "remove": "REMOVING",
        "exec": "EXECUTING PREPARED PLAN",
        "status": "CHECKING STATUS",
        "test": "TESTING",
        "update": "UPDATING",
        "verify": "VERIFYING",
    }
    label = labels.get(verb, f"RUNNING {verb.upper()}")
    target = _command_target(request)
    if verb == "add" and isinstance(request, dict):
        parameters = request.get("parameters", {})
        if isinstance(parameters, dict) and parameters.get("poly.source.url"):
            source = _safe_source_url(str(parameters["poly.source.url"]))
            requested_ref = parameters.get("poly.source.ref")
            ref = f" (ref: {_safe_visible(str(requested_ref))})" if requested_ref else ""
            return f"{label}{f' {target}' if target else ''} from {source}{ref} ..."
    return f"{label}{f' {target}' if target else ''} ..."


def _command_target(request: JsonValue) -> str:
    if not isinstance(request, dict):
        return ""
    parameters = request.get("parameters", {})
    if isinstance(parameters, dict):
        for key in ("poly.node.id", "poly.name"):
            value = parameters.get(key)
            if value:
                return str(value)
    selected = request.get("selected_node_ids", [])
    if isinstance(selected, list) and selected:
        return ", ".join(str(item) for item in selected)
    return ""


def _concise_document(
    lines: list[str], document: ReportDocument, verbosity: int, color: bool, width: int
) -> None:
    operations: dict[str, str] = {}
    diagnostics = document.get("diagnostics", [])
    for diagnostic in diagnostics if isinstance(diagnostics, list) else []:
        if isinstance(diagnostic, dict):
            message = diagnostic.get("message")
            lines.append(f"{_DETAIL_INDENT}{_styled(f'⚠ WARN     {message}', 'yellow', color)}")

    plan = document.get("plan")
    if isinstance(plan, dict):
        planned = plan.get("planned_actions", [])
        count = len(planned) if isinstance(planned, list) else 0
        for action in planned if isinstance(planned, list) else []:
            if isinstance(action, dict):
                operations[str(action.get("id"))] = str(action.get("operation"))
        plan_line = f"PLAN     {plan.get('id')} · {count} action(s) · {plan.get('status')}"
        lines.append(f"{_SECTION_INDENT}{_styled(plan_line, 'cyan', color)}")
        plan_diagnostics = plan.get("diagnostics", [])
        for diagnostic in plan_diagnostics if isinstance(plan_diagnostics, list) else []:
            if isinstance(diagnostic, dict):
                warning = f"⚠ WARN     {diagnostic.get('message')}"
                lines.append(f"{_DETAIL_INDENT}{_styled(warning, 'yellow', color)}")

    run = document.get("run")
    if isinstance(run, dict):
        actions = run.get("actions", [])
        for action in actions if isinstance(actions, list) else []:
            if isinstance(action, dict):
                operation = operations.get(str(action.get("action_id")))
                _concise_action(lines, action, operation, verbosity, color, width)
        return

    kind = str(document.get("kind", "report"))
    if kind == "drivers":
        _concise_drivers(lines, document.get("drivers"), verbosity, color)
    elif kind == "natures":
        _concise_named_items(lines, document.get("natures"), "nature", verbosity, color)
    elif kind == "controllers":
        _concise_named_items(lines, document.get("controllers"), "controller", verbosity, color)
    elif kind == "inspection":
        inventory = document.get("inventory", {})
        nodes = inventory.get("nodes", []) if isinstance(inventory, dict) else []
        count = len(nodes) if isinstance(nodes, list) else 0
        status = _styled(f"✓ OK       inspection · {count} node(s)", "green", color)
        lines.append(f"{_SECTION_INDENT}{status}")
        if verbosity >= 1:
            for node in nodes if isinstance(nodes, list) else []:
                if isinstance(node, dict):
                    lines.append(f"{_DETAIL_INDENT}{node.get('id')} · {node.get('path')}")
    elif kind == "actions":
        catalogs = document.get("verbs", [])
        for catalog in catalogs if isinstance(catalogs, list) else []:
            if isinstance(catalog, dict):
                applicable = catalog.get("applicable_actions", [])
                count = len(applicable) if isinstance(applicable, list) else 0
                status = f"✓ OK       {catalog.get('verb')} · {count} applicable action(s)"
                lines.append(f"{_SECTION_INDENT}{_styled(status, 'green', color)}")


def _concise_plan(lines: list[str], document: ReportDocument, color: bool) -> None:
    plan = document.get("plan")
    if not isinstance(plan, dict):
        return
    planned = plan.get("planned_actions", [])
    count = len(planned) if isinstance(planned, list) else 0
    plan_line = f"PLAN     {plan.get('id')} · {count} action(s) · {plan.get('status')}"
    lines.append(f"{_SECTION_INDENT}{_styled(plan_line, 'cyan', color)}")
    diagnostics = plan.get("diagnostics", [])
    for diagnostic in diagnostics if isinstance(diagnostics, list) else []:
        if isinstance(diagnostic, dict):
            warning = f"⚠ WARN     {diagnostic.get('message')}"
            lines.append(f"{_DETAIL_INDENT}{_styled(warning, 'yellow', color)}")


def _append_run_logs(lines: list[str], document: ReportDocument) -> None:
    run = document.get("run", {})
    actions = run.get("actions", []) if isinstance(run, dict) else []
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        attempt = action.get("attempt")
        if not isinstance(attempt, dict):
            continue
        for stream_name in ("stdout", "stderr"):
            stream = attempt.get(stream_name)
            if stream:
                for output_line in str(stream).rstrip().splitlines():
                    lines.append(f"{_LOG_INDENT}{stream_name}: {_safe_visible(output_line)}")


def _append_outputs(
    lines: list[str], document: ReportDocument, *, hyperlinks: bool = False
) -> None:
    run = document.get("run", {})
    actions = run.get("actions", []) if isinstance(run, dict) else []
    outputs: list[tuple[str, str, str | None, str | None]] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        attempt = action.get("attempt")
        references = attempt.get("outputs", []) if isinstance(attempt, dict) else []
        for reference in references if isinstance(references, list) else []:
            if not isinstance(reference, dict):
                continue
            key = (
                str(reference.get("kind", "")),
                str(reference.get("target", "")),
                str(reference["label"]) if reference.get("label") is not None else None,
                str(reference["media_type"]) if reference.get("media_type") is not None else None,
            )
            if (
                key in seen
                or key[0] not in {"file", "url"}
                or not _is_safe_text(key[1])
                or _output_href(key[0], key[1]) is None
            ):
                continue
            seen.add(key)
            outputs.append(key)
    command_outputs = document.get("outputs", [])
    for reference in command_outputs if isinstance(command_outputs, list) else []:
        if not isinstance(reference, dict):
            continue
        key = (
            str(reference.get("kind", "")),
            str(reference.get("target", "")),
            str(reference["label"]) if reference.get("label") is not None else None,
            str(reference["media_type"]) if reference.get("media_type") is not None else None,
        )
        if (
            key in seen
            or key[0] not in {"file", "url"}
            or not _is_safe_text(key[1])
            or _output_href(key[0], key[1]) is None
        ):
            continue
        seen.add(key)
        outputs.append(key)
    if not outputs:
        return
    lines.append(f"{_SECTION_INDENT}> OUTPUT")
    for kind, target, label, _media_type in outputs:
        visible = _safe_visible(f"{label}: {target}" if label else target)
        href = _output_href(kind, target)
        if hyperlinks and href is not None:
            visible = f"\x1b]8;;{href}\x1b\\{visible}\x1b]8;;\x1b\\"
        lines.append(f"{_DETAIL_INDENT}{visible}")


def _concise_named_items(
    lines: list[str],
    value: JsonValue | None,
    noun: str,
    verbosity: int,
    color: bool,
) -> None:
    items = value if isinstance(value, list) else []
    status = _styled(f"✓ OK       {len(items)} {noun}(s)", "green", color)
    lines.append(f"{_SECTION_INDENT}{status}")
    if verbosity >= 1:
        for item in items:
            if isinstance(item, dict):
                version = f" {item.get('version')}" if item.get("version") else ""
                lines.append(f"{_DETAIL_INDENT}{item.get('name')}{version}")


def _concise_drivers(
    lines: list[str], value: JsonValue | None, verbosity: int, color: bool
) -> None:
    items = value if isinstance(value, list) else []
    loaded = sum(1 for item in items if isinstance(item, dict) and item.get("status") == "loaded")
    rejected = len(items) - loaded
    summary = f"✓ OK       {loaded} loaded driver(s) · {rejected} rejected"
    lines.append(f"{_SECTION_INDENT}{_styled(summary, 'green', color)}")
    for item in items:
        if not isinstance(item, dict):
            continue
        capabilities = item.get("capabilities", [])
        verbs = item.get("verbs", [])
        capability_values = capabilities if isinstance(capabilities, list) else []
        verb_values = verbs if isinstance(verbs, list) else []
        state = str(item.get("status"))
        marker, label, tone = _state_style("succeeded" if state == "loaded" else "failed")
        line = (
            f"{marker} {label:<8} {item.get('name')} {item.get('version') or '-'} "
            f"· {item.get('origin')} · API {item.get('api_version') or '-'} "
            f"· capabilities={','.join(str(value) for value in capability_values) or '-'} "
            f"· verbs={','.join(str(value) for value in verb_values) or '-'}"
        )
        lines.append(f"{_DETAIL_INDENT}{_styled(line, tone, color)}")
        if item.get("diagnostic"):
            lines.append(f"{_LOG_INDENT}diagnostic: {item.get('diagnostic')}")
        if verbosity >= 1 and item.get("entry_point"):
            lines.append(f"{_LOG_INDENT}entry point: {item.get('entry_point')}")


def _concise_action(
    lines: list[str],
    action: dict[str, JsonValue],
    operation: str | None,
    verbosity: int,
    color: bool,
    width: int,
) -> None:
    state = str(action.get("state", "unknown"))
    marker, label, tone = _state_style(state)
    line = f"{marker} {label:<8} {_safe_visible(str(action.get('action_id')))}"
    if operation:
        line += f" ({_safe_visible(operation)})"
    attempt = action.get("attempt")
    if isinstance(attempt, dict):
        value = attempt.get("value")
        if isinstance(value, dict):
            scalar = value.get("value")
            value_label = value.get("label")
            rendered = f"{value_label}: {scalar}" if value_label else str(scalar)
            line += f" · {_safe_visible(rendered)}"
        summary = attempt.get("summary")
        if summary and not isinstance(value, dict):
            line += f" · {_safe_visible(str(summary))}"
    blocked = action.get("blocked_by")
    if blocked:
        line += f" · blocked by {_compact(blocked)}"
    lines.extend(_render_action_lines(line, tone, color, width).rstrip().splitlines())

    if isinstance(attempt, dict) and verbosity >= 1:
        for stream_name in ("stdout", "stderr"):
            stream = attempt.get(stream_name)
            if stream:
                for output_line in str(stream).rstrip().splitlines():
                    lines.append(f"{_LOG_INDENT}{stream_name}: {_safe_visible(output_line)}")


def _completion_line(document: ReportDocument, exit_code: int, color: bool) -> str:
    request = document.get("request", {})
    kind = str(document.get("kind", "command"))
    fallback = "inspect" if kind == "inspection" else kind
    verb = request.get("verb", fallback) if isinstance(request, dict) else fallback
    verb = verb or fallback
    run = document.get("run", {})
    actions = run.get("actions", []) if isinstance(run, dict) else []
    counts: dict[str, int] = {}
    for action in actions if isinstance(actions, list) else []:
        if isinstance(action, dict):
            state = str(action.get("state", "unknown"))
            counts[state] = counts.get(state, 0) + 1
    result = " · ".join(f"{value} {state}" for state, value in sorted(counts.items()))
    suffix = f" · {result}" if result else ""
    plan = document.get("plan", {})
    if isinstance(plan, dict) and plan.get("status") == "empty":
        return _styled(f"· NONE     poly {verb}", "muted", color)
    if exit_code == 0:
        return _styled(f"✓ SUCCESS  poly {verb}{suffix}", "green", color)
    return _styled(f"✗ FAILURE  poly {verb}{suffix}", "red", color)


def _usable_width(width: int) -> int:
    return max(24, width if width > 0 else _FALLBACK_WIDTH)


def _render_action_lines(line: str, tone: str, color: bool, width: int) -> str:
    available = _usable_width(width)
    prefix = _DETAIL_INDENT
    if _display_width(prefix) + _display_width(line) <= available or " · " not in line:
        return f"{prefix}{_styled(line, tone, color)}\n"
    primary, detail = line.split(" · ", 1)
    primary_width = max(1, available - _display_width(prefix))
    primary_chunks = (
        [primary]
        if _display_width(primary) <= primary_width
        else _wrap_display(primary, primary_width)
    )
    detail_width = max(1, available - _display_width(_LOG_INDENT) - 2)
    chunks = _wrap_display(detail, detail_width)
    rendered = [f"{prefix}{_styled(chunk, tone, color)}" for chunk in primary_chunks]
    rendered.extend(f"{_LOG_INDENT}· {chunk}" for chunk in chunks)
    return "\n".join(rendered) + "\n"


def _display_width(value: str) -> int:
    return sum(
        0
        if unicodedata.combining(character)
        else 2
        if unicodedata.east_asian_width(character) in {"W", "F"}
        else 1
        for character in value
    )


def _wrap_display(value: str, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in value.split():
        candidate = f"{current} {word}" if current else word
        if _display_width(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        chunk = ""
        for character in word:
            if chunk and _display_width(chunk + character) > width:
                lines.append(chunk)
                chunk = ""
            chunk += character
        current = chunk
    if current or not lines:
        lines.append(current)
    return lines


def _is_safe_text(value: str) -> bool:
    return bool(value) and not any(
        ord(character) < 32 or ord(character) == 127 for character in value
    )


def _safe_visible(value: str) -> str:
    if _is_safe_text(value):
        return value
    return (
        "".join(
            character if ord(character) >= 32 and ord(character) != 127 else "?"
            for character in value.replace("\x1b", "?")
        )
        .replace("\n", "?")
        .replace("\r", "?")
    )


def _safe_source_url(value: str) -> str:
    safe = _safe_visible(value)
    if "://" not in safe:
        return safe
    parsed = urlsplit(safe)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        parsed_port = parsed.port
    except ValueError:
        return "<invalid-source>"
    port = f":{parsed_port}" if parsed_port is not None else ""
    return urlunsplit(
        (parsed.scheme, f"{hostname}{port}", parsed.path, parsed.query, parsed.fragment)
    )


def _output_href(kind: str, target: str) -> str | None:
    if not _is_safe_text(target):
        return None
    if kind == "url":
        parsed = urlsplit(target)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
        return target
    if kind == "file":
        if re.match(r"^[A-Za-z]:[\\/]", target):
            drive = target[0].upper()
            suffix = target[2:].replace("\\", "/")
            return f"file:///{drive}:{quote(suffix, safe='/')}"
        path = Path(target)
        try:
            return path.resolve().as_uri()
        except ValueError:
            return None
    return None


def _state_style(state: str) -> tuple[str, str, str]:
    if state == "succeeded":
        return "✓", "OK", "green"
    if state == "failed":
        return "✗", "KO", "red"
    if state in {"blocked", "skipped"}:
        return "⚠", "WARN", "yellow"
    return ">", state.upper(), "cyan"


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
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "duration_ms": result.duration_ms,
        "attempt": None
        if attempt is None
        else {
            "success": attempt.success,
            "summary": attempt.summary,
            "exit_code": attempt.exit_code,
            "stdout": attempt.stdout,
            "stderr": attempt.stderr,
            "details": _json_mapping(attempt.details),
            "value": None
            if attempt.value is None
            else {"value": attempt.value.value, "label": attempt.value.label},
            "outputs": [_output_document(output) for output in attempt.outputs],
        },
    }


def _output_document(output: OutputReference) -> ReportDocument:
    return {
        "kind": str(output.kind),
        "target": output.target,
        "label": output.label,
        "media_type": output.media_type,
    }


def _event_document(event: RunEvent) -> ReportDocument:
    return {
        "sequence": event.sequence,
        "state": event.state.value,
        "action_id": event.action_id,
        "message": event.message,
        "occurred_at": event.occurred_at,
        "value": None
        if event.value is None
        else {"value": event.value.value, "label": event.value.label},
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
    _text_drivers(lines, document)
    _text_planning(lines, document)
    _text_controllers(lines, document)
    _text_run(lines, document)
    outputs = document.get("outputs", [])
    for output in outputs if isinstance(outputs, list) else []:
        if isinstance(output, dict):
            lines.append(f"Output ({output.get('kind')}): {output.get('target')}")
    return "\n".join(lines) + "\n"


def _text_drivers(lines: list[str], document: ReportDocument) -> None:
    drivers = document.get("drivers")
    if not isinstance(drivers, list):
        return
    lines.append(f"Drivers: {len(drivers)}")
    for driver in drivers:
        if not isinstance(driver, dict):
            continue
        lines.append(
            f"  {driver.get('name')} {driver.get('version') or '-'} "
            f"[{driver.get('status')}] origin={driver.get('origin')} "
            f"api={driver.get('api_version') or '-'}"
        )
        capabilities = driver.get("capabilities", [])
        verbs = driver.get("verbs", [])
        capability_values = capabilities if isinstance(capabilities, list) else []
        verb_values = verbs if isinstance(verbs, list) else []
        lines.append(
            "    capabilities: " + (", ".join(str(value) for value in capability_values) or "-")
        )
        lines.append("    verbs: " + (", ".join(str(value) for value in verb_values) or "-"))
        if driver.get("diagnostic"):
            lines.append(f"    diagnostic: {driver.get('diagnostic')}")


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
            value = attempt.get("value")
            if isinstance(value, dict):
                label = f"{value.get('label')}: " if value.get("label") else ""
                lines.append(f"    value: {label}{value.get('value')}")
            outputs = attempt.get("outputs", [])
            for output in outputs if isinstance(outputs, list) else []:
                if isinstance(output, dict):
                    lines.append(f"    output ({output.get('kind')}): {output.get('target')}")
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
                    f"{event.get('state')} {event.get('message')} @ {event.get('occurred_at')}"
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
