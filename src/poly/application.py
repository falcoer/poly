"""Application services joining inspectors, planners, and the runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from poly.driver import DriverRegistry, InspectionContext, InspectionDiagnostic
from poly.model import (
    ActionSpec,
    Inventory,
    Plan,
    PlanningRequest,
    RejectedCandidate,
)
from poly.planning import Planner


@dataclass(frozen=True, slots=True)
class InspectionSnapshot:
    workspace: Path
    inventory: Inventory
    diagnostics: tuple[InspectionDiagnostic, ...]
    available_verbs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanningSnapshot:
    inspection: InspectionSnapshot
    request: PlanningRequest
    applicable_actions: tuple[ActionSpec, ...]
    rejected: tuple[RejectedCandidate, ...]
    plan: Plan


def inspect_workspace(registry: DriverRegistry, workspace: Path) -> InspectionSnapshot:
    context = InspectionContext(workspace)
    nodes = []
    diagnostics: list[InspectionDiagnostic] = []
    known_ids: set[str] = set()
    for provider in registry.inspection_providers():
        result = provider.inspect(context)
        diagnostics.extend(result.diagnostics)
        for node in result.nodes:
            if node.id in known_ids:
                diagnostics.append(
                    InspectionDiagnostic(
                        "inventory.node.duplicate",
                        f"multiple inspectors produced node {node.id!r}",
                        node.path,
                    )
                )
                continue
            known_ids.add(node.id)
            nodes.append(node)
    return InspectionSnapshot(
        workspace.resolve(),
        Inventory(tuple(nodes)),
        tuple(sorted(diagnostics)),
        available_verbs(registry),
    )


def prepare_planning(
    registry: DriverRegistry,
    inspection: InspectionSnapshot,
    verb: str,
    selected_node_ids: tuple[str, ...],
    parameters: dict[str, str] | None = None,
) -> PlanningSnapshot:
    request = PlanningRequest(
        verb,
        inspection.inventory,
        selected_node_ids,
        parameters or {},
    )
    planner = Planner(registry.planning_providers(verb))
    proposals = planner.propose(request)
    actions = tuple(
        sorted(
            (action for proposal in proposals for action in proposal.actions), key=lambda a: a.id
        )
    )
    rejected = tuple(sorted(candidate for proposal in proposals for candidate in proposal.rejected))
    return PlanningSnapshot(
        inspection,
        request,
        actions,
        rejected,
        planner.negotiate_proposals(request, proposals),
    )


def available_verbs(registry: DriverRegistry) -> tuple[str, ...]:
    return tuple(
        sorted({verb for provider in registry.planning_providers() for verb in provider.verbs})
    )
