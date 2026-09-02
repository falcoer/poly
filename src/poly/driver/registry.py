"""Validated in-process driver registry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from poly.driver.api import ActionHandler, CommandFacade, InspectionProvider, PlanningProvider
from poly.driver.manifest import DriverCapability, DriverManifest, DriverProtocolError


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
        facade_keys = [(facade.verb, facade.name) for facade in self.facades]
        if len(facade_keys) != len(set(facade_keys)):
            raise DriverProtocolError("driver registers duplicate facade identities")


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


class DriverRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, DriverRegistration] = {}
        self._inventory: list[DriverInventoryItem] = []

    def register(
        self,
        registration: DriverRegistration,
        *,
        origin: DriverOrigin | str = DriverOrigin.BUILTIN,
        entry_point: str | None = None,
    ) -> None:
        registration.validate()
        name = registration.manifest.name
        if name in self._registrations:
            raise DriverProtocolError(f"driver {name!r} is already registered")
        current_facades = {
            (facade.verb, facade.name)
            for current in self._registrations.values()
            for facade in current.facades
        }
        collisions = sorted(
            f"{facade.verb}:{facade.name}"
            for facade in registration.facades
            if (facade.verb, facade.name) in current_facades
        )
        if collisions:
            raise DriverProtocolError(f"driver facade collision: {collisions!r}")
        self._registrations[name] = registration
        self._inventory.append(
            DriverInventoryItem(
                name,
                registration.manifest.version,
                origin.value if isinstance(origin, DriverOrigin) else origin,
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
            registration.manifest for _, registration in sorted(self._registrations.items())
        )

    def inspection_providers(self) -> tuple[InspectionProvider, ...]:
        return tuple(
            provider
            for _, registration in sorted(self._registrations.items())
            for provider in registration.inspectors
        )

    def planning_providers(self, verb: str | None = None) -> tuple[PlanningProvider, ...]:
        providers = tuple(
            provider
            for _, registration in sorted(self._registrations.items())
            for provider in registration.planners
        )
        if verb is None:
            return providers
        return tuple(provider for provider in providers if verb in provider.verbs)

    def command_facades(self, verb: str | None = None) -> tuple[CommandFacade, ...]:
        facades = tuple(
            facade
            for _, registration in sorted(self._registrations.items())
            for facade in registration.facades
        )
        if verb is None:
            return tuple(sorted(facades, key=lambda facade: (facade.verb, facade.name)))
        return tuple(
            sorted((facade for facade in facades if facade.verb == verb), key=lambda f: f.name)
        )

    def action_handler(self, driver_name: str) -> ActionHandler:
        try:
            handlers = self._registrations[driver_name].handlers
        except KeyError as error:
            raise DriverProtocolError(f"unknown driver: {driver_name!r}") from error
        if len(handlers) != 1:
            raise DriverProtocolError(
                f"driver {driver_name!r} must register exactly one action handler"
            )
        return handlers[0]
