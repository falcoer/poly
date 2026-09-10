"""Technology-neutral hydration inspections and finite workspace consolidation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

from poly.driver import (
    DRIVER_API_VERSION,
    WORKSPACE_COHERENT,
    DriverCapability,
    DriverExecutionResult,
    DriverManifest,
    DriverRegistration,
    DriverRegistry,
    ExecutionContext,
    InspectionContext,
    source_available,
)
from poly.driver.hydration import inventory_value, read_inventory
from poly.model import ActionSpec, Constraint, DriverProposal, Inventory, Node, PlanningRequest
from poly.workspace import reconcile_inventory, validate_workspace

HYDRATION_DRIVER = "poly.hydration"


def _inspection_id(source: str, provider: str) -> str:
    return f"inspect:{source}:{provider}"


def _artifact(run: Path, action_id: str) -> Path:
    digest = hashlib.sha256(action_id.encode()).hexdigest()
    return run / "hydration" / "observations" / f"{digest}.json"


@dataclass(frozen=True, slots=True)
class HydrationPlanningProvider:
    registry: DriverRegistry
    name: str = HYDRATION_DRIVER
    verbs: frozenset[str] = frozenset(("hydrate",))

    def propose(self, request: PlanningRequest) -> DriverProposal:
        if not any(
            node.metadata.get("poly.kind") == "workspace" for node in request.inventory.nodes
        ):
            return DriverProposal(self.name)
        selection = request.inventory.select(request.selected_node_ids)
        scope = (
            request.inventory.nodes
            if any(node.metadata.get("poly.kind") == "configuration" for node in selection)
            else selection
        )
        sources = tuple(
            node
            for node in scope
            if node.path is not None
            and node.metadata.get("poly.kind") in {"workspace", "repository", "module"}
        )
        source_ids = {source.id for source in sources}
        actions: list[ActionSpec] = []
        expected: list[str] = []
        for source in sources:
            if not source.metadata.get("poly.source.driver"):
                actions.append(
                    ActionSpec(
                        f"available:{source.id}",
                        self.name,
                        "hydrate",
                        "poly/source/check",
                        (source.id,),
                        requires=frozenset((source_available(str(source.metadata["poly.parent"])),))
                        if source.metadata.get("poly.parent") in source_ids
                        else frozenset(),
                        produces=frozenset((source_available(source.id),)),
                        environment={"path": source.require_path()},
                        concurrency_safe=True,
                        required_capability="driver.execute",
                    )
                )
            for provider in self.registry.source_inspection_providers():
                identity = _inspection_id(source.id, provider.name)
                expected.append(identity)
                actions.append(
                    ActionSpec(
                        identity,
                        self.name,
                        "hydrate",
                        "poly/source/inspect",
                        (source.id,),
                        requires=frozenset((source_available(source.id),)),
                        produces=frozenset((Constraint(identity),)),
                        environment={"provider": provider.name, "source": source.id},
                        concurrency_safe=True,
                        required_capability="driver.execute",
                    )
                )
        actions.append(
            ActionSpec(
                "workspace.coherence",
                self.name,
                "hydrate",
                "poly/workspace/coherence",
                (),
                requires=frozenset(
                    (
                        *[source_available(source.id) for source in sources],
                        *[Constraint(identity) for identity in expected],
                    )
                ),
                produces=frozenset((WORKSPACE_COHERENT,)),
                environment={
                    "expected": json.dumps(expected),
                    "sources": json.dumps([source.id for source in sources]),
                    "manifest": validate_workspace(request.workspace).manifest.digest
                    if request.workspace is not None
                    else "",
                },
                required_capability="driver.execute",
            )
        )
        return DriverProposal(self.name, tuple(actions))


@dataclass(frozen=True, slots=True)
class HydrationActionHandler:
    registry: DriverRegistry
    name: str = HYDRATION_DRIVER

    def execute(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        try:
            if action.operation == "poly/source/check":
                path = (context.workspace / action.environment["path"]).resolve()
                if not path.is_relative_to(context.workspace) or not path.is_dir():
                    return DriverExecutionResult(False, f"source directory unavailable: {path}")
                return DriverExecutionResult(True, "source directory available")
            compiled = validate_workspace(context.workspace)
            if action.operation == "poly/source/inspect":
                source = compiled.inventory.get(action.environment["source"])
                providers = [
                    provider
                    for provider in self.registry.source_inspection_providers()
                    if provider.name == action.environment["provider"]
                ]
                if len(providers) != 1:
                    return DriverExecutionResult(False, "source inspection provider unavailable")
                result = providers[0].inspect(InspectionContext(context.workspace, source=source))
                if result.diagnostics:
                    return DriverExecutionResult(
                        False,
                        "; ".join(f"{item.code}: {item.message}" for item in result.diagnostics),
                    )
                nodes = tuple(
                    replace(
                        node,
                        nature_origins={
                            nature: (f"observed:{providers[0].name}",) for nature in node.natures
                        },
                    )
                    for node in result.nodes
                )
                path = _artifact(context.run_directory, action.id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(inventory_value(Inventory(nodes)), sort_keys=True), encoding="utf-8"
                )
                return DriverExecutionResult(
                    True, f"inspected {source.id}", {"observed_nodes": len(nodes)}
                )
            if action.operation == "poly/workspace/coherence":
                if compiled.manifest.digest != action.environment["manifest"]:
                    return DriverExecutionResult(
                        False, "workspace declaration changed after planning"
                    )
                observed: list[Node] = []
                for identity in json.loads(action.environment["expected"]):
                    observed.extend(
                        read_inventory(_artifact(context.run_directory, identity)).nodes
                    )
                inventory = reconcile_inventory(compiled, tuple(observed))
                for node in inventory.nodes:
                    if node.metadata.get("poly.kind") == "configuration":
                        schema = str(node.configuration.get("schema", ""))
                        self.registry.contributions.configuration_schema(schema).validate(
                            dict(node.configuration)
                        )
                path = context.run_directory / "hydration" / "inventory.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(inventory_value(inventory), sort_keys=True), encoding="utf-8"
                )
                return DriverExecutionResult(True, "workspace inventory consolidated")
            return DriverExecutionResult(
                False, f"unsupported hydration operation: {action.operation}"
            )
        except (OSError, ValueError, KeyError, TypeError) as error:
            return DriverExecutionResult(False, str(error))


def hydration_driver(registry: DriverRegistry) -> DriverRegistration:
    return DriverRegistration(
        DriverManifest(
            HYDRATION_DRIVER,
            "0.1.0",
            DRIVER_API_VERSION,
            frozenset((DriverCapability.PLAN, DriverCapability.EXECUTE)),
            "Source inspection and workspace coherence",
        ),
        planners=(HydrationPlanningProvider(registry),),
        handlers=(HydrationActionHandler(registry),),
    )
