from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from poly.driver import (
    DRIVER_API_VERSION,
    ActionValue,
    DriverCapability,
    DriverExecutionResult,
    DriverManifest,
    DriverProtocolError,
    DriverRegistration,
    DriverRegistry,
    FacadeArgument,
    FacadeRequest,
    InspectionContext,
    InspectionProvider,
    InspectionResult,
    OutputReference,
    PlanningProvider,
)
from poly.driver.testkit import (
    DriverConformanceError,
    assert_inspection_side_effect_free,
    assert_manifest_compatible,
    assert_planning_deterministic,
    workspace_fingerprint,
)
from poly.model import DriverProposal, Inventory, Node, PlanningRequest

NAME = "example.driver"


@dataclass(frozen=True)
class ExampleInspector:
    name: str = NAME

    def inspect(self, context: InspectionContext) -> InspectionResult:
        return InspectionResult(self.name, (Node("root", ".", ("example/root",)),))


@dataclass(frozen=True)
class ExamplePlanner:
    name: str = NAME
    verbs: frozenset[str] = frozenset(("status",))

    def propose(self, request: PlanningRequest) -> DriverProposal:
        return DriverProposal(self.name)


@dataclass(frozen=True)
class ExampleFacade:
    name: str = "service"
    verb: str = "add"
    description: str = "add a service"
    arguments: tuple[FacadeArgument, ...] = (
        FacadeArgument("node_id", ("node_id",), required=True),
    )

    def translate(self, request: FacadeRequest) -> dict[str, str]:
        value = request.values["node_id"]
        assert isinstance(value, str)
        return {**request.parameters, "poly.node.id": value}


def manifest(api_version: str = DRIVER_API_VERSION) -> DriverManifest:
    return DriverManifest(
        name=NAME,
        version="0.1.0",
        api_version=api_version,
        capabilities=frozenset((DriverCapability.INSPECT, DriverCapability.PLAN)),
        description="fixture driver",
    )


def test_protocols_are_runtime_checkable() -> None:
    assert isinstance(ExampleInspector(), InspectionProvider)
    assert isinstance(ExamplePlanner(), PlanningProvider)


def test_manifest_round_trip_and_compatibility() -> None:
    value = manifest()
    assert_manifest_compatible(value)
    assert DriverManifest.from_dict(value.to_dict()) == value

    with pytest.raises(DriverProtocolError, match=r"requires API 2\.0"):
        manifest("2.0").ensure_compatible()
    with pytest.raises(DriverProtocolError, match=r"requires API 1\.2"):
        manifest("1.2").ensure_compatible()


@pytest.mark.parametrize("value", ("1", "one.zero", "1.0.0"))
def test_manifest_rejects_invalid_api_version(value: str) -> None:
    with pytest.raises(DriverProtocolError, match=r"<major>\.<minor>"):
        manifest(value)


def test_manifest_rejects_malformed_mapping() -> None:
    with pytest.raises(DriverProtocolError, match="invalid driver manifest"):
        DriverManifest.from_dict({"name": NAME, "version": "1", "api_version": "1.0"})


def test_registry_validates_and_orders_drivers() -> None:
    registry = DriverRegistry()
    registration = DriverRegistration(
        manifest(), inspectors=(ExampleInspector(),), planners=(ExamplePlanner(),)
    )
    registry.register(registration)

    assert registry.manifests() == (manifest(),)
    assert registry.inspection_providers() == (ExampleInspector(),)
    assert registry.planning_providers("status") == (ExamplePlanner(),)
    assert registry.planning_providers("verify") == ()

    with pytest.raises(DriverProtocolError, match="already registered"):
        registry.register(registration)
    with pytest.raises(DriverProtocolError, match="unknown driver"):
        registry.action_handler("missing")


def test_registration_rejects_capability_or_name_mismatch() -> None:
    with pytest.raises(DriverProtocolError, match="declares"):
        DriverRegistration(manifest(), inspectors=(ExampleInspector(),)).validate()

    wrong = ExampleInspector("wrong.name")
    with pytest.raises(DriverProtocolError, match="manifest name"):
        DriverRegistration(
            DriverManifest(NAME, "1", "1.0", frozenset((DriverCapability.INSPECT,))),
            inspectors=(wrong,),
        ).validate()


