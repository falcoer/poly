"""Versioned driver-facing protocols and transport-neutral contexts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

from poly.model import ActionSpec, DriverProposal, JsonValue, Node, PlanningRequest

type FacadeArgumentValue = str | tuple[str, ...] | None


def _display_text(value: str, field_name: str) -> str:
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if any(character in value for character in ("\n", "\r", "\x1b")) or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValueError(f"{field_name} must be a single control-free line")
    return value


class OutputKind(StrEnum):
    FILE = "file"
    URL = "url"


@dataclass(frozen=True, slots=True)
class ActionValue:
    """One concise, canonical value suitable for an action row."""

    value: str | int | float | bool
    label: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.value, str):
            _display_text(self.value, "action value")
        elif isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("action value must be a finite JSON number")
        elif not isinstance(self.value, (int, float, bool)):
            raise TypeError("action value must be a string, number, or boolean")
        if self.label is not None:
            _display_text(self.label, "action value label")


ScalarValue = ActionValue


@dataclass(frozen=True, slots=True)
class OutputReference:
    """A typed, user-facing deliverable explicitly exposed by an action."""

    kind: OutputKind | str
    target: str
    label: str | None = None
    media_type: str | None = None

    def __post_init__(self) -> None:
        kind = OutputKind(self.kind)
        target = _display_text(self.target, "output target")
        if kind is OutputKind.URL:
            parsed = urlsplit(target)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("URL output target must be an absolute HTTP(S) URL")
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("URL output target must not contain credentials")
        if self.label is not None:
            _display_text(self.label, "output label")
        if self.media_type is not None:
            _display_text(self.media_type, "output media type")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "target", target)


@dataclass(frozen=True, slots=True, order=True)
class InspectionDiagnostic:
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True, slots=True)
class InspectionContext:
    workspace: Path
    parameters: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        workspace = self.workspace.resolve()
        if not workspace.is_dir():
            raise ValueError(f"workspace does not exist or is not a directory: {workspace}")
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(
            self, "parameters", MappingProxyType(dict(sorted(self.parameters.items())))
        )


@dataclass(frozen=True, slots=True)
class InspectionResult:
    driver: str
    nodes: tuple[Node, ...] = ()
    diagnostics: tuple[InspectionDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(sorted(self.nodes, key=lambda node: node.id)))
        object.__setattr__(self, "diagnostics", tuple(sorted(self.diagnostics)))


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    workspace: Path
    run_directory: Path
    environment: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        workspace = self.workspace.resolve()
        run_directory = self.run_directory.resolve()
        if not workspace.is_dir():
            raise ValueError(f"workspace does not exist: {workspace}")
        try:
            run_directory.relative_to(workspace)
        except ValueError as error:
            raise ValueError("run directory must belong to the workspace") from error
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "run_directory", run_directory)
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))


@dataclass(frozen=True, slots=True, init=False)
class DriverExecutionResult:
    success: bool
    summary: str = ""
    details: dict[str, JsonValue] = field(default_factory=dict)
    value: ActionValue | None = None
    outputs: tuple[OutputReference, ...] = ()

    def __init__(
        self,
        success: bool,
        summary: str = "",
        details: dict[str, JsonValue] | None = None,
        value: ActionValue | str | int | float | bool | None = None,
        outputs: tuple[OutputReference, ...] = (),
    ) -> None:
        object.__setattr__(self, "success", success)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "details", {} if details is None else details)
        object.__setattr__(
            self,
            "value",
            ActionValue(value)
            if value is not None and not isinstance(value, ActionValue)
            else value,
        )
        object.__setattr__(self, "outputs", outputs)
        self.__post_init__()

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))
        if any(not isinstance(output, OutputReference) for output in self.outputs):
            raise TypeError("outputs must contain OutputReference values")
        object.__setattr__(self, "outputs", tuple(self.outputs))


@dataclass(frozen=True, slots=True)
class FacadeArgument:
    """Transport-neutral description of one dynamically exposed CLI argument."""

    name: str
    flags: tuple[str, ...]
    required: bool = False
    repeatable: bool = False
    choices: tuple[str, ...] = ()
    help: str = ""

    def __post_init__(self) -> None:
        if not self.name or any(character.isspace() for character in self.name):
            raise ValueError("facade argument name must be non-empty and contain no whitespace")
        if not self.flags:
            raise ValueError("facade argument must declare at least one flag")
        positional = not self.flags[0].startswith("-")
        if positional and (len(self.flags) != 1 or self.flags[0] != self.name):
            raise ValueError("positional facade argument flag must equal its name")
        if not positional and any(not flag.startswith("--") for flag in self.flags):
            raise ValueError("optional facade argument flags must use long --names")
        normalized_choices = tuple(sorted(set(self.choices)))
        if any(not value for value in normalized_choices):
            raise ValueError("facade argument choices must not be empty")
        object.__setattr__(self, "flags", tuple(self.flags))
        object.__setattr__(self, "choices", normalized_choices)

    @property
    def positional(self) -> bool:
        return not self.flags[0].startswith("-")


@dataclass(frozen=True, slots=True)
class FacadeRequest:
    """One parsed facade invocation before canonical planning negotiation."""

    workspace: Path
    values: dict[str, FacadeArgumentValue]
    parameters: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace", self.workspace.resolve())
        object.__setattr__(self, "values", MappingProxyType(dict(sorted(self.values.items()))))
        object.__setattr__(
            self, "parameters", MappingProxyType(dict(sorted(self.parameters.items())))
        )


@runtime_checkable
class InspectionProvider(Protocol):
    @property
    def name(self) -> str: ...

    def inspect(self, context: InspectionContext) -> InspectionResult: ...


@runtime_checkable
class PlanningProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def verbs(self) -> frozenset[str]: ...

    def propose(self, request: PlanningRequest) -> DriverProposal: ...


@runtime_checkable
class ActionHandler(Protocol):
    @property
    def name(self) -> str: ...

    def execute(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult: ...


@runtime_checkable
class CommandFacade(Protocol):
    """Driver-contributed syntax translating to one canonical planning request."""

    @property
    def name(self) -> str: ...

    @property
    def verb(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def arguments(self) -> tuple[FacadeArgument, ...]: ...

    def translate(self, request: FacadeRequest) -> dict[str, str]: ...
