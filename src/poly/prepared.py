"""Composition and staleness checks for the single prepared workspace plan."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

from poly.application import PlanningSnapshot
from poly.model import (
    ActionSpec,
    Constraint,
    JsonValue,
    Plan,
    PlanDiagnostic,
    PlanStatus,
    RejectedCandidate,
)
from poly.reporting import ReportDocument, inspection_document, plan_document

AUTHORED_FILES = ("poly.yaml", "poly.lock.yaml", ".gitignore")
_RECOMPUTED_DIAGNOSTICS = frozenset(
    {"action.duplicate-id", "claim.conflict", "constraint.cycle", "constraint.missing"}
)


class PreparedPlanError(ValueError):
    pass


def workspace_fingerprint(workspace: Path) -> str:
    digest = hashlib.sha256()
    for name in AUTHORED_FILES:
        path = workspace / name
        digest.update(name.encode())
        digest.update(b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def prepare_document(
    snapshot: PlanningSnapshot,
    command: str,
    previous: ReportDocument | None = None,
) -> ReportDocument:
    fingerprint = workspace_fingerprint(snapshot.inspection.workspace)
    plans: tuple[Plan, ...] = (snapshot.plan,)
    requests: list[JsonValue] = []
    commands: list[str] = []
    if previous is not None:
        prepared = previous.get("prepared")
        if not isinstance(prepared, dict) or prepared.get("workspace_fingerprint") != fingerprint:
            raise PreparedPlanError("the prepared plan is stale; clear it before preparing again")
        plans = (plan_from_document(previous), snapshot.plan)
        requests.extend(_request_values(previous.get("requests")))
        commands.extend(_string_values(prepared.get("commands")))
    requests.append(
        {
            "verb": snapshot.request.verb,
            "selected_node_ids": list(snapshot.request.selected_node_ids),
            "parameters": dict(snapshot.request.parameters),
        }
    )
    commands.append(command)
    plan = compose_plans(plans)
    document = inspection_document(snapshot.inspection)
    document.update(
        {
            "kind": "prepared-plan",
            "request": {
                "verb": snapshot.request.verb,
                "selected_node_ids": list(snapshot.request.selected_node_ids),
                "parameters": dict(snapshot.request.parameters),
            },
            "requests": requests,
            "applicable_actions": [
                cast(dict[str, JsonValue], action_document(action)) for action in plan.actions
            ],
            "rejected_candidates": [
                cast(dict[str, JsonValue], rejected_document(candidate))
                for candidate in plan.rejected
            ],
            "plan": plan_document(plan),
            "prepared": {
                "workspace_fingerprint": fingerprint,
                "commands": cast(list[JsonValue], commands),
            },
        }
    )
    return document


def require_current(document: ReportDocument, workspace: Path) -> Plan:
    prepared = document.get("prepared")
    if not isinstance(prepared, dict):
        raise PreparedPlanError("persisted document is not a prepared plan")
    if prepared.get("workspace_fingerprint") != workspace_fingerprint(workspace):
        raise PreparedPlanError("the prepared plan is stale; clear it and prepare it again")
    plan = plan_from_document(document)
    if compose_plans((plan,)).id != plan.id:
        raise PreparedPlanError("the prepared plan content does not match its identifier")
    return plan


def compose_plans(plans: tuple[Plan, ...]) -> Plan:
    actions = _sequenced_actions(plans)
    rejected = tuple(sorted(candidate for plan in plans for candidate in plan.rejected))
    initial = frozenset(constraint for plan in plans for constraint in plan.initial_constraints)
    diagnostics = tuple(
        sorted(
            {
                *(
                    diagnostic
                    for plan in plans
                    for diagnostic in plan.diagnostics
                    if diagnostic.code not in _RECOMPUTED_DIAGNOSTICS
                ),
                *_diagnostics(actions, initial),
            }
        )
    )
    status = _status(actions, diagnostics)
    payload = {
        "actions": [action_document(action) for action in actions],
        "rejected": [rejected_document(candidate) for candidate in rejected],
        "diagnostics": [
            (diagnostic.code, diagnostic.message, diagnostic.action_id)
            for diagnostic in diagnostics
        ],
        "initial": sorted(constraint.key for constraint in initial),
    }
    identifier = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]
    return Plan(identifier, "prepared", (), actions, rejected, diagnostics, status, initial)


def _sequenced_actions(plans: tuple[Plan, ...]) -> tuple[ActionSpec, ...]:
    """Preserve command order while retaining each command's internal action graph."""

    actions: list[ActionSpec] = []
    previous_completions: frozenset[Constraint] = frozenset()
    for plan in plans:
        current: list[ActionSpec] = []
        for action in plan.actions:
            completion = Constraint(f"poly/prepared-complete:{action.id}")
            current.append(
                replace(
                    action,
                    requires=action.requires | (previous_completions - {completion}),
                    produces=action.produces | {completion},
                )
            )
        actions.extend(current)
        previous_completions |= frozenset(
            Constraint(f"poly/prepared-complete:{action.id}") for action in current
        )
    return tuple(sorted(actions, key=lambda action: action.id))


