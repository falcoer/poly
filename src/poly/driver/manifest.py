"""Driver identity, capability declaration, and protocol compatibility."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

DRIVER_API_VERSION = "1.1"


class DriverProtocolError(ValueError):
    """Raised before loading an incompatible or malformed driver."""


class DriverCapability(StrEnum):
    FACADE = "facade"
    INSPECT = "inspect"
    PLAN = "plan"
    EXECUTE = "execute"


def _version_parts(value: str, field_name: str) -> tuple[int, int]:
    parts = value.split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise DriverProtocolError(f"{field_name} must use <major>.<minor>: {value!r}")
    return int(parts[0]), int(parts[1])


@dataclass(frozen=True, slots=True)
class DriverManifest:
    name: str
    version: str
    api_version: str
    capabilities: frozenset[DriverCapability]
    description: str = ""
    natures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or any(character.isspace() for character in self.name):
            raise DriverProtocolError("driver name must be non-empty and contain no whitespace")
        if not self.version:
            raise DriverProtocolError("driver version must not be empty")
        normalized_natures = tuple(sorted(set(self.natures)))
        if any(
            not nature or any(character.isspace() for character in nature)
            for nature in normalized_natures
        ):
            raise DriverProtocolError("driver natures must be non-empty and contain no whitespace")
        object.__setattr__(self, "natures", normalized_natures)
        _version_parts(self.api_version, "api_version")

    def ensure_compatible(self, supported: str = DRIVER_API_VERSION) -> None:
        requested_major, requested_minor = _version_parts(self.api_version, "api_version")
        supported_major, supported_minor = _version_parts(supported, "supported api version")
        if requested_major != supported_major or requested_minor > supported_minor:
            raise DriverProtocolError(
                f"driver {self.name!r} requires API {self.api_version}; Poly supports {supported}"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "api_version": self.api_version,
            "capabilities": sorted(capability.value for capability in self.capabilities),
            "description": self.description,
            "natures": list(self.natures),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> DriverManifest:
        try:
            capabilities = frozenset(
                DriverCapability(item) for item in _string_list(value["capabilities"])
            )
            return cls(
                name=str(value["name"]),
                version=str(value["version"]),
                api_version=str(value["api_version"]),
                capabilities=capabilities,
                description=str(value.get("description", "")),
                natures=_string_list(value.get("natures", [])),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise DriverProtocolError(f"invalid driver manifest: {error}") from error


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DriverProtocolError("capabilities must be a list of strings")
    return tuple(value)
