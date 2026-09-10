from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from poly.application import inspect_workspace, prepare_planning
from poly.cli import build_registry
from poly.driver import (
    WORKSPACE_COHERENT,
    ConfigurationAddFacade,
    ConfigurationError,
    ConfigurationSchema,
    DriverRegistration,
    DriverRegistry,
    ExecutionContext,
    ExtensionProtocolError,
    FacadeArgumentValue,
    FacadeRequest,
    InspectionContext,
    hydration_inventory,
    load_plugin_entrypoint,
    source_available,
)
from poly.drivers.maven import MavenInspectionProvider, MavenModelError
from poly.hydration import HydrationActionHandler
from poly.model import ActionSpec, Metadata, Node, PlanStatus
from poly.runtime import Executor, LocalActionRunner, RunStatus
from poly.workspace import (
    LockedSource,
    SourceDeclaration,
    WorkspaceError,
    add_manifest_node,
    create_workspace_files,
    reconcile_inventory,
    set_manifest_node_natures,
    validate_manifest_value,
    validate_workspace,
)


def _registry(monkeypatch: pytest.MonkeyPatch) -> DriverRegistry:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "examples/eclipse-contract")
    )
    registry = build_registry()
    registry.register_plugin(load_plugin_entrypoint("eclipse_contract:plugin"))
    return registry


def _declare(directory: Path, registry: DriverRegistry) -> None:
    create_workspace_files(directory, "demo", "Demo")
    schema = registry.contributions.configuration_schema("fixture.eclipse/workspace/v1")
    add_manifest_node(
        directory,
        node_id="ide",
        parent="root",
        kind="configuration",
        path=None,
        natures=("fixture/eclipse-configuration",),
        configuration={"schema": schema.identity, "values": {"name": "Demo"}},
    )


def _git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(directory), *args), check=True, capture_output=True, text=True
    ).stdout.strip()


def _source(directory: Path) -> str:
    directory.mkdir()
    _git(directory, "init", "--quiet")
    _git(directory, "config", "user.email", "test@example.test")
    _git(directory, "config", "user.name", "Test")
    (directory / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion><groupId>test</groupId>"
        "<artifactId>demo</artifactId><version>1</version><packaging>pom</packaging>"
        "<modules><module>service</module></modules></project>",
        encoding="utf-8",
    )
    (directory / "service").mkdir()
    (directory / "service/pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion><groupId>test</groupId>"
        "<artifactId>service</artifactId><version>1</version><packaging>war</packaging></project>",
        encoding="utf-8",
    )
    _git(directory, "add", ".")
    _git(directory, "commit", "--quiet", "-m", "source")
    return _git(directory, "rev-parse", "HEAD")


def test_checkout_then_inspection_then_projection_converges_on_two_workspaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(monkeypatch)
    remote = tmp_path / "remote"
    commit = _source(remote)
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _declare(first, registry)
    add_manifest_node(
        first,
        node_id="code",
        parent="root",
        kind="repository",
        path="sources/code",
        natures=("maven/project", "custom/manual"),
        source=SourceDeclaration("git", remote.as_uri()),
        locked_source=LockedSource("code", "git", remote.as_uri(), None, commit, "commit"),
    )
    add_manifest_node(
        first,
        node_id="reactor",
        parent="code",
        kind="module",
        path=".",
        natures=("custom/reactor",),
    )
    _git(first, "init", "--quiet")
    _git(first, "config", "user.email", "test@example.test")
    _git(first, "config", "user.name", "Test")
    _git(first, "add", "poly.yaml", "poly.lock.yaml", ".gitignore")
    _git(first, "commit", "--quiet", "-m", "shared declaration")
    subprocess.run(("git", "clone", "--quiet", str(first), str(second)), check=True)
    inventories = []
    for directory in (first, second):
        inspection = inspect_workspace(registry, directory, declared_only=True)
        assert inspection.cache_state == "declaration"
        assert not (directory / "sources/code").exists()
        selected = tuple(node.id for node in inspection.inventory.nodes)
        plan = prepare_planning(registry, inspection, "hydrate", selected).plan
        assert plan.status is PlanStatus.EXECUTABLE
        coherence = next(action for action in plan.actions if action.id == "workspace.coherence")
        assert source_available("code") in coherence.requires
        assert WORKSPACE_COHERENT in coherence.produces
        assert any(action.id == "inspect:code:poly.driver.maven" for action in plan.actions)
        frozen_ids = tuple(action.id for action in plan.actions)
        context = ExecutionContext(directory, directory / ".poly/runs/hydrate")
        result = Executor(LocalActionRunner(registry=registry), jobs=4).execute(plan, context)
        assert result.status is RunStatus.SUCCEEDED, result
        assert tuple(action.action_id for action in result.actions) == frozen_ids
        inventory = hydration_inventory(context)
        inventories.append(inventory)
        code = inventory.get("code")
        assert code.nature_origins["custom/manual"] == ("declared",)
        assert code.nature_origins["maven/project"] == ("declared",)
        assert inventory.get("reactor").nature_origins["maven/project"] == (
            "observed:poly.driver.maven",
        )
        assert any(node.metadata.get("maven.packaging") == "war" for node in inventory.nodes)
        assert len(inventory.nodes) > len(inspection.inventory.nodes)
        assert (directory / ".poly/projections/ide/request.xml").is_file()
        assert _git(directory / "sources/code", "rev-parse", "HEAD") == commit
    assert (first / ".poly/projections/ide/request.xml").read_bytes() == (
        second / ".poly/projections/ide/request.xml"
    ).read_bytes()
    # Root Git origin differs by onboarding route; functional projections agree.
    assert [
        (node.id, node.path, node.natures, node.configuration, node.nature_origins)
        for node in inventories[0].nodes
    ] == [
        (node.id, node.path, node.natures, node.configuration, node.nature_origins)
        for node in inventories[1].nodes
    ]


