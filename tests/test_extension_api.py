from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import cast

import pytest

from poly.driver import (
    DRIVER_API_VERSION,
    POLY_EXTENSION_API_VERSION,
    BlueprintContribution,
    CommandFacade,
    ContributionDescriptor,
    ContributionKind,
    DriverCapability,
    DriverDiscoveryError,
    DriverManifest,
    DriverProtocolError,
    DriverRegistration,
    DriverRegistry,
    ExtensionProtocolError,
    FacadeArgument,
    FacadeRequest,
    Plugin,
    PluginRegistration,
    blueprint_contribution_identity,
    discover_external_plugins,
    driver_contribution_identity,
    facade_contribution_identity,
    load_plugin_entrypoint,
)
from poly.reporting import drivers_document


@dataclass(frozen=True)
class ServiceFacade:
    name: str = "service"
    verb: str = "add"
    description: str = "Add a service"
    arguments: tuple[FacadeArgument, ...] = (FacadeArgument("name", ("name",), required=True),)

    def translate(self, request: FacadeRequest) -> dict[str, str]:
        name = request.values["name"]
        assert isinstance(name, str)
        return {"poly.node.id": name}


@dataclass(frozen=True)
class Blueprint:
    name: str = "service-stack"
    description: str = "A declarative service layout"


def _driver(name: str = "example.driver", *, facade: bool = False) -> DriverRegistration:
    facades: tuple[CommandFacade, ...] = (ServiceFacade(),) if facade else ()
    capabilities = frozenset((DriverCapability.FACADE,)) if facade else frozenset()
    return DriverRegistration(
        DriverManifest(name, "1.2.3", DRIVER_API_VERSION, capabilities),
        facades=facades,
    )


def _plugin(
    plugin_id: str = "example.plugin",
    *,
    driver: DriverRegistration | None = None,
    facade: CommandFacade | None = None,
    blueprint: BlueprintContribution | None = None,
) -> PluginRegistration:
    contributions: list[ContributionDescriptor] = []
    drivers = () if driver is None else (driver,)
    facades = () if facade is None else (facade,)
    blueprints = () if blueprint is None else (blueprint,)
    if driver is not None:
        contributions.append(
            ContributionDescriptor(
                driver_contribution_identity(driver.manifest.name), ContributionKind.DRIVER
            )
        )
        contributions.extend(
            ContributionDescriptor(
                facade_contribution_identity(item.verb, item.name), ContributionKind.FACADE
            )
            for item in driver.facades
        )
    if facade is not None:
        contributions.append(
            ContributionDescriptor(
                facade_contribution_identity(facade.verb, facade.name), ContributionKind.FACADE
            )
        )
    if blueprint is not None:
        contributions.append(
            ContributionDescriptor(
                blueprint_contribution_identity(blueprint.name), ContributionKind.BLUEPRINT
            )
        )
    return PluginRegistration(
        Plugin(
            plugin_id,
            "2.0.0",
            POLY_EXTENSION_API_VERSION,
            tuple(contributions),
        ),
        drivers,
        facades,
        blueprints,
    )


def test_plugin_descriptor_is_canonical_serializable_and_round_trips() -> None:
    descriptor = _plugin(driver=_driver(facade=True), blueprint=Blueprint()).plugin

    encoded = descriptor.to_dict()

    assert Plugin.from_dict(encoded) == descriptor
    assert json.loads(json.dumps(encoded)) == encoded
    contributions = cast(list[dict[str, object]], encoded["contributions"])
    assert [item["identity"] for item in contributions] == [
        "blueprint:service-stack",
        "driver:example.driver",
        "facade:add:service",
    ]


@pytest.mark.parametrize("api", ("1.1", "2.1"))
def test_plugin_rejects_incompatible_extension_api(api: str) -> None:
    plugin = Plugin("future.plugin", "1", api, ())

    with pytest.raises(ExtensionProtocolError, match="requires Poly Extension API"):
        plugin.ensure_compatible()


def test_plugin_descriptor_rejects_invalid_identity_dependencies_and_mapping() -> None:
    with pytest.raises(ExtensionProtocolError, match="plugin id"):
        Plugin("bad plugin", "1", POLY_EXTENSION_API_VERSION, ())
    with pytest.raises(ExtensionProtocolError, match="depend on itself"):
        Plugin("plugin", "1", POLY_EXTENSION_API_VERSION, (), ("plugin",))
    with pytest.raises(ExtensionProtocolError, match="duplicate contributions"):
        contribution = ContributionDescriptor("driver:one", "driver")
        Plugin("plugin", "1", POLY_EXTENSION_API_VERSION, (contribution, contribution))
    with pytest.raises(ExtensionProtocolError, match="invalid plugin descriptor"):
        Plugin.from_dict({"id": "plugin", "version": "1", "api_version": "1.0"})
    with pytest.raises(ExtensionProtocolError, match="invalid contribution descriptor"):
        ContributionDescriptor.from_dict({"identity": "driver:one"})
    with pytest.raises(ExtensionProtocolError, match="does not match kind"):
        ContributionDescriptor("facade:add:one", "driver")


def test_plugin_dependencies_are_optional_metadata_and_resources_are_serialized() -> None:
    registry = DriverRegistry()
    descriptor = Plugin(
        "plugin",
        "1",
        POLY_EXTENSION_API_VERSION,
        (),
        dependencies=("not-installed",),
        resources=("schemas/plugin.json",),
    )

    registry.register_plugin(PluginRegistration(descriptor))

    assert registry.plugin_registry.get("plugin") == descriptor
    assert descriptor.to_dict()["resources"] == ["schemas/plugin.json"]