def plan_from_document(document: ReportDocument) -> Plan:
    value = document.get("plan")
    if not isinstance(value, dict):
        raise PreparedPlanError("prepared plan document has no plan")
    try:
        actions_value = value["planned_actions"]
        diagnostics_value = value["diagnostics"]
        if not isinstance(actions_value, list) or not isinstance(diagnostics_value, list):
            raise TypeError("plan collections must be lists")
        return Plan(
            id=_string(value, "id"),
            verb=_string(value, "verb"),
            selected_node_ids=tuple(_strings(value.get("selected_node_ids", []))),
            actions=tuple(_action_from_value(item) for item in actions_value),
            rejected=tuple(
                _rejected_from_value(item) for item in _list(document, "rejected_candidates")
            ),
            diagnostics=tuple(_diagnostic_from_value(item) for item in diagnostics_value),
            status=PlanStatus(_string(value, "status")),
            initial_constraints=frozenset(
                Constraint(item) for item in _strings(value.get("initial_constraints", []))
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PreparedPlanError(f"invalid prepared plan: {error}") from error


def action_document(action: ActionSpec) -> dict[str, object]:
    return {
        "id": action.id,
        "driver": action.driver,
        "verb": action.verb,
        "operation": action.operation,
        "node_ids": list(action.node_ids),
        "requested_node_ids": list(action.requested_node_ids),
        "requires": sorted(item.key for item in action.requires),
        "produces": sorted(item.key for item in action.produces),
        "claims": [
            {"operation": claim.operation, "scope": claim.scope} for claim in sorted(action.claims)
        ],
        "command": list(action.command) if action.command is not None else None,
        "environment": dict(action.environment),
        "changes_structure": action.changes_structure,
        "required_capability": action.required_capability,
    }


def rejected_document(candidate: RejectedCandidate) -> dict[str, object]:
    return {
        "driver": candidate.driver,
        "operation": candidate.operation,
        "reason": candidate.reason,
        "node_ids": list(candidate.node_ids),
        "missing": list(candidate.missing),
    }


def _action_from_value(value: object) -> ActionSpec:
    from poly.model import ActionClaim

    if not isinstance(value, dict):
        raise TypeError("planned action must be an object")
    claims = _list(value, "claims")
    environment = value.get("environment", {})
    command = value.get("command")
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in environment.items()
    ):
        raise TypeError("action environment must contain strings")
    if command is not None and not isinstance(command, list):
        raise TypeError("action command must be a list or null")
    return ActionSpec(
        _string(value, "id"),
        _string(value, "driver"),
        _string(value, "verb"),
        _string(value, "operation"),
        tuple(_strings(value.get("node_ids", []))),
        tuple(_strings(value.get("requested_node_ids", []))),
        frozenset(Constraint(item) for item in _strings(value.get("requires", []))),
        frozenset(Constraint(item) for item in _strings(value.get("produces", []))),
        frozenset(
            ActionClaim(_string(item, "operation"), _string(item, "scope"))
            for item in claims
            if isinstance(item, dict)
        ),
        tuple(_strings(command)) if command is not None else None,
        dict(environment),
        bool(value.get("changes_structure", False)),
        _string(value, "required_capability"),
    )


def _rejected_from_value(value: object) -> RejectedCandidate:
    if not isinstance(value, dict):
        raise TypeError("rejected candidate must be an object")
    return RejectedCandidate(
        _string(value, "driver"),
        _string(value, "operation"),
        _string(value, "reason"),
        tuple(_strings(value.get("node_ids", []))),
        tuple(_strings(value.get("missing", []))),
    )


def _diagnostic_from_value(value: object) -> PlanDiagnostic:
    if not isinstance(value, dict):
        raise TypeError("plan diagnostic must be an object")
    action_id = value.get("action_id")
    return PlanDiagnostic(
        _string(value, "code"),
        _string(value, "message"),
        action_id if isinstance(action_id, str) else None,
    )


def _diagnostics(
    actions: tuple[ActionSpec, ...], initial: frozenset[Constraint]
) -> tuple[PlanDiagnostic, ...]:
    diagnostics: list[PlanDiagnostic] = []
    ids: defaultdict[str, list[ActionSpec]] = defaultdict(list)
    claims: defaultdict[tuple[str, str], list[ActionSpec]] = defaultdict(list)
    producers: defaultdict[str, list[ActionSpec]] = defaultdict(list)
    for action in actions:
        ids[action.id].append(action)
        for claim in action.claims:
            claims[(claim.operation, claim.scope)].append(action)
        for produced in action.produces:
            producers[produced.key].append(action)
    for identifier, duplicates in ids.items():
        if len(duplicates) > 1:
            diagnostics.append(
                PlanDiagnostic(
                    "action.duplicate-id", f"multiple actions use id {identifier!r}", identifier
                )
            )
    for (operation, scope), candidates in claims.items():
        if len(candidates) > 1:
            drivers = ", ".join(sorted(action.driver for action in candidates))
            diagnostics.append(
                PlanDiagnostic(
                    "claim.conflict", f"{operation!r} on {scope!r} is claimed by {drivers}"
                )
            )
    available = {item.key for item in initial}
    for action in actions:
        missing = sorted(
            item.key
            for item in action.requires
            if item.key not in available and item.key not in producers
        )
        if missing:
            diagnostics.append(
                PlanDiagnostic(
                    "constraint.missing",
                    f"no planned action produces: {', '.join(missing)}",
                    action.id,
                )
            )
    graph = {
        action.id: {
            producer.id for required in action.requires for producer in producers[required.key]
        }
        for action in actions
    }
    if _contains_cycle(graph):
        diagnostics.append(
            PlanDiagnostic("constraint.cycle", "action constraints contain a dependency cycle")
        )
    return tuple(sorted(diagnostics))


def _contains_cycle(graph: dict[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(dependency) for dependency in graph[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _status(actions: tuple[ActionSpec, ...], diagnostics: tuple[PlanDiagnostic, ...]) -> PlanStatus:
    if any(
        item.code in {"action.duplicate-id", "action.wrong-verb", "claim.conflict"}
        for item in diagnostics
    ):
        return PlanStatus.CONFLICT
    if diagnostics:
        return PlanStatus.BLOCKED
    return PlanStatus.EXECUTABLE if actions else PlanStatus.EMPTY


def _string(value: Mapping[str, object], key: str) -> str:
    item = value[key]
    if not isinstance(item, str):
        raise TypeError(f"{key} must be a string")
    return item


def _strings(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError("value must be a string list")
    return value


def _string_values(value: object) -> list[str]:
    return _strings(value)


def _list(value: Mapping[str, object], key: str) -> list[object]:
    item = value.get(key, [])
    if not isinstance(item, list):
        raise TypeError(f"{key} must be a list")
    return item


def _request_values(value: object) -> list[JsonValue]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise PreparedPlanError("prepared plan requests must be an object list")
    return [cast(dict[str, JsonValue], dict(item)) for item in value]