def test_projection_only_plan_cannot_ignore_unavailable_declared_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(monkeypatch)
    _declare(tmp_path, registry)
    add_manifest_node(
        tmp_path,
        node_id="code",
        parent="root",
        kind="repository",
        path="code",
        source=SourceDeclaration("git", "missing"),
        locked_source=LockedSource("code", "git", "missing", None, "a" * 40, "commit"),
    )
    inspection = inspect_workspace(registry, tmp_path, declared_only=True)
    plan = prepare_planning(registry, inspection, "hydrate", ("ide",)).plan
    assert plan.status is PlanStatus.BLOCKED
    assert any("poly/source-available:code" in item.message for item in plan.diagnostics)
    full = prepare_planning(registry, inspection, "hydrate", ("root", "code", "ide")).plan
    result = Executor(LocalActionRunner(registry=registry), jobs=2).execute(
        full, ExecutionContext(tmp_path, tmp_path / ".poly/runs/failure")
    )
    assert result.status is not RunStatus.SUCCEEDED
    assert WORKSPACE_COHERENT.key not in result.available_constraints
    assert not (tmp_path / ".poly/projections/ide/request.xml").exists()


def test_configuration_manifest_and_provenance_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(monkeypatch)
    _declare(tmp_path, registry)
    compiled = validate_workspace(tmp_path)
    node = compiled.inventory.get("ide")
    assert node.path is None
    assert "path" not in compiled.manifest.get("ide").semantic()
    with pytest.raises(ValueError, match="no filesystem path"):
        node.require_path()
    invalid_values: tuple[Metadata, ...] = ({"path": "."}, {"configuration": [1]})
    for invalid in invalid_values:
        value = compiled.manifest.semantic()
        nodes = value["nodes"]
        assert isinstance(nodes, list)
        config = next(item for item in nodes if isinstance(item, dict) and item["id"] == "ide")
        assert isinstance(config, dict)
        config.update(invalid)
        with pytest.raises(WorkspaceError):
            validate_manifest_value(tmp_path, value)
    set_manifest_node_natures(tmp_path, "ide", ("manual",), add=True)
    observed = Node(
        "ide",
        None,
        ("manual", "detected"),
        nature_origins={"manual": ("observed:probe",), "detected": ("observed:probe",)},
    )
    updated = validate_workspace(tmp_path)
    merged = reconcile_inventory(updated, (observed,)).get("ide")
    assert merged.nature_origins["manual"] == ("declared", "observed:probe")
    assert "manual" in reconcile_inventory(updated, ()).get("ide").natures
    assert "detected" not in reconcile_inventory(updated, ()).get("ide").natures
    with pytest.raises(ValueError, match="provenance"):
        replace(node, nature_origins={"absent": ("declared",)})


def test_configuration_schema_validates_offline_and_reports_value_path(tmp_path: Path) -> None:
    schema = ConfigurationSchema(
        "test/v1",
        {
            "type": "object",
            "properties": {"count": {"type": "integer", "minimum": 1}},
            "required": ["count"],
            "additionalProperties": False,
        },
    )
    valid: Metadata = {"schema": "test/v1", "values": {"count": 1}}
    schema.validate(valid)
    with pytest.raises(ConfigurationError, match="values/count"):
        schema.validate({"schema": "test/v1", "values": {"count": 0}})
    with pytest.raises(ConfigurationError, match="exactly"):
        schema.validate({"values": {}})
    with pytest.raises(ConfigurationError, match="expected"):
        schema.validate({"schema": "other", "values": {}})
    with pytest.raises(ConfigurationError, match="whitespace"):
        ConfigurationSchema("bad name", {})
    with pytest.raises(ConfigurationError, match="local"):
        ConfigurationSchema("bad/v1", {"allOf": [{"$ref": "https://example.invalid/schema"}]})
    facade = ConfigurationAddFacade("test-config", "test/config", schema, {"count": 1})
    result = facade.translate(FacadeRequest(tmp_path, {"node_id": "settings", "parent": "root"}))
    assert json.loads(result["poly.node.configuration"]) == valid
    assert result["poly.node.parent"] == "root"
    invalid_arguments: tuple[dict[str, FacadeArgumentValue], ...] = (
        {"node_id": None},
        {"node_id": "x", "configuration_file": "absent"},
    )
    for values in invalid_arguments:
        with pytest.raises(ConfigurationError):
            facade.translate(FacadeRequest(tmp_path, values))


