"""Transport-neutral plugin and contribution descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

POLY_EXTENSION_API_VERSION = "1.0"


class ExtensionProtocolError(ValueError):
    """Raised before accepting an incompatible extension container."""


def _identity(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized or any(character.isspace() for character in normalized):
        raise ExtensionProtocolError(f"{field_name} must be non-empty and contain no whitespace")
    return normalized


def _version_parts(value: str, field_name: str) -> tuple[int, int]:
    parts = value.split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ExtensionProtocolError(f"{field_name} must use <major>.<minor>: {value!r}")
    return int(parts[0]), int(parts[1])


class ContributionKind(StrEnum):
    """Kinds reserved by the Poly Extension API."""

    DRIVER = "driver"
    FACADE = "facade"
    BLUEPRINT = "blueprint"


@dataclass(frozen=True, slots=True, order=True)
class ContributionDescriptor:
    """Stable, serializable identity for one plugin contribution."""

    identity: str
    kind: ContributionKind | str

    def __post_init__(self) -> None:
        identity = _identity(self.identity, "contribution identity")
        kind = ContributionKind(self.kind)
        if not identity.startswith(f"{kind.value}:"):
            raise ExtensionProtocolError(
                f"contribution identity {identity!r} does not match kind {kind.value!r}"
            )
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "kind", kind)

    def to_dict(self) -> dict[str, str]:
        return {"identity": self.identity, "kind": ContributionKind(self.kind).value}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> ContributionDescriptor:
        try:
            return cls(str(value["identity"]), str(value["kind"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ExtensionProtocolError(f"invalid contribution descriptor: {error}") from error


@dataclass(frozen=True, slots=True)
class Plugin:
    """Serializable descriptor for one Poly extension container."""

    id: str
    version: str
    api_version: str
    contributions: tuple[ContributionDescriptor, ...]
    dependencies: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identity(self.id, "plugin id"))
        if not self.version:
            raise ExtensionProtocolError("plugin version must not be empty")
        _version_parts(self.api_version, "api_version")
        contributions = tuple(sorted(self.contributions))
        identities = [contribution.identity for contribution in contributions]
        if len(identities) != len(set(identities)):
            raise ExtensionProtocolError(f"plugin {self.id!r} declares duplicate contributions")
        dependencies = tuple(
            sorted({_identity(dependency, "plugin dependency") for dependency in self.dependencies})
        )
        if self.id in dependencies:
            raise ExtensionProtocolError(f"plugin {self.id!r} cannot depend on itself")
        resources = tuple(sorted(set(self.resources)))
        if any(
            not resource or any(character in resource for character in ("\x00", "\n", "\r"))
            for resource in resources
        ):
            raise ExtensionProtocolError("plugin resources must be non-empty, control-free strings")
        object.__setattr__(self, "contributions", contributions)
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "resources", resources)

    def ensure_compatible(self, supported: str = POLY_EXTENSION_API_VERSION) -> None:
        requested_major, requested_minor = _version_parts(self.api_version, "api_version")
        supported_major, supported_minor = _version_parts(supported, "supported api version")
        if requested_major != supported_major or requested_minor > supported_minor:
            raise ExtensionProtocolError(
                f"plugin {self.id!r} requires Poly Extension API {self.api_version}; "
                f"Poly supports {supported}"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "version": self.version,
            "api_version": self.api_version,
            "contributions": [contribution.to_dict() for contribution in self.contributions],
            "dependencies": list(self.dependencies),
            "resources": list(self.resources),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> Plugin:
        try:
            raw_contributions = value["contributions"]
            raw_dependencies = value.get("dependencies", [])
            raw_resources = value.get("resources", [])
            if not isinstance(raw_contributions, list) or not all(
                isinstance(item, dict) for item in raw_contributions
            ):
                raise TypeError("contributions must be a list of objects")
            if not isinstance(raw_dependencies, list) or not all(
                isinstance(item, str) for item in raw_dependencies
            ):
                raise TypeError("dependencies must be a list of strings")
            if not isinstance(raw_resources, list) or not all(
                isinstance(item, str) for item in raw_resources
            ):
                raise TypeError("resources must be a list of strings")
            return cls(
                id=str(value["id"]),
                version=str(value["version"]),
                api_version=str(value["api_version"]),
                contributions=tuple(
                    ContributionDescriptor.from_dict(item) for item in raw_contributions
                ),
                dependencies=tuple(raw_dependencies),
                resources=tuple(raw_resources),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ExtensionProtocolError(f"invalid plugin descriptor: {error}") from error


def driver_contribution_identity(driver_name: str) -> str:
    return f"driver:{_identity(driver_name, 'driver name')}"


def facade_contribution_identity(verb: str, name: str) -> str:
    return f"facade:{_identity(verb, 'facade verb')}:{_identity(name, 'facade name')}"


def blueprint_contribution_identity(name: str) -> str:
    return f"blueprint:{_identity(name, 'blueprint name')}"
