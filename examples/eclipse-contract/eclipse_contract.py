"""External hydration contract fixture; this does not launch or import into Eclipse."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

from poly.driver import (
    DRIVER_API_VERSION,
    POLY_EXTENSION_API_VERSION,
    WORKSPACE_COHERENT,
    BlueprintDefinition,
    BlueprintParameter,
    ConfigurationAddFacade,
    ConfigurationSchema,
    ContributionDescriptor,
    DriverCapability,
    DriverExecutionResult,
    DriverManifest,
    DriverRegistration,
    ExecutionContext,
    OutputReference,
    Plugin,
    PluginRegistration,
    hydration_inventory,
)
from poly.model import ActionClaim, ActionSpec, DriverProposal, PlanningRequest

SCHEMA = ConfigurationSchema(
    "fixture.eclipse/workspace/v1",
    {
        "type": "object",
        "additionalProperties": False,
        "properties": {"name": {"type": "string", "minLength": 1}},
        "required": ["name"],
    },
)


class EclipseDriver:
    name = "fixture.eclipse"
    verbs = frozenset(("hydrate",))

    def propose(self, request: PlanningRequest) -> DriverProposal:
        actions = []
        for node in request.inventory.select(request.selected_node_ids):
            if node.configuration.get("schema") != SCHEMA.identity:
                continue
            SCHEMA.validate(dict(node.configuration))
            actions.append(
                ActionSpec(
                    f"fixture.eclipse:{node.id}",
                    self.name,
                    "hydrate",
                    "fixture/eclipse-request",
                    (node.id,),
                    requested_node_ids=(node.id,),
                    requires=frozenset((WORKSPACE_COHERENT,)),
                    claims=frozenset((ActionClaim("file/write", f"projection:{node.id}"),)),
                    environment={
                        "configuration": json.dumps(dict(node.configuration), sort_keys=True)
                    },
                    required_capability="driver.execute",
                )
            )
        return DriverProposal(self.name, tuple(actions))

    def execute(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        inventory = hydration_inventory(context)
        node = inventory.get(action.node_ids[0])
        if (
            json.dumps(dict(node.configuration), sort_keys=True)
            != action.environment["configuration"]
        ):
            return DriverExecutionResult(False, "configuration changed after planning")
        template = Path(__file__).parent / "resources" / "request.xml"
        request = ElementTree.fromstring(template.read_text(encoding="utf-8"))
        values = node.configuration["values"]
        assert isinstance(values, dict)
        request.set("name", str(values["name"]))
        for source in inventory.nodes:
            if source.path is not None:
                ElementTree.SubElement(
                    request,
                    "source",
                    {
                        "id": source.id,
                        "path": source.path,
                        "natures": ",".join(source.natures),
                    },
                )
        output = context.workspace / ".poly" / "projections" / node.id / "request.xml"
        content = ElementTree.tostring(request, encoding="utf-8", xml_declaration=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and output.read_bytes() != content:
            return DriverExecutionResult(
                False, "existing fixture output differs; review before replacement"
            )
        if not output.exists():
            with output.open("xb") as stream:
                stream.write(content)
        return DriverExecutionResult(
            True,
            "generated fixture request; no Eclipse import performed",
            outputs=(OutputReference("file", str(output), "Fixture import request"),),
        )


def plugin() -> PluginRegistration:
    driver = EclipseDriver()
    return PluginRegistration(
        Plugin(
            "fixture.eclipse.plugin",
            "2.0.0",
            POLY_EXTENSION_API_VERSION,
            (
                ContributionDescriptor("driver:fixture.eclipse", "driver"),
                ContributionDescriptor("facade:add:eclipse-configuration", "facade"),
                ContributionDescriptor("blueprint:eclipse-workspace", "blueprint"),
            ),
            resources=("resources/request.xml",),
        ),
        drivers=(
            DriverRegistration(
                DriverManifest(
                    driver.name,
                    "2.0.0",
                    DRIVER_API_VERSION,
                    frozenset((DriverCapability.PLAN, DriverCapability.EXECUTE)),
                ),
                planners=(driver,),
                handlers=(driver,),
                configuration_schemas=(SCHEMA,),
            ),
        ),
        facades=(
            ConfigurationAddFacade(
                "eclipse-configuration",
                "fixture/eclipse-configuration",
                SCHEMA,
                {"name": "Workspace"},
            ),
        ),
        blueprints=(
            BlueprintDefinition(
                "eclipse-workspace",
                "Minimal workspace declaration values",
                "1.0.0",
                parameters=(BlueprintParameter("project_name"),),
                bindings={"name": "project_name"},
                resources=("resources/request.xml",),
                required_contributions=("driver:fixture.eclipse",),
            ),
        ),
    )