def test_unknown_or_invalid_configurations_block_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(monkeypatch)
    _declare(tmp_path, registry)
    inspection = inspect_workspace(registry, tmp_path, declared_only=True)
    for configuration in (
        "[]",
        '{"schema":"missing","values":{}}',
        '{"schema":"fixture.eclipse/workspace/v1","values":{}}',
    ):
        plan = prepare_planning(
            registry,
            inspection,
            "add",
            (),
            {
                "poly.node.kind": "configuration",
                "poly.node.id": "bad",
                "poly.node.configuration": configuration,
            },
        ).plan
        assert plan.status is PlanStatus.BLOCKED
        assert any(item.code == "configuration.invalid" for item in plan.diagnostics)
    original = registry.contributions.driver_registration("fixture.eclipse")
    with pytest.raises(ValueError, match="duplicate configuration schema"):
        replace(original, configuration_schemas=original.configuration_schemas * 2).validate()
    with pytest.raises((ExtensionProtocolError, ValueError), match="configuration-schema"):
        registry.register(
            DriverRegistration(
                replace(original.manifest, name="other", capabilities=frozenset()),
                configuration_schemas=original.configuration_schemas,
            )
        )


def test_source_scan_follows_descriptors_without_a_deep_tree_walk(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project><artifactId>root</artifactId></project>")
    buried = tmp_path / "deep/code/unrelated"
    buried.mkdir(parents=True)
    (buried / "pom.xml").write_text("<project><artifactId>ignored</artifactId></project>")
    provider = MavenInspectionProvider()
    result = provider.inspect(InspectionContext(tmp_path, source=Node("root", ".")))
    assert len(result.nodes) == 1
    (tmp_path / "pom.xml").write_text(
        "<project><artifactId>root</artifactId><modules><module>../outside</module></modules></project>"
    )
    with pytest.raises(MavenModelError, match="escapes source"):
        provider.inspect(InspectionContext(tmp_path, source=Node("root", ".")))


def test_hydration_handler_refuses_missing_inputs_and_stale_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(monkeypatch)
    _declare(tmp_path, registry)
    inspection = inspect_workspace(registry, tmp_path, declared_only=True)
    plan = prepare_planning(registry, inspection, "hydrate", ("root", "ide")).plan
    context = ExecutionContext(tmp_path, tmp_path / ".poly/runs/test")
    handler = HydrationActionHandler(registry)
    coherence = next(action for action in plan.actions if action.id == "workspace.coherence")
    assert not handler.execute(coherence, context).success
    set_manifest_node_natures(tmp_path, "root", ("manual",), add=True)
    assert "changed after planning" in handler.execute(coherence, context).summary
    action = ActionSpec("bad", handler.name, "hydrate", "unknown", ())
    assert not handler.execute(action, context).success
    check = replace(action, operation="poly/source/check", environment={"path": "absent"})
    assert not handler.execute(check, context).success
    missing_provider = replace(
        action,
        operation="poly/source/inspect",
        environment={"source": "root", "provider": "missing"},
    )
    assert not handler.execute(missing_provider, context).success


def test_prepared_configuration_and_hydration_use_the_same_cli_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from poly.cli import main

    registry = _registry(monkeypatch)
    monkeypatch.setattr("poly.cli.build_registry", lambda: registry)
    create_workspace_files(tmp_path, "demo", "Demo")
    common = ["--workspace", str(tmp_path), "--format", "json"]
    assert main(["add", "eclipse-configuration", "ide", "--prepare", *common]) == 0
    assert len(validate_workspace(tmp_path).inventory.nodes) == 1
    assert main(["exec", *common]) == 0
    assert validate_workspace(tmp_path).inventory.get("ide").path is None
    assert main(["hydrate", "--prepare", *common]) == 0
    assert main(["exec", *common]) == 0
    assert (tmp_path / ".poly/projections/ide/request.xml").exists()
    capsys.readouterr()
    with pytest.raises(SystemExit) as error:
        main(["configure", "eclipse", *common])
    assert error.value.code == 2


def test_schema_registration_does_not_imply_a_hydration_implementation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _registry(monkeypatch)
    original = loaded.contributions.driver_registration("fixture.eclipse")
    registry = build_registry()
    registry.register(
        DriverRegistration(
            replace(original.manifest, capabilities=frozenset()),
            configuration_schemas=original.configuration_schemas,
        )
    )
    _declare(tmp_path, registry)
    inspection = inspect_workspace(registry, tmp_path, declared_only=True)
    plan = prepare_planning(registry, inspection, "hydrate", ("root", "ide")).plan
    assert plan.status is PlanStatus.BLOCKED
    assert any(item.code == "configuration.unhandled" for item in plan.diagnostics)
