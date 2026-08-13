"""Application services joining inspectors, planners, and the runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from poly.driver import DriverRegistry, InspectionContext, InspectionDiagnostic
from poly.model import (
    ActionSpec,
    Inventory,
    Node,
    Plan,
    PlanningRequest,
    RejectedCandidate,
)
from poly.planning import Planner
from poly.workspace import (
    PROVISIONAL_WORKSPACE_MANIFEST,
    WORKSPACE_MANIFEST,
    compile_workspace,
    reconcile_inventory,
)


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


def inspect_workspace(
    registry: DriverRegistry, workspace: Path, *, remote: bool = False
) -> InspectionSnapshot:
    compiled = (
        compile_workspace(workspace)
        if (workspace / WORKSPACE_MANIFEST).is_file()
        or (workspace / PROVISIONAL_WORKSPACE_MANIFEST).is_file()
        else None
    )
    locked_sources = (
        {
            compiled.manifest.get(source.node_id).workspace_path: {
                "commit": source.commit,
                "url": source.url,
                "ref": source.requested_ref,
            }
            for source in compiled.lock.sources
        }
        if compiled is not None
        else {}
    )
    context = InspectionContext(
        workspace,
        {
            "poly.git.locked-sources": json.dumps(locked_sources, sort_keys=True),
            "poly.git.remote": "true" if remote else "false",
        },
    )
    nodes: list[Node] = []
    diagnostics: list[InspectionDiagnostic] = []
    for provider in registry.inspection_providers():
        result = provider.inspect(context)
        diagnostics.extend(result.diagnostics)
        nodes.extend(result.nodes)
    return InspectionSnapshot(
        workspace.resolve(),
        reconcile_inventory(compiled, tuple(nodes)),
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
        workspace=inspection.workspace,
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