def test_registry_exposes_dynamic_facades_and_rejects_collisions(tmp_path: Path) -> None:
    facade = ExampleFacade()
    registration = DriverRegistration(
        DriverManifest(NAME, "1", "1.1", frozenset((DriverCapability.FACADE,))),
        facades=(facade,),
    )
    registry = DriverRegistry()
    registry.register(registration)

    assert registry.command_facades("add") == (facade,)
    assert registry.command_facades("remove") == ()
    assert registry.inventory()[0].facades == ("add:service",)
    assert facade.translate(FacadeRequest(tmp_path, {"node_id": "api"})) == {"poly.node.id": "api"}

    duplicate = DriverRegistration(
        DriverManifest("other.driver", "1", "1.1", frozenset((DriverCapability.FACADE,))),
        facades=(facade,),
    )
    with pytest.raises(DriverProtocolError, match="facade collision"):
        registry.register(duplicate)

    with pytest.raises(DriverProtocolError, match="duplicate facade"):
        DriverRegistration(registration.manifest, facades=(facade, facade)).validate()


def test_conformance_testkit_accepts_pure_deterministic_providers(tmp_path: Path) -> None:
    context = InspectionContext(tmp_path)
    assert_inspection_side_effect_free(ExampleInspector(), context)

    request = PlanningRequest(
        "status",
        Inventory((Node("root", "."),)),
        ("root",),
    )
    assert_planning_deterministic(ExamplePlanner(), request, tmp_path)

    outcome = DriverExecutionResult(True, "done", {"count": 1})
    assert outcome.details["count"] == 1
    with pytest.raises(TypeError):
        outcome.details["changed"] = True


def test_structured_execution_values_and_outputs_are_validated() -> None:
    result = DriverExecutionResult(
        True,
        "report generated",
        {"diagnostic": "retained"},
        ActionValue(82.4, "coverage"),
        (
            OutputReference("file", r"D:\test\quality.html", media_type="text/html"),
            OutputReference("url", "https://example.test/report/1", "Sonar report"),
        ),
    )

    assert result.value == ActionValue(82.4, "coverage")
    assert str(result.outputs[0].kind) == "file"
    assert result.outputs[1].label == "Sonar report"
    with pytest.raises(ValueError, match="control-free"):
        ActionValue("unsafe\x1b[31m")
    with pytest.raises(ValueError, match="credentials"):
        OutputReference("url", "https://user:secret@example.test/report")
    with pytest.raises(ValueError, match="absolute HTTP"):
        OutputReference("url", "javascript:alert(1)")
    with pytest.raises(TypeError, match="OutputReference"):
        DriverExecutionResult(True, outputs=({"kind": "file", "target": "bad"},))  # type: ignore[arg-type]


def test_conformance_testkit_detects_workspace_mutation(tmp_path: Path) -> None:
    @dataclass(frozen=True)
    class MutatingInspector:
        name: str = NAME

        def inspect(self, context: InspectionContext) -> InspectionResult:
            (context.workspace / "side-effect").write_text("changed")
            return InspectionResult(self.name)

    with pytest.raises(DriverConformanceError, match="changed the workspace"):
        assert_inspection_side_effect_free(MutatingInspector(), InspectionContext(tmp_path))

    @dataclass(frozen=True)
    class MutatingPlanner:
        name: str = NAME
        verbs: frozenset[str] = frozenset(("status",))

        def propose(self, request: PlanningRequest) -> DriverProposal:
            (tmp_path / "planned-side-effect").write_text(request.verb)
            return DriverProposal(self.name)

    request = PlanningRequest("status", Inventory((Node("root", "."),)), ("root",))
    with pytest.raises(DriverConformanceError, match="planning changed"):
        assert_planning_deterministic(MutatingPlanner(), request, tmp_path)


def test_contexts_and_fingerprint_validate_workspace(tmp_path: Path) -> None:
    before = workspace_fingerprint(tmp_path)
    (tmp_path / "file").write_text("content")
    assert workspace_fingerprint(tmp_path) != before

    with pytest.raises(ValueError, match="does not exist"):
        InspectionContext(tmp_path / "missing")
