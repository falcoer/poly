"""Versioned driver-facing protocols and transport-neutral contexts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from poly.model import ActionSpec, DriverProposal, JsonValue, Node, PlanningRequest


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


@dataclass(frozen=True, slots=True)
class DriverExecutionResult:
    success: bool
    summary: str = ""
    details: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


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
