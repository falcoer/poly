"""Finite, deterministic plan negotiation."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable

from poly.driver.api import PlanningProvider
from poly.model import (
    ActionSpec,
    DriverProposal,
    Plan,
    PlanDiagnostic,
    PlanningRequest,
    PlanStatus,
)


class Planner:
    """Aggregate providers for one verb and freeze a closed action plan."""

    def __init__(self, providers: Iterable[PlanningProvider]) -> None:
        self._providers = tuple(sorted(providers, key=lambda provider: provider.name))

    def negotiate(self, request: PlanningRequest) -> Plan:
        return self.negotiate_proposals(request, self.propose(request))

    def propose(self, request: PlanningRequest) -> tuple[DriverProposal, ...]:
        return tuple(
            provider.propose(request)
            for provider in self._providers
            if request.verb in provider.verbs
        )

    def negotiate_proposals(
        self, request: PlanningRequest, proposals: tuple[DriverProposal, ...]
    ) -> Plan:
        actions = tuple(
            sorted((action for p in proposals for action in p.actions), key=lambda a: a.id)
        )
        rejected = tuple(sorted(candidate for p in proposals for candidate in p.rejected))
        diagnostics = self._diagnose(request, actions)
        status = self._status(actions, diagnostics)
        plan_id = self._fingerprint(request, actions, rejected, diagnostics)
        return Plan(
            id=plan_id,
            verb=request.verb,
            selected_node_ids=request.selected_node_ids,
            actions=actions,
            rejected=rejected,
            diagnostics=diagnostics,
            status=status,
            initial_constraints=request.initial_constraints,
        )

    @staticmethod
    def _diagnose(
        request: PlanningRequest, actions: tuple[ActionSpec, ...]
    ) -> tuple[PlanDiagnostic, ...]:
        diagnostics: list[PlanDiagnostic] = []
        ids: defaultdict[str, list[ActionSpec]] = defaultdict(list)
        claims: defaultdict[tuple[str, str], list[ActionSpec]] = defaultdict(list)
        producers: defaultdict[str, list[ActionSpec]] = defaultdict(list)

        for action in actions:
            ids[action.id].append(action)
            if action.verb != request.verb:
                diagnostics.append(
                    PlanDiagnostic(
                        code="action.wrong-verb",
                        message=(
                            f"{action.driver} proposed verb {action.verb!r} while "
                            f"negotiating {request.verb!r}"
                        ),
                        action_id=action.id,
                    )
                )
            unknown_nodes = sorted(
                set(action.node_ids) - {node.id for node in request.inventory.nodes}
            )
            if unknown_nodes:
                diagnostics.append(
                    PlanDiagnostic(
                        code="action.unknown-node",
                        message=f"action covers unknown nodes: {', '.join(unknown_nodes)}",
                        action_id=action.id,
                    )
                )
            outside_selection = sorted(
                set(action.requested_node_ids) - set(request.selected_node_ids)
            )
            if outside_selection:
                diagnostics.append(
                    PlanDiagnostic(
                        code="action.outside-selection",
                        message=(
                            "action marks unselected nodes as requested: "
                            f"{', '.join(outside_selection)}"
                        ),
                        action_id=action.id,
                    )
                )
            for claim in action.claims:
                claims[(claim.operation, claim.scope)].append(action)
            for constraint in action.produces:
                producers[constraint.key].append(action)

        for action_id, duplicates in ids.items():
            if len(duplicates) > 1:
                diagnostics.append(
                    PlanDiagnostic(
                        code="action.duplicate-id",
                        message=f"multiple actions use id {action_id!r}",
                        action_id=action_id,
                    )
                )

        for (operation, scope), candidates in claims.items():
            if len(candidates) > 1:
                names = ", ".join(sorted(action.driver for action in candidates))
                diagnostics.append(
                    PlanDiagnostic(
                        code="claim.conflict",
                        message=f"{operation!r} on {scope!r} is claimed by {names}",
                    )
                )

        initial = {constraint.key for constraint in request.initial_constraints}
        for action in actions:
            missing = sorted(
                constraint.key
                for constraint in action.requires
                if constraint.key not in initial and constraint.key not in producers
            )
            if missing:
                diagnostics.append(
                    PlanDiagnostic(
                        code="constraint.missing",
                        message=f"no planned action produces: {', '.join(missing)}",
                        action_id=action.id,
                    )
                )

        graph: dict[str, set[str]] = {action.id: set() for action in actions}
        for consumer in actions:
            for constraint in consumer.requires:
                graph[consumer.id].update(producer.id for producer in producers[constraint.key])
        if _contains_cycle(graph):
            diagnostics.append(
                PlanDiagnostic(
                    code="constraint.cycle",
                    message="action constraints contain a dependency cycle",
                )
            )

        return tuple(sorted(diagnostics))

    @staticmethod
    def _status(
        actions: tuple[ActionSpec, ...], diagnostics: tuple[PlanDiagnostic, ...]
    ) -> PlanStatus:
        if any(
            diagnostic.code in {"action.duplicate-id", "action.wrong-verb", "claim.conflict"}
            for diagnostic in diagnostics
        ):
            return PlanStatus.CONFLICT
        if diagnostics:
            return PlanStatus.BLOCKED
        if not actions:
            return PlanStatus.EMPTY
        return PlanStatus.EXECUTABLE

    @staticmethod
    def _fingerprint(
        request: PlanningRequest,
        actions: tuple[ActionSpec, ...],
        rejected: tuple[object, ...],
        diagnostics: tuple[PlanDiagnostic, ...],
    ) -> str:
        payload = {
            "verb": request.verb,
            "selection": request.selected_node_ids,
            "parameters": dict(request.parameters),
            "initial": sorted(constraint.key for constraint in request.initial_constraints),
            "actions": [_action_payload(action) for action in actions],
            "rejected": [repr(candidate) for candidate in rejected],
            "diagnostics": [
                (diagnostic.code, diagnostic.message, diagnostic.action_id)
                for diagnostic in diagnostics
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()[:20]


def _action_payload(action: ActionSpec) -> dict[str, object]:
    return {
        "id": action.id,
        "driver": action.driver,
        "verb": action.verb,
        "operation": action.operation,
        "nodes": action.node_ids,
        "requested_nodes": action.requested_node_ids,
        "requires": sorted(constraint.key for constraint in action.requires),
        "produces": sorted(constraint.key for constraint in action.produces),
        "claims": sorted((claim.operation, claim.scope) for claim in action.claims),
        "command": action.command,
        "environment": dict(action.environment),
        "changes_structure": action.changes_structure,
        "required_capability": action.required_capability,
    }


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