def test_registry_resolves_every_existing_driver_through_contribution_registry() -> None:
    registry = DriverRegistry()
    driver = _driver(facade=True)

    registry.register(driver, plugin_id="example.plugin")

    assert registry.manifests() == (driver.manifest,)
    assert registry.command_facades("add") == (ServiceFacade(),)
    assert registry.contributions.driver_registration("example.driver") is driver
    assert registry.contributions.plugin_for_driver("example.driver") == "example.plugin"
    assert [item.identity for item in registry.contribution_inventory()] == [
        "driver:example.driver",
        "facade:add:service",
    ]
    inventory = registry.inventory()[0]
    assert inventory.plugin == "example.plugin"
    assert inventory.contributions == (
        "driver:example.driver",
        "facade:add:service",
    )


def test_explicit_plugin_reserves_blueprints_and_first_class_facades() -> None:
    registry = DriverRegistry()
    registration = _plugin(facade=ServiceFacade(), blueprint=Blueprint())

    registry.register_plugin(registration)

    assert registry.command_facades() == (ServiceFacade(),)
    assert registry.blueprints() == (Blueprint(),)
    assert registry.contributions.blueprint("service-stack") == Blueprint()
    assert registry.contributions.facade("add", "service") == ServiceFacade()
    assert isinstance(registry.blueprints()[0], BlueprintContribution)
    with pytest.raises(ExtensionProtocolError, match="no declarative definition"):
        registry.contributions.resolve_blueprint("service-stack", {}, version="1")
    assert registry.plugin_inventory()[0].contributions == (
        "blueprint:service-stack",
        "facade:add:service",
    )


def test_direct_plugin_facades_cannot_redeclare_core_cli_arguments() -> None:
    facade = ServiceFacade(arguments=(FacadeArgument("workspace", ("workspace",), required=True),))

    with pytest.raises(DriverProtocolError, match="reserved CLI arguments"):
        _plugin(facade=facade).validate()


def test_duplicate_plugins_and_contributions_fail_before_partial_registration() -> None:
    registry = DriverRegistry()
    first = _plugin(driver=_driver())
    registry.register_plugin(first)

    with pytest.raises(ExtensionProtocolError, match="already registered"):
        registry.register_plugin(_plugin())
    with pytest.raises(ExtensionProtocolError, match="duplicate contribution"):
        registry.register_plugin(_plugin("another.plugin", driver=_driver()))

    assert registry.plugins.plugins() == (first.plugin,)
    assert registry.manifests() == (first.drivers[0].manifest,)


def test_plugin_registration_requires_exact_descriptor_inventory() -> None:
    registration = PluginRegistration(
        Plugin("plugin", "1", POLY_EXTENSION_API_VERSION, ()),
        drivers=(_driver(),),
    )

    with pytest.raises(ExtensionProtocolError, match="descriptor mismatch"):
        registration.validate()


def test_legacy_registration_keeps_driver_errors_and_adds_implicit_plugin() -> None:
    registry = DriverRegistry()
    driver = _driver()
    registry.register(driver)

    assert registry.plugins.plugins()[0].id == "example.driver"
    with pytest.raises(DriverProtocolError, match="already registered"):
        registry.register(driver)
    with pytest.raises(DriverProtocolError, match="unknown driver"):
        registry.contributions.driver_registration("missing")


def test_structured_inventory_exposes_plugin_ownership(tmp_path: Path) -> None:
    registry = DriverRegistry()
    registry.register_plugin(_plugin(driver=_driver(), blueprint=Blueprint()))

    document = drivers_document(
        tmp_path,
        registry.inventory(),
        registry.plugin_inventory(),
        registry.contribution_inventory(),
    )

    drivers = cast(list[dict[str, object]], document["drivers"])
    plugins = cast(list[dict[str, object]], document["plugins"])
    assert drivers[0]["plugin"] == "example.plugin"
    assert plugins[0]["id"] == "example.plugin"
    assert document["contributions"] == [
        {"id": "blueprint:service-stack", "kind": "blueprint", "plugin": "example.plugin"},
        {"id": "driver:example.driver", "kind": "driver", "plugin": "example.plugin"},
    ]


def test_explicit_plugin_entrypoint_discovery_is_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "plugins.py"
    module.write_text(
        "from poly.driver import (POLY_EXTENSION_API_VERSION, Plugin, PluginRegistration)\n"
        "def valid():\n"
        "    return PluginRegistration(Plugin('installed.plugin', '1', "
        "POLY_EXTENSION_API_VERSION, ()))\n"
        "def invalid(): return object()\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    candidates = (
        EntryPoint("valid", "plugins:valid", "poly.plugins"),
        EntryPoint("invalid", "plugins:invalid", "poly.plugins"),
    )
    registry = DriverRegistry()

    result = discover_external_plugins(registry, candidates)

    assert result.loaded == ("installed.plugin",)
    assert len(result.rejected) == 1
    assert "PluginRegistration" in result.rejected[0].message
    rejected = next(item for item in registry.plugin_inventory() if item.status == "rejected")
    assert rejected.identity == "invalid"
    assert "PluginRegistration" in (rejected.diagnostic or "")
    with pytest.raises(DriverDiscoveryError):
        load_plugin_entrypoint("plugins:invalid")
    with pytest.raises(DriverProtocolError, match="external plugin loading failed"):
        result.require_success()
