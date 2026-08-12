"""Canonical, technology-neutral models used by Poly."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type Metadata = dict[str, JsonValue]


def _required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if any(character.isspace() for character in normalized):
        raise ValueError(f"{field_name} must not contain whitespace: {value!r}")
    return normalized


def _frozen_metadata(value: Metadata) -> Metadata:
    return MappingProxyType(dict(value))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True, order=True)
class Constraint:
    """A monotonic fact available only while negotiating or executing one run."""

    key: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _required(self.key, "constraint key"))


@dataclass(frozen=True, slots=True, order=True)
class ActionClaim:
    """Exclusive ownership of an operation on a scope."""

    operation: str
    scope: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _required(self.operation, "claim operation"))
        object.__setattr__(self, "scope", _required(self.scope, "claim scope"))


@dataclass(frozen=True, slots=True, order=True)
class NodeRelation:
    kind: str
    target: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _required(self.kind, "relation kind"))
        object.__setattr__(self, "target", _required(self.target, "relation target"))


@dataclass(frozen=True, slots=True)
class Node:
    """An observed structural unit selectable by a user or driver."""

    id: str
    path: str
    natures: tuple[str, ...] = ()
    metadata: Metadata = field(default_factory=dict)
    relations: tuple[NodeRelation, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required(self.id, "node id"))
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"node path must be workspace-relative: {self.path!r}")
        object.__setattr__(self, "path", path.as_posix())
        object.__setattr__(
            self, "natures", tuple(sorted({_required(n, "nature") for n in self.natures}))
        )
        object.__setattr__(self, "metadata", _frozen_metadata(self.metadata))
        object.__setattr__(self, "relations", tuple(sorted(set(self.relations))))


@dataclass(frozen=True, slots=True)
class Inventory:
    """A canonical snapshot of observable workspace structure."""

    nodes: tuple[Node, ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.nodes, key=lambda node: node.id))
        ids = [node.id for node in ordered]
        if len(ids) != len(set(ids)):
            raise ValueError("inventory contains duplicate node ids")
        known = set(ids)
        dangling = sorted(
            (node.id, relation.target)
            for node in ordered
            for relation in node.relations
            if relation.target not in known
        )
        if dangling:
            raise ValueError(f"inventory contains dangling relations: {dangling!r}")
        object.__setattr__(self, "nodes", ordered)

    def get(self, node_id: str) -> Node:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)

    def select(self, node_ids: tuple[str, ...]) -> tuple[Node, ...]:
        requested = tuple(dict.fromkeys(node_ids))
        selected = tuple(self.get(node_id) for node_id in requested)
        return tuple(sorted(selected, key=lambda node: node.id))


@dataclass(frozen=True, slots=True)
class PlanningRequest:
    verb: str
    inventory: Inventory
    selected_node_ids: tuple[str, ...]
    parameters: dict[str, str] = field(default_factory=dict)
    initial_constraints: frozenset[Constraint] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "verb", _required(self.verb, "verb"))
        selected = tuple(sorted(dict.fromkeys(self.selected_node_ids)))
        self.inventory.select(selected)
        object.__setattr__(self, "selected_node_ids", selected)
        object.__setattr__(
            self, "parameters", MappingProxyType(dict(sorted(self.parameters.items())))
        )


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """A fully described action. The executor must not reinterpret it."""

    id: str
    driver: str
    verb: str
    operation: str
    node_ids: tuple[str, ...]
    requested_node_ids: tuple[str, ...] = ()
    requires: frozenset[Constraint] = frozenset()
    produces: frozenset[Constraint] = frozenset()
    claims: frozenset[ActionClaim] = frozenset()
    command: tuple[str, ...] | None = None
    environment: dict[str, str] = field(default_factory=dict)
    changes_structure: bool = False

    def __post_init__(self) -> None:
        for name in ("id", "driver", "verb", "operation"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "node_ids", tuple(sorted(dict.fromkeys(self.node_ids))))
        requested = tuple(sorted(dict.fromkeys(self.requested_node_ids)))
        if not set(requested).issubset(self.node_ids):
            raise ValueError("requested nodes must be covered by the action")
        object.__setattr__(self, "requested_node_ids", requested)
        object.__setattr__(
            self, "environment", MappingProxyType(dict(sorted(self.environment.items())))
        )
        if self.command is not None and not self.command:
            raise ValueError("command must contain at least an executable")


@dataclass(frozen=True, slots=True, order=True)
class RejectedCandidate:
    driver: str
    operation: str
    reason: str
    node_ids: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DriverProposal:
    driver: str
    actions: tuple[ActionSpec, ...] = ()
    rejected: tuple[RejectedCandidate, ...] = ()


class PlanStatus(StrEnum):
    EXECUTABLE = "executable"
    EMPTY = "empty"
    BLOCKED = "blocked"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True, order=True)
class PlanDiagnostic:
    code: str
    message: str
    action_id: str | None = None


@dataclass(frozen=True, slots=True)
class Plan:
    id: str
    verb: str
    selected_node_ids: tuple[str, ...]
    actions: tuple[ActionSpec, ...]
    rejected: tuple[RejectedCandidate, ...]
    diagnostics: tuple[PlanDiagnostic, ...]
    status: PlanStatus
    initial_constraints: frozenset[Constraint] = frozenset()

    @property
    def ready_action_ids(self) -> tuple[str, ...]:
        available = self.initial_constraints
        return tuple(action.id for action in self.actions if action.requires.issubset(available))
