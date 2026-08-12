"""Discover and validate external drivers through public Python conventions."""

from __future__ import annotations

import importlib
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import cast

from poly.driver.manifest import DriverProtocolError
from poly.driver.registry import DriverRegistration, DriverRegistry

DRIVER_ENTRY_POINT_GROUP = "poly.drivers"
DRIVER_SPEC_VERSION = "1"
DriverFactory = Callable[[], DriverRegistration]


class DriverDiscoveryError(DriverProtocolError):
    """Raised when an external-driver declaration cannot be loaded safely."""


@dataclass(frozen=True, slots=True)
class ExternalDriverSpec:
    """Versioned local declaration used by the conformance CLI."""

    name: str
    entrypoint: str
    spec_version: str = DRIVER_SPEC_VERSION

    def __post_init__(self) -> None:
        if self.spec_version != DRIVER_SPEC_VERSION:
            raise DriverDiscoveryError(
                f"unsupported driver spec version {self.spec_version!r}; "
                f"expected {DRIVER_SPEC_VERSION!r}"
            )
        if not self.name or any(character.isspace() for character in self.name):
            raise DriverDiscoveryError("driver name must be non-empty and contain no whitespace")
        module, separator, attribute = self.entrypoint.partition(":")
        if not separator or not module or not attribute or ":" in attribute:
            raise DriverDiscoveryError("entrypoint must use the form <module>:<factory>")

    @classmethod
    def from_file(cls, path: Path) -> ExternalDriverSpec:
        try:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
            driver = document["driver"]
            if not isinstance(driver, dict):
                raise TypeError("[driver] must be a table")
            name = driver["name"]
            entrypoint = driver["entrypoint"]
            spec_version = driver.get("spec-version", DRIVER_SPEC_VERSION)
            if not all(isinstance(value, str) for value in (name, entrypoint, spec_version)):
                raise TypeError("driver fields must be strings")
        except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as error:
            raise DriverDiscoveryError(f"invalid driver spec {path}: {error}") from error
        return cls(name, entrypoint, spec_version)


@dataclass(frozen=True, slots=True, order=True)
class DriverLoadDiagnostic:
    entry_point: str
    message: str


@dataclass(frozen=True, slots=True)
class DriverLoadResult:
    loaded: tuple[str, ...]
    rejected: tuple[DriverLoadDiagnostic, ...]

    def require_success(self) -> None:
        if self.rejected:
            details = "; ".join(
                f"{diagnostic.entry_point}: {diagnostic.message}" for diagnostic in self.rejected
            )
            raise DriverDiscoveryError(f"external driver loading failed: {details}")


def load_external_driver(spec: ExternalDriverSpec) -> DriverRegistration:
    """Load one declaration and validate it before returning any providers."""

    module_name, _, attribute = spec.entrypoint.partition(":")
    try:
        factory_value = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as error:
        raise DriverDiscoveryError(
            f"cannot load driver entrypoint {spec.entrypoint!r}: {error}"
        ) from error
    registration = _registration_from_factory(factory_value)
    if registration.manifest.name != spec.name:
        raise DriverDiscoveryError(
            f"declared driver {spec.name!r} does not match manifest {registration.manifest.name!r}"
        )
    return registration


def load_entrypoint(value: str) -> DriverRegistration:
    """Load one explicit ``module:factory`` expression for conformance checks."""

    module_name, separator, attribute = value.partition(":")
    if not separator or not module_name or not attribute or ":" in attribute:
        raise DriverDiscoveryError("entrypoint must use the form <module>:<factory>")
    try:
        factory_value = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as error:
        raise DriverDiscoveryError(f"cannot load driver entrypoint {value!r}: {error}") from error
    return _registration_from_factory(factory_value)


def discover_external_drivers(
    registry: DriverRegistry,
    candidates: Iterable[EntryPoint] | None = None,
) -> DriverLoadResult:
    """Load, validate, and register installed drivers in deterministic order."""

    selected = tuple(
        candidates
        if candidates is not None
        else entry_points().select(group=DRIVER_ENTRY_POINT_GROUP)
    )
    loaded: list[str] = []
    rejected: list[DriverLoadDiagnostic] = []
    for entry_point in sorted(selected, key=lambda item: (item.name, item.value)):
        try:
            registration = _registration_from_factory(entry_point.load())
            registry.register(registration)
        except Exception as error:  # third-party import and factory boundary
            rejected.append(
                DriverLoadDiagnostic(entry_point.name, f"{type(error).__name__}: {error}")
            )
            continue
        loaded.append(registration.manifest.name)
    return DriverLoadResult(tuple(loaded), tuple(rejected))


def _registration_from_factory(factory_value: object) -> DriverRegistration:
    if not callable(factory_value):
        raise DriverDiscoveryError("entrypoint must resolve to a driver factory")
    registration = cast(DriverFactory, factory_value)()
    if not isinstance(registration, DriverRegistration):
        raise DriverDiscoveryError("driver factory must return DriverRegistration")
    registration.validate()
    return registration
