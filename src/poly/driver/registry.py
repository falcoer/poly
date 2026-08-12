"""Validated in-process driver registry."""

from __future__ import annotations

from dataclasses import dataclass

from poly.driver.api import ActionHandler, InspectionProvider, PlanningProvider
from poly.driver.manifest import DriverCapability, DriverManifest, DriverProtocolError


@dataclass(frozen=True, slots=True)
class DriverRegistration:
    manifest: DriverManifest
    inspectors: tuple[InspectionProvider, ...] = ()
    planners: tuple[PlanningProvider, ...] = ()
    handlers: tuple[ActionHandler, ...] = ()

    def validate(self) -> None:
        self.manifest.ensure_compatible()
        actual: set[DriverCapability] = set()
        if self.inspectors:
            actual.add(DriverCapability.INSPECT)
        if self.planners:
            actual.add(DriverCapability.PLAN)
        if self.handlers:
            actual.add(DriverCapability.EXECUTE)
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


class DriverRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, DriverRegistration] = {}

    def register(self, registration: DriverRegistration) -> None:
        registration.validate()
        name = registration.manifest.name
        if name in self._registrations:
            raise DriverProtocolError(f"driver {name!r} is already registered")
        self._registrations[name] = registration

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
