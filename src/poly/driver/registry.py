"""Validated in-process driver registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from poly.driver.api import (
    ActionHandler,
    BlueprintContribution,
    CommandFacade,
    InspectionProvider,
    PlanningProvider,
)
from poly.driver.blueprint import BlueprintDefinition, ResolvedBlueprint, resolve_definition
from poly.driver.extension import (
    POLY_EXTENSION_API_VERSION,
    ContributionDescriptor,
    ContributionKind,
    ExtensionProtocolError,
    Plugin,
    blueprint_contribution_identity,
    driver_contribution_identity,
    facade_contribution_identity,
)
from poly.driver.manifest import DriverCapability, DriverManifest, DriverProtocolError

_RESERVED_FACADE_ARGUMENT_NAMES = frozenset(
    {
        "color",
        "command",
        "controller",
        "facade",
        "format",
        "help",
        "parameter",
        "plan_only",
        "prepare",
        "select",
        "verbosity",
        "version",
        "workspace",
    }
)
_RESERVED_FACADE_FLAGS = frozenset(
    {
        "--color",
        "--controller",
        "--format",
        "--help",
        "--parameter",
        "--plan",
        "--prepare",
        "--quiet",
        "--select",
        "--verbose",
        "--version",
        "--workspace",
    }
)


def _validate_facades(facades: tuple[CommandFacade, ...]) -> None:
    facade_keys = [(facade.verb, facade.name) for facade in facades]
    if len(facade_keys) != len(set(facade_keys)):
        raise DriverProtocolError("extension registers duplicate facade identities")
    for facade in facades:
        names = [argument.name for argument in facade.arguments]
        flags = [flag for argument in facade.arguments for flag in argument.flags]
        if len(names) != len(set(names)):
            raise DriverProtocolError(
                f"facade {facade.verb}:{facade.name} registers duplicate argument names"
            )
        if len(flags) != len(set(flags)):
            raise DriverProtocolError(
                f"facade {facade.verb}:{facade.name} registers duplicate argument flags"
            )
        reserved_names = sorted(set(names) & _RESERVED_FACADE_ARGUMENT_NAMES)
        reserved_flags = sorted(set(flags) & _RESERVED_FACADE_FLAGS)
        if reserved_names or reserved_flags:
            collisions = sorted({*reserved_names, *reserved_flags})
            raise DriverProtocolError(
                f"facade {facade.verb}:{facade.name} collides with reserved CLI arguments: "
                f"{collisions!r}"
            )


@dataclass(frozen=True, slots=True)
class DriverRegistration:
    manifest: DriverManifest
    inspectors: tuple[InspectionProvider, ...] = ()
    planners: tuple[PlanningProvider, ...] = ()
    handlers: tuple[ActionHandler, ...] = ()
    facades: tuple[CommandFacade, ...] = ()

    def validate(self) -> None:
        self.manifest.ensure_compatible()
        actual: set[DriverCapability] = set()
        if self.inspectors:
            actual.add(DriverCapability.INSPECT)
        if self.planners:
            actual.add(DriverCapability.PLAN)
        if self.handlers:
            actual.add(DriverCapability.EXECUTE)
        if self.facades:
            actual.add(DriverCapability.FACADE)
        if actual != set(self.manifest.capabilities):
            raise DriverProtocolError(
                f"driver {self.manifest.name!r} declares "
                f"{sorted(item.value for item in self.manifest.capabilities)!r} but registers "
                f"{sorted(item.value for item in actual)!r}"
            )
        provider_names = {
            *(provider.name for provider in self.inspectors),
            *(provider.name for provider in self.planners),
            *(provider.name for provider in self.handlers),
        }
        mismatched = sorted(provider_names - {self.manifest.name})
        if mismatched:
            raise DriverProtocolError(
                f"providers must use manifest name {self.manifest.name!r}: {mismatched!r}"
            )
        try:
            _validate_facades(self.facades)
        except DriverProtocolError as error:
            if "extension registers duplicate" in str(error):
                raise DriverProtocolError("driver registers duplicate facade identities") from error
            raise


@dataclass(frozen=True, slots=True)
class PluginRegistration:
    """One plugin descriptor paired with its in-process contributions."""

    plugin: Plugin
    drivers: tuple[DriverRegistration, ...] = ()
    facades: tuple[CommandFacade, ...] = ()
    blueprints: tuple[BlueprintContribution, ...] = ()

    def validate(self) -> None:
        self.plugin.ensure_compatible()
        for driver in self.drivers:
            driver.validate()
        all_facades = (
            *self.facades,
            *(facade for driver in self.drivers for facade in driver.facades),
        )
        _validate_facades(all_facades)
        blueprint_names = [blueprint.name for blueprint in self.blueprints]
        if len(blueprint_names) != len(set(blueprint_names)):
            raise ExtensionProtocolError("plugin registers duplicate blueprint identities")
        actual_values = (
            *(
                ContributionDescriptor(
                    driver_contribution_identity(driver.manifest.name),
                    ContributionKind.DRIVER,
                )
                for driver in self.drivers
            ),
            *(
                ContributionDescriptor(
                    facade_contribution_identity(facade.verb, facade.name),
                    ContributionKind.FACADE,
                )
                for facade in all_facades
            ),
            *(
                ContributionDescriptor(
                    blueprint_contribution_identity(blueprint.name),
                    ContributionKind.BLUEPRINT,
                )
                for blueprint in self.blueprints
            ),
        )
        actual = set(actual_values)
        if len(actual_values) != len(actual):
            raise ExtensionProtocolError("plugin registers duplicate contribution identities")
        declared = set(self.plugin.contributions)
        if actual != declared:
            missing = sorted(item.identity for item in actual - declared)
            unexpected = sorted(item.identity for item in declared - actual)
            raise ExtensionProtocolError(
                f"plugin {self.plugin.id!r} contribution descriptor mismatch; "
                f"missing={missing!r}, unexpected={unexpected!r}"
            )


@dataclass(frozen=True, slots=True)
class PluginInventoryItem:
    identity: str
    version: str | None
    api_version: str | None
    dependencies: tuple[str, ...]
    resources: tuple[str, ...]
    contributions: tuple[str, ...]
    origin: str
    status: str
    entry_point: str | None = None
    diagnostic: str | None = None


@dataclass(frozen=True, slots=True)
class ContributionInventoryItem:
    identity: str
    kind: str
    plugin: str


class ContributionRegistry:
    """Language-neutral identity index for executable extension contributions."""

    def __init__(self) -> None:
        self._drivers: dict[str, tuple[str, DriverRegistration]] = {}
        self._facades: dict[tuple[str, str], tuple[str, CommandFacade]] = {}
        self._blueprints: dict[str, tuple[str, BlueprintContribution]] = {}
        self._blueprint_resources: dict[str, frozenset[str]] = {}

    def validate_registration(self, registration: PluginRegistration) -> None:
        registration.validate()
        duplicates: list[str] = []
        for driver in registration.drivers:
            identity = driver_contribution_identity(driver.manifest.name)
            if driver.manifest.name in self._drivers:
                duplicates.append(identity)
        for facade in self._registration_facades(registration):
            identity = facade_contribution_identity(facade.verb, facade.name)
            if (facade.verb, facade.name) in self._facades:
                duplicates.append(identity)
        for blueprint in registration.blueprints:
            identity = blueprint_contribution_identity(blueprint.name)
            if blueprint.name in self._blueprints:
                duplicates.append(identity)
        if duplicates:
            raise ExtensionProtocolError(
                f"duplicate contribution identities: {sorted(duplicates)!r}"
            )

    def register(self, registration: PluginRegistration) -> None:
        self.validate_registration(registration)
        plugin_id = registration.plugin.id
        for driver in registration.drivers:
            self._drivers[driver.manifest.name] = (plugin_id, driver)
        for facade in self._registration_facades(registration):
            self._facades[(facade.verb, facade.name)] = (plugin_id, facade)
        for blueprint in registration.blueprints:
            self._blueprints[blueprint.name] = (plugin_id, blueprint)
            self._blueprint_resources[blueprint.name] = frozenset(registration.plugin.resources)

    def driver_registrations(self) -> tuple[DriverRegistration, ...]:
        return tuple(value[1] for _, value in sorted(self._drivers.items()))

    def driver_registration(self, name: str) -> DriverRegistration:
        try:
            return self._drivers[name][1]
        except KeyError as error:
            raise DriverProtocolError(f"unknown driver: {name!r}") from error

    def plugin_for_driver(self, name: str) -> str:
        try:
            return self._drivers[name][0]
        except KeyError as error:
            raise DriverProtocolError(f"unknown driver: {name!r}") from error

    def facades(self, verb: str | None = None) -> tuple[CommandFacade, ...]:
        values = tuple(value[1] for _, value in sorted(self._facades.items()))
        if verb is None:
            return values
        return tuple(facade for facade in values if facade.verb == verb)

    def facade(self, verb: str, name: str) -> CommandFacade:
        try:
            return self._facades[(verb, name)][1]
        except KeyError as error:
            raise ExtensionProtocolError(f"unknown facade: {verb}:{name}") from error

    def blueprints(self) -> tuple[BlueprintContribution, ...]:
        return tuple(value[1] for _, value in sorted(self._blueprints.items()))

    def blueprint(self, name: str) -> BlueprintContribution:
        try:
            return self._blueprints[name][1]
        except KeyError as error:
            raise ExtensionProtocolError(f"unknown blueprint: {name!r}") from error

    def resolve_blueprint(
        self, name: str, parameters: Mapping[str, str], *, version: str
    ) -> ResolvedBlueprint:
        """Resolve data only, using loaded contributions and the owning plugin resources."""
        blueprint = self.blueprint(name)
        if not isinstance(blueprint, BlueprintDefinition):
            raise ExtensionProtocolError(f"blueprint {name!r} has no declarative definition")
        return resolve_definition(
            blueprint,
            parameters,
            version=version,
            available_contributions=frozenset(item.identity for item in self.inventory()),
            available_resources=self._blueprint_resources[name],
        )

    def inventory(self) -> tuple[ContributionInventoryItem, ...]:
        items = [
            ContributionInventoryItem(driver_contribution_identity(name), "driver", plugin)
            for name, (plugin, _) in self._drivers.items()
        ]
        items.extend(
            ContributionInventoryItem(facade_contribution_identity(verb, name), "facade", plugin)
            for (verb, name), (plugin, _) in self._facades.items()
        )
        items.extend(
            ContributionInventoryItem(blueprint_contribution_identity(name), "blueprint", plugin)
            for name, (plugin, _) in self._blueprints.items()
        )
        return tuple(sorted(items, key=lambda item: item.identity))

    @staticmethod
    def _registration_facades(
        registration: PluginRegistration,
    ) -> tuple[CommandFacade, ...]:
        return (
            *registration.facades,
            *(f for driver in registration.drivers for f in driver.facades),
        )


class PluginRegistry:
    """Validated registry of plugin containers and their owned contributions."""

    def __init__(self, contributions: ContributionRegistry | None = None) -> None:
        self.contributions = contributions or ContributionRegistry()
        self._plugins: dict[str, PluginRegistration] = {}
        self._metadata: dict[str, tuple[str, str | None]] = {}
        self._rejected: list[PluginInventoryItem] = []

    def register(
        self,
        registration: PluginRegistration,
        *,
        origin: str = "installed",
        entry_point: str | None = None,
    ) -> None:
        registration.validate()
        plugin_id = registration.plugin.id
        if plugin_id in self._plugins:
            raise ExtensionProtocolError(f"plugin {plugin_id!r} is already registered")
        self.contributions.validate_registration(registration)
        self.contributions.register(registration)
        self._plugins[plugin_id] = registration
        self._metadata[plugin_id] = (origin, entry_point)

    def plugins(self) -> tuple[Plugin, ...]:
        return tuple(value.plugin for _, value in sorted(self._plugins.items()))

    def get(self, plugin_id: str) -> Plugin:
        try:
            return self._plugins[plugin_id].plugin
        except KeyError as error:
            raise ExtensionProtocolError(f"unknown plugin: {plugin_id!r}") from error

    def reject(
        self,
        identity: str,
        *,
        origin: str,
        diagnostic: str,
        entry_point: str | None = None,
        version: str | None = None,
        api_version: str | None = None,
    ) -> None:
        self._rejected.append(
            PluginInventoryItem(
                identity,
                version,
                api_version,
                (),
                (),
                (),
                origin,
                DriverLoadStatus.REJECTED.value,
                entry_point,
                diagnostic,
            )
        )

    def inventory(self) -> tuple[PluginInventoryItem, ...]:
        loaded = tuple(
            PluginInventoryItem(
                registration.plugin.id,
                registration.plugin.version,
                registration.plugin.api_version,
                registration.plugin.dependencies,
                registration.plugin.resources,
                tuple(item.identity for item in registration.plugin.contributions),
                self._metadata[plugin_id][0],
                DriverLoadStatus.LOADED.value,
                self._metadata[plugin_id][1],
            )
            for plugin_id, registration in sorted(self._plugins.items())
        )
        return tuple(
            sorted(
                (*loaded, *self._rejected),
                key=lambda item: (
                    item.identity,
                    item.origin,
                    item.entry_point or "",
                    item.status,
                ),
            )
        )


class DriverOrigin(StrEnum):
    SYSTEM = "system"
    BUILTIN = "builtin"
    INSTALLED = "installed"


class DriverLoadStatus(StrEnum):
    LOADED = "loaded"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class DriverInventoryItem:
    identity: str
    version: str | None
    origin: str
    api_version: str | None
    capabilities: tuple[str, ...]
    verbs: tuple[str, ...]
    status: str
    entry_point: str | None = None
    diagnostic: str | None = None
    description: str = ""
    natures: tuple[str, ...] = ()
    facades: tuple[str, ...] = ()
    plugin: str | None = None
    contributions: tuple[str, ...] = ()


class DriverRegistry:
    def __init__(self) -> None:
        self.contribution_registry = ContributionRegistry()
        self.plugin_registry = PluginRegistry(self.contribution_registry)
        self.contributions = self.contribution_registry
        self.plugins = self.plugin_registry
        self._inventory: list[DriverInventoryItem] = []

    def register(
        self,
        registration: DriverRegistration,
        *,
        origin: DriverOrigin | str = DriverOrigin.BUILTIN,
        entry_point: str | None = None,
        plugin_id: str | None = None,
    ) -> None:
        registration.validate()
        name = registration.manifest.name
        owner = plugin_id or name
        descriptors = (
            ContributionDescriptor(driver_contribution_identity(name), ContributionKind.DRIVER),
            *(
                ContributionDescriptor(
                    facade_contribution_identity(facade.verb, facade.name),
                    ContributionKind.FACADE,
                )
                for facade in registration.facades
            ),
        )
        plugin = Plugin(
            owner,
            registration.manifest.version,
            POLY_EXTENSION_API_VERSION,
            descriptors,
        )
        try:
            self.register_plugin(
                PluginRegistration(plugin, drivers=(registration,)),
                origin=origin,
                entry_point=entry_point,
            )
        except ExtensionProtocolError as error:
            message = str(error)
            if "duplicate contribution" in message:
                if driver_contribution_identity(name) in message:
                    raise DriverProtocolError(f"driver {name!r} is already registered") from error
                raise DriverProtocolError(
                    message.replace("duplicate contribution identities", "driver facade collision")
                ) from error
            raise DriverProtocolError(message) from error

    def register_plugin(
        self,
        registration: PluginRegistration,
        *,
        origin: DriverOrigin | str = DriverOrigin.BUILTIN,
        entry_point: str | None = None,
    ) -> None:
        origin_value = origin.value if isinstance(origin, DriverOrigin) else origin
        self.plugins.register(registration, origin=origin_value, entry_point=entry_point)
        for driver in registration.drivers:
            self._record_driver(driver, registration.plugin.id, origin_value, entry_point)

    def _record_driver(
        self,
        registration: DriverRegistration,
        plugin_id: str,
        origin: str,
        entry_point: str | None,
    ) -> None:
        name = registration.manifest.name
        self._inventory.append(
            DriverInventoryItem(
                name,
                registration.manifest.version,
                origin,
                registration.manifest.api_version,
                tuple(sorted(item.value for item in registration.manifest.capabilities)),
                tuple(
                    sorted({verb for provider in registration.planners for verb in provider.verbs})
                ),
                DriverLoadStatus.LOADED.value,
                entry_point,
                description=registration.manifest.description,
                natures=registration.manifest.natures,
                facades=tuple(
                    sorted(f"{facade.verb}:{facade.name}" for facade in registration.facades)
                ),
                plugin=plugin_id,
                contributions=tuple(
                    sorted(
                        (
                            driver_contribution_identity(name),
                            *(
                                facade_contribution_identity(facade.verb, facade.name)
                                for facade in registration.facades
                            ),
                        )
                    )
                ),
            )
        )

    def reject(
        self,
        identity: str,
        *,
        origin: str,
        diagnostic: str,
        entry_point: str | None = None,
        version: str | None = None,
        api_version: str | None = None,
        capabilities: tuple[str, ...] = (),
        verbs: tuple[str, ...] = (),
        description: str = "",
        natures: tuple[str, ...] = (),
        facades: tuple[str, ...] = (),
    ) -> None:
        self._inventory.append(
            DriverInventoryItem(
                identity,
                version,
                origin,
                api_version,
                tuple(sorted(capabilities)),
                tuple(sorted(verbs)),
                DriverLoadStatus.REJECTED.value,
                entry_point,
                diagnostic,
                description,
                tuple(sorted(natures)),
                tuple(sorted(facades)),
                None,
                (),
            )
        )

    def inventory(self) -> tuple[DriverInventoryItem, ...]:
        return tuple(
            sorted(
                self._inventory,
                key=lambda item: (
                    item.identity,
                    item.origin,
                    item.entry_point or "",
                    item.status,
                    item.version or "",
                ),
            )
        )

    def manifests(self) -> tuple[DriverManifest, ...]:
        return tuple(
            registration.manifest for registration in self.contributions.driver_registrations()
        )

    def plugin_inventory(self) -> tuple[PluginInventoryItem, ...]:
        return self.plugins.inventory()

    def contribution_inventory(self) -> tuple[ContributionInventoryItem, ...]:
        return self.contributions.inventory()

    def inspection_providers(self) -> tuple[InspectionProvider, ...]:
        return tuple(
            provider
            for registration in self.contributions.driver_registrations()
            for provider in registration.inspectors
        )

    def planning_providers(self, verb: str | None = None) -> tuple[PlanningProvider, ...]:
        providers = tuple(
            provider
            for registration in self.contributions.driver_registrations()
            for provider in registration.planners
        )
        if verb is None:
            return providers
        return tuple(provider for provider in providers if verb in provider.verbs)

    def command_facades(self, verb: str | None = None) -> tuple[CommandFacade, ...]:
        return self.contributions.facades(verb)

    def blueprints(self) -> tuple[BlueprintContribution, ...]:
        return self.contributions.blueprints()

    def action_handler(self, driver_name: str) -> ActionHandler:
        handlers = self.contributions.driver_registration(driver_name).handlers
        if len(handlers) != 1:
            raise DriverProtocolError(
                f"driver {driver_name!r} must register exactly one action handler"
            )
        return handlers[0]
