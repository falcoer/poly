"""External contract fixture, deliberately not a production Eclipse driver."""

from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree

from poly.driver import (
    BlueprintDefinition,
    BlueprintParameter,
    ContributionDescriptor,
    DriverCapability,
    DriverManifest,
    DriverRegistration,
    FacadeArgument,
    FacadeRequest,
    Plugin,
    PluginRegistration,
)
from poly.model import ActionSpec, DriverProposal, PlanningRequest, RejectedCandidate


class EclipseFacade:
    name = "eclipse-fixture"
    verb = "configure"
    description = "Normalize an Eclipse configuration request"
    arguments = (FacadeArgument("name", ("name",), required=True),)

    def translate(self, request: FacadeRequest) -> dict[str, str]:
        value = request.values["name"]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("project name must be a non-empty string")
        return {"project_name": value.strip()}


class EclipseDriver:
    name = "fixture.eclipse"
    verbs = frozenset(("configure",))

    def propose(self, request: PlanningRequest) -> DriverProposal:
        # Another configure provider can handle other tools without a rejection.
        if request.parameters.get("tool") != "eclipse":
            return DriverProposal(self.name)
        actions = []
        rejected = []
        for node in request.inventory.select(request.selected_node_ids):
            if "java/project" not in node.natures:
                rejected.append(
                    RejectedCandidate(
                        self.name,
                        request.verb,
                        "Eclipse fixture requires a Java project",
                        (node.id,),
                        ("nature:java/project",),
                    )
                )
                continue
            template = Path(__file__).parent / "resources" / "project.xml"
            project = ElementTree.fromstring(template.read_text(encoding="utf-8"))
            name = project.find("name")
            assert name is not None
            name.text = request.parameters["project.name"]
            content = ElementTree.tostring(project, encoding="unicode")
            # Freeze the generated content in an ordinary process action.
            # Exclusive creation is intentional: lifecycle/merge policy is 0.13.2.
            script = (
                "from pathlib import Path; "
                "p=Path('.project'); "
                f"p.open('x', encoding='utf-8').write({content!r})"
            )
            actions.append(
                ActionSpec(
                    f"eclipse:{node.id}",
                    self.name,
                    request.verb,
                    "fixture/eclipse",
                    (node.id,),
                    working_directory=node.path,
                    command=(sys.executable, "-c", script),
                )
            )
        return DriverProposal(self.name, tuple(actions), tuple(rejected))


def plugin() -> PluginRegistration:
    driver = EclipseDriver()
    return PluginRegistration(
        Plugin(
            "fixture.eclipse.plugin",
            "1.0.0",
            "1.1",
            (
                ContributionDescriptor("driver:fixture.eclipse", "driver"),
                ContributionDescriptor("facade:configure:eclipse-fixture", "facade"),
                ContributionDescriptor("blueprint:eclipse-java", "blueprint"),
            ),
            resources=("resources/project.xml",),
        ),
        drivers=(
            DriverRegistration(
                DriverManifest(driver.name, "1.0.0", "1.1", frozenset((DriverCapability.PLAN,))),
                planners=(driver,),
            ),
        ),
        facades=(EclipseFacade(),),
        blueprints=(
            BlueprintDefinition(
                "eclipse-java",
                "Minimal Eclipse Java configuration",
                "1.0.0",
                parameters=(BlueprintParameter("project_name"),),
                configuration={"tool": "eclipse"},
                bindings={"project.name": "project_name"},
                resources=("resources/project.xml",),
                required_contributions=("driver:fixture.eclipse",),
            ),
        ),
    )
