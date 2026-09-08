"""Application services joining inspectors, planners, and the runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from poly.driver import (
    ContributionInventoryItem,
    DriverInventoryItem,
    DriverRegistry,
    InspectionContext,
    InspectionDiagnostic,
    PluginInventoryItem,
)
from poly.inspection_cache import fingerprint as inspection_fingerprint
from poly.inspection_cache import load as load_inspection_cache
from poly.inspection_cache import save as save_inspection_cache
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
    drivers: tuple[DriverInventoryItem, ...] = ()
    plugins: tuple[PluginInventoryItem, ...] = ()
    contributions: tuple[ContributionInventoryItem, ...] = ()
    cache_state: str = "cold"
    elapsed_ms: int = 0


@dataclass(frozen=True, slots=True)
class PlanningSnapshot:
    inspection: InspectionSnapshot
    request: PlanningRequest
    applicable_actions: tuple[ActionSpec, ...]
    rejected: tuple[RejectedCandidate, ...]
    plan: Plan


def inspect_workspace(
    registry: DriverRegistry, workspace: Path, *, remote: bool = False, refresh: bool = False
) -> InspectionSnapshot:
    started = perf_counter()
    resolved_workspace = workspace.resolve()
    drivers = registry.inventory()
    plugins = registry.plugin_inventory()
    contributions = registry.contribution_inventory()
    cache_enabled = (resolved_workspace / ".poly").is_dir()
    source_fingerprint = (
        inspection_fingerprint(resolved_workspace, drivers, remote=remote)
        if cache_enabled
        else None
    )
    if not refresh and source_fingerprint is not None:
        cached = load_inspection_cache(resolved_workspace, source_fingerprint)
        if cached is not None:
            inventory, cached_diagnostics = cached
            return InspectionSnapshot(
                resolved_workspace,
                inventory,
                cached_diagnostics,
                available_verbs(registry),
                drivers,
                plugins,
                contributions,
                "hit",
                _elapsed_ms(started),
            )
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
        resolved_workspace,
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
    snapshot = InspectionSnapshot(
        resolved_workspace,
        reconcile_inventory(compiled, tuple(nodes)),
        tuple(sorted(diagnostics)),
        available_verbs(registry),
        drivers,
        plugins,
        contributions,
        "refresh" if refresh else "cold",
        _elapsed_ms(started),
    )
    if source_fingerprint is not None:
        save_inspection_cache(
            resolved_workspace, source_fingerprint, snapshot.inventory, snapshot.diagnostics
        )
    return snapshot


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


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
