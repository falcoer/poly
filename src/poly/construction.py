"""Construction plans for creating and extending Poly workspaces."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from poly.driver import (
    DRIVER_API_VERSION,
    DriverCapability,
    DriverExecutionResult,
    DriverManifest,
    DriverRegistration,
    ExecutionContext,
)
from poly.model import ActionClaim, ActionSpec, JsonValue, Plan, PlanStatus

CONSTRUCTOR_DRIVER_NAME = "poly.constructor"
WORKSPACE_SCHEMA = "poly.workspace/v1"
WORKSPACE_MANIFEST = ".poly/workspace.json"


class ConstructionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ConstructionPlanner:
    def plan_init(self, workspace: Path, name: str) -> Plan:
        workspace = workspace.resolve()
        if not workspace.is_dir():
            raise ConstructionError(f"workspace does not exist: {workspace}")
        if not name.strip():
            raise ConstructionError("workspace name must not be empty")
        manifest = workspace / WORKSPACE_MANIFEST
        if manifest.exists():
            raise ConstructionError(f"workspace is already initialized: {manifest}")
        action = ActionSpec(
            "construct.init",
            CONSTRUCTOR_DRIVER_NAME,
            "init",
            "poly/construction/init",
            (),
            claims=frozenset((ActionClaim("poly/construction/init", "workspace:."),)),
            environment={"poly.workspace.name": name.strip()},
            changes_structure=True,
            required_capability="workspace.construct",
        )
        return _construction_plan("init", (action,))

    def plan_add(
        self,
        workspace: Path,
        node_id: str,
        path: str,
        natures: tuple[str, ...] = (),
    ) -> Plan:
        definition = read_workspace_definition(workspace)
        normalized_path = _relative_path(path)
        normalized_id = node_id.strip()
        if not normalized_id or any(character.isspace() for character in normalized_id):
            raise ConstructionError("node id must be non-empty and contain no whitespace")
        nodes = definition.get("nodes")
        if not isinstance(nodes, list):
            raise ConstructionError("workspace manifest nodes must be a list")
        if any(isinstance(node, dict) and node.get("id") == normalized_id for node in nodes):
            raise ConstructionError(f"node already exists: {normalized_id!r}")
        if any(isinstance(node, dict) and node.get("path") == normalized_path for node in nodes):
            raise ConstructionError(f"node path already exists: {normalized_path!r}")
        nature_values: list[JsonValue] = [nature for nature in sorted(set(natures))]
        spec: dict[str, JsonValue] = {
            "id": normalized_id,
            "path": normalized_path,
            "natures": nature_values,
        }
        action = ActionSpec(
            f"construct.add:{normalized_id}",
            CONSTRUCTOR_DRIVER_NAME,
            "add",
            "poly/construction/add",
            (),
            claims=frozenset(
                (
                    ActionClaim("poly/construction/add", f"node:{normalized_id}"),
                    ActionClaim("poly/construction/path", f"path:{normalized_path}"),
                )
            ),
            environment={"poly.node.spec": json.dumps(spec, sort_keys=True)},
            changes_structure=True,
            required_capability="workspace.construct",
        )
        return _construction_plan("add", (action,))


@dataclass(frozen=True, slots=True)
class ConstructionActionHandler:
    name: str = CONSTRUCTOR_DRIVER_NAME

    def execute(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        if action.operation == "poly/construction/init":
            return self._init(action, context)
        if action.operation == "poly/construction/add":
            return self._add(action, context)
        return DriverExecutionResult(
            False, f"unsupported construction operation: {action.operation}"
        )

    def _init(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        manifest = context.workspace / WORKSPACE_MANIFEST
        if manifest.exists():
            return DriverExecutionResult(False, "workspace is already initialized")
        name = action.environment.get("poly.workspace.name", "").strip()
        if not name:
            return DriverExecutionResult(False, "construction action has no workspace name")
        definition: dict[str, JsonValue] = {
            "schema": WORKSPACE_SCHEMA,
            "name": name,
            "nodes": [],
        }
        _write_json(manifest, definition)
        (context.workspace / ".poly" / "state").mkdir(parents=True, exist_ok=True)
        (context.workspace / ".poly" / "runs").mkdir(parents=True, exist_ok=True)
        return DriverExecutionResult(True, f"initialized Poly workspace {name!r}")

    def _add(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        try:
            spec = json.loads(action.environment["poly.node.spec"])
            if not isinstance(spec, dict):
                raise ConstructionError("node specification must be an object")
            node_id = str(spec["id"])
            path = _relative_path(str(spec["path"]))
            natures_value = spec.get("natures", [])
            if not isinstance(natures_value, list) or not all(
                isinstance(nature, str) for nature in natures_value
            ):
                raise ConstructionError("node natures must be a string list")
            definition = read_workspace_definition(context.workspace)
            nodes = definition["nodes"]
            if not isinstance(nodes, list):
                raise ConstructionError("workspace manifest nodes must be a list")
            if any(isinstance(node, dict) and node.get("id") == node_id for node in nodes):
                return DriverExecutionResult(False, f"node already exists: {node_id!r}")
            nodes.append({"id": node_id, "path": path, "natures": sorted(natures_value)})
            nodes.sort(key=lambda node: str(node.get("id")) if isinstance(node, dict) else "")
            (context.workspace / path).mkdir(parents=True, exist_ok=True)
            _write_json(context.workspace / WORKSPACE_MANIFEST, definition)
        except (KeyError, OSError, json.JSONDecodeError, ConstructionError) as error:
            return DriverExecutionResult(False, str(error))
        return DriverExecutionResult(True, f"added node {node_id!r}", {"path": path})


def constructor_driver() -> DriverRegistration:
    return DriverRegistration(
        DriverManifest(
            CONSTRUCTOR_DRIVER_NAME,
            "0.1.0",
            DRIVER_API_VERSION,
            frozenset((DriverCapability.EXECUTE,)),
            "Poly workspace construction action handler",
        ),
        handlers=(ConstructionActionHandler(),),
    )


def read_workspace_definition(workspace: Path) -> dict[str, JsonValue]:
    manifest = workspace.resolve() / WORKSPACE_MANIFEST
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConstructionError(f"workspace is not initialized: {manifest}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ConstructionError(f"cannot read workspace manifest: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != WORKSPACE_SCHEMA:
        raise ConstructionError("workspace manifest has an unsupported schema")
    if not isinstance(value.get("name"), str) or not isinstance(value.get("nodes"), list):
        raise ConstructionError("workspace manifest is malformed")
    return value


def _construction_plan(verb: str, actions: tuple[ActionSpec, ...]) -> Plan:
    payload = json.dumps(
        [
            {
                "id": action.id,
                "verb": action.verb,
                "operation": action.operation,
                "environment": dict(action.environment),
                "capability": action.required_capability,
            }
            for action in actions
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    plan_id = hashlib.sha256(payload.encode()).hexdigest()[:20]
    return Plan(plan_id, verb, (), actions, (), (), PlanStatus.EXECUTABLE)


def _relative_path(value: str) -> str:
    path = PurePosixPath(value.strip())
    if not value.strip() or path.is_absolute() or ".." in path.parts or path.as_posix() == ".":
        raise ConstructionError(f"node path must be a non-root workspace-relative path: {value!r}")
    return path.as_posix()


def _write_json(path: Path, value: dict[str, JsonValue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
