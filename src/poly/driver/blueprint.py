"""Minimal data-only configuration contract; no generation or execution hooks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from poly.driver.extension import ExtensionProtocolError


def _name(value: str) -> str:
    if not value or any(character.isspace() for character in value):
        raise ExtensionProtocolError("blueprint identifiers must be non-empty without whitespace")
    return value


def _strings(values: Mapping[str, str]) -> Mapping[str, str]:
    if any(not isinstance(value, str) for value in values.values()):
        raise ExtensionProtocolError("blueprint values must be strings")
    return MappingProxyType({_name(key): value for key, value in sorted(values.items())})


@dataclass(frozen=True, slots=True)
class BlueprintParameter:
    """A required string parameter, or an optional one with an explicit default."""

    name: str
    default: str | None = None
    choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _name(self.name)
        if any(not isinstance(value, str) for value in self.choices):
            raise ExtensionProtocolError("blueprint choices must be strings")
        object.__setattr__(self, "choices", tuple(sorted(set(self.choices))))
        if self.default is not None:
            self.validate(self.default)

    def validate(self, value: str) -> str:
        if not isinstance(value, str) or (self.choices and value not in self.choices):
            raise ExtensionProtocolError(f"invalid blueprint parameter {self.name!r}: {value!r}")
        return value


@dataclass(frozen=True, slots=True)
class ResolvedBlueprint:
    """Resolved intent for one finite negotiation, never an executable blueprint."""

    name: str
    version: str
    parameters: Mapping[str, str]
    configuration: Mapping[str, str]
    resources: tuple[str, ...]
    required_contributions: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _strings(self.parameters))
        object.__setattr__(self, "configuration", _strings(self.configuration))

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "parameters": dict(self.parameters),
            "configuration": dict(self.configuration),
            "resources": list(self.resources),
            "required_contributions": list(self.required_contributions),
        }


@dataclass(frozen=True, slots=True)
class BlueprintDefinition:
    """Versioned string-map configuration with explicit parameter bindings.

    Keys and values belong to the consuming driver. Resource references are
    opaque plugin resource identifiers, not instructions to fetch or write files.
    Legacy name/description-only contributions remain registerable.
    """

    name: str
    description: str
    version: str
    parameters: tuple[BlueprintParameter, ...] = ()
    configuration: Mapping[str, str] = field(default_factory=dict)
    bindings: Mapping[str, str] = field(default_factory=dict)
    resources: tuple[str, ...] = ()
    required_contributions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _name(self.name)
        _name(self.version)
        parameters = tuple(sorted(self.parameters, key=lambda item: item.name))
        names = {parameter.name for parameter in parameters}
        if len(names) != len(parameters):
            raise ExtensionProtocolError("duplicate blueprint parameters")
        configuration = _strings(self.configuration)
        bindings = _strings(self.bindings)
        if set(bindings.values()) - names:
            raise ExtensionProtocolError("blueprint binding references an unknown parameter")
        if set(bindings) & set(configuration):
            raise ExtensionProtocolError("blueprint bindings conflict with configuration keys")
        for attribute in ("resources", "required_contributions"):
            values = tuple(sorted({_name(value) for value in getattr(self, attribute)}))
            object.__setattr__(self, attribute, values)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "configuration", configuration)
        object.__setattr__(self, "bindings", bindings)


def resolve_definition(
    definition: BlueprintDefinition,
    parameters: Mapping[str, str],
    *,
    version: str,
    available_contributions: frozenset[str],
    available_resources: frozenset[str],
) -> ResolvedBlueprint:
    """Validate explicit inputs and substitute bindings before plan freezing."""
    if version != definition.version:
        raise ExtensionProtocolError(f"blueprint {definition.name!r} version mismatch: {version!r}")
    for label, required, available in (
        ("contributions", definition.required_contributions, available_contributions),
        ("resources", definition.resources, available_resources),
    ):
        missing = set(required) - available
        if missing:
            raise ExtensionProtocolError(f"missing blueprint {label}: {sorted(missing)!r}")
    unknown = set(parameters) - {item.name for item in definition.parameters}
    if unknown:
        raise ExtensionProtocolError(f"unknown blueprint parameters: {sorted(unknown)!r}")
    values: dict[str, str] = {}
    for parameter in definition.parameters:
        value = parameters.get(parameter.name, parameter.default)
        if value is None:
            raise ExtensionProtocolError(f"missing blueprint parameter: {parameter.name!r}")
        values[parameter.name] = parameter.validate(value)
    configuration = dict(definition.configuration)
    configuration.update({key: values[name] for key, name in definition.bindings.items()})
    return ResolvedBlueprint(
        definition.name,
        definition.version,
        values,
        configuration,
        definition.resources,
        definition.required_contributions,
    )
