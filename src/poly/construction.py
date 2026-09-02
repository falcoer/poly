"""Construction plans for editing the root-owned workspace composition."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from poly.driver import (
    DRIVER_API_VERSION,
    DriverCapability,
    DriverExecutionResult,
    DriverManifest,
    DriverRegistration,
    ExecutionContext,
    FacadeArgument,
    FacadeRequest,
)
from poly.model import (
    ActionClaim,
    ActionSpec,
    Constraint,
    DriverProposal,
    JsonValue,
    Plan,
    PlanningRequest,
    PlanStatus,
    RejectedCandidate,
)
from poly.workspace import (
    WORKSPACE_MANIFEST,
    WORKSPACE_SCHEMA,
    LockedSource,
    SourceDeclaration,
    WorkspaceError,
    add_manifest_node,
    compile_workspace,
    create_workspace_files,
    remove_manifest_node,
    set_manifest_node_natures,
    validate_initialization_target,
    validate_manifest_value,
    validate_workspace,
    workspace_id,
)

CONSTRUCTOR_DRIVER_NAME = "poly.constructor"


class ConstructionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ModuleAddFacade:
    """User-facing syntax for declaring a filesystem module."""

    name: str = "module"
    verb: str = "add"
    description: str = "add a module to the workspace composition"
    arguments: tuple[FacadeArgument, ...] = (
        FacadeArgument("node_id", ("node_id",), required=True),
        FacadeArgument("node_path", ("--path",), required=True, help="workspace-relative path"),
        FacadeArgument("parent", ("--parent",), help="parent node"),
        FacadeArgument("nature", ("--nature",), repeatable=True, help="declared nature"),
    )

    def translate(self, request: FacadeRequest) -> dict[str, str]:
        parameters = dict(request.parameters)
        parameters.update(
            {
                "poly.node.id": _facade_string(request, "node_id"),
                "poly.node.path": _facade_string(request, "node_path"),
                "poly.node.kind": "module",
                "poly.node.natures": ",".join(_facade_values(request, "nature")),
            }
        )
        parent = request.values.get("parent")
        if isinstance(parent, str) and parent:
            parameters["poly.node.parent"] = parent
        return parameters


@dataclass(frozen=True, slots=True)
class ConstructionPlanningProvider:
    """Negotiate structural changes through the public driver planning API."""

    name: str = CONSTRUCTOR_DRIVER_NAME
    verbs: frozenset[str] = frozenset(("add", "init", "nature-add", "nature-remove", "remove"))

    def propose(self, request: PlanningRequest) -> DriverProposal:
        try:
            if request.verb == "init":
                return DriverProposal(self.name, (self._init(request),))
            if request.verb == "add":
                return DriverProposal(self.name, (self._add(request),))
            if request.verb == "remove":
                return DriverProposal(self.name, (self._remove(request),))
            if request.verb in {"nature-add", "nature-remove"}:
                return DriverProposal(self.name, (self._nature(request),))
        except ConstructionError as error:
            return DriverProposal(
                self.name,
                rejected=(
                    RejectedCandidate(self.name, f"poly/construction/{request.verb}", str(error)),
                ),
            )
        return DriverProposal(self.name)

    def _init(self, request: PlanningRequest) -> ActionSpec:
        name = request.parameters.get("poly.name", "Workspace").strip()
        if not name:
            raise ConstructionError("workspace name must not be empty")
        initialized = any("poly/workspace" in node.natures for node in request.inventory.nodes)
        operation = "poly/construction/reconcile" if initialized else "poly/construction/init"
        environment = (
            {}
            if initialized
            else {
                "poly.workspace.id": workspace_id(name),
                "poly.workspace.name": name,
            }
        )
        return ActionSpec(
            "construct.reconcile" if initialized else "construct.init",
            self.name,
            "init",
            operation,
            (),
            claims=frozenset((ActionClaim(operation, "workspace:."),)),
            environment=environment,
            changes_structure=True,
            required_capability="workspace.construct",
        )

    def _add(self, request: PlanningRequest) -> ActionSpec:
        node_id = _required_parameter(request, "poly.node.id")
        path = _required_parameter(request, "poly.node.path")
        kind = request.parameters.get("poly.node.kind", "module")
        if kind not in {"module", "repository"}:
            raise ConstructionError(f"unsupported node kind: {kind!r}")
        parent = request.parameters.get("poly.node.parent") or _root_node_id(request)
        natures = tuple(
            sorted(
                item.strip()
                for item in request.parameters.get("poly.node.natures", "").split(",")
                if item.strip()
            )
        )
        spec: dict[str, JsonValue] = {
            "id": node_id,
            "parent": parent,
            "kind": kind,
            "path": path,
        }
        if natures:
            spec["natures"] = list(natures)
        repository = request.parameters.get("poly.source.url")
        if repository:
            if kind != "repository":
                raise ConstructionError("a Git source requires node kind 'repository'")
            source: dict[str, JsonValue] = {"driver": "git", "url": repository}
            requested_ref = request.parameters.get("poly.source.ref")
            if requested_ref:
                source["ref"] = requested_ref
            spec["source"] = source
        resolution_key = f"poly/source-resolved:{node_id}"
        manifest_key = f"poly/manifest-added:{node_id}"
        return ActionSpec(
            f"construct.add:{node_id}",
            self.name,
            "add",
            "poly/construction/add",
            (),
            requires=(frozenset((Constraint(resolution_key),)) if repository else frozenset()),
            produces=frozenset((Constraint(manifest_key),)),
            claims=frozenset(
                (
                    ActionClaim("poly/construction/add", f"node:{node_id}"),
                    ActionClaim("poly/construction/path", f"path:{path}"),
                )
            ),
            environment={"poly.node.spec": json.dumps(spec, sort_keys=True)},
            changes_structure=True,
            required_capability="workspace.construct",
        )

    def _remove(self, request: PlanningRequest) -> ActionSpec:
        node_id = _required_parameter(request, "poly.node.id")
        return ActionSpec(
            f"construct.remove:{node_id}",
            self.name,
            "remove",
            "poly/construction/remove",
            (),
            claims=frozenset((ActionClaim("poly/construction/remove", f"node:{node_id}"),)),
            environment={"poly.node.id": node_id},
            changes_structure=True,
            required_capability="workspace.construct",
        )

    def _nature(self, request: PlanningRequest) -> ActionSpec:
        if len(request.selected_node_ids) != 1:
            raise ConstructionError("nature management requires exactly one selected node")
        node_id = request.selected_node_ids[0]
        natures = tuple(
            sorted(
                item.strip()
                for item in request.parameters.get("poly.node.natures", "").split(",")
                if item.strip()
            )
        )
        if not natures:
            raise ConstructionError("at least one nature is required")
        operation = f"poly/construction/{request.verb}"
        return ActionSpec(
            f"construct.{request.verb}:{node_id}",
            self.name,
            request.verb,
            operation,
            (node_id,),
            requested_node_ids=(node_id,),
            claims=frozenset((ActionClaim(operation, f"node:{node_id}"),)),
            environment={
                "poly.node.id": node_id,
                "poly.node.natures": json.dumps(natures),
            },
            changes_structure=True,
            required_capability="workspace.construct",
        )


@dataclass(frozen=True, slots=True)
class ConstructionPlanner:
    def plan_init(self, workspace: Path, name: str) -> Plan:
        workspace = workspace.resolve()
        if not workspace.is_dir():
            raise ConstructionError(f"workspace does not exist: {workspace}")
        normalized_name = name.strip()
        if not normalized_name:
            raise ConstructionError("workspace name must not be empty")
        try:
            if (workspace / WORKSPACE_MANIFEST).is_file():
                validate_workspace(workspace)
                action = ActionSpec(
                    "construct.reconcile",
                    CONSTRUCTOR_DRIVER_NAME,
                    "init",
                    "poly/construction/reconcile",
                    (),
                    claims=frozenset((ActionClaim("poly/construction/reconcile", "workspace:."),)),
                    changes_structure=True,
                    required_capability="workspace.construct",
                )
                return _construction_plan("init", (action,))
            validate_initialization_target(workspace)
            identifier = workspace_id(normalized_name)
        except WorkspaceError as error:
            raise ConstructionError(str(error)) from error
        action = ActionSpec(
            "construct.init",
            CONSTRUCTOR_DRIVER_NAME,
            "init",
            "poly/construction/init",
            (),
            claims=frozenset((ActionClaim("poly/construction/init", "workspace:."),)),
            environment={
                "poly.workspace.id": identifier,
                "poly.workspace.name": normalized_name,
            },
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
        *,
        parent: str | None = None,
        kind: str = "module",
    ) -> Plan:
        try:
            compiled = validate_workspace(workspace)
            parent_id = parent or compiled.manifest.root_node
            value = compiled.manifest.semantic()
            nodes = value["nodes"]
            assert isinstance(nodes, list)
            spec: dict[str, JsonValue] = {
                "id": node_id,
                "parent": parent_id,
                "kind": kind,
                "path": path,
            }
            if natures:
                spec["natures"] = list(natures)
            nodes.append(spec)
            validate_manifest_value(workspace, value)
        except WorkspaceError as error:
            raise ConstructionError(str(error)) from error
        action = ActionSpec(
            f"construct.add:{node_id}",
            CONSTRUCTOR_DRIVER_NAME,
            "add",
            "poly/construction/add",
            (),
            claims=frozenset(
                (
                    ActionClaim("poly/construction/add", f"node:{node_id}"),
                    ActionClaim("poly/construction/path", f"path:{path}"),
                )
            ),
            environment={"poly.node.spec": json.dumps(spec, sort_keys=True)},
            changes_structure=True,
            required_capability="workspace.construct",
        )
        return _construction_plan("add", (action,))

    def plan_remove(self, workspace: Path, node_id: str) -> Plan:
        try:
            compiled = validate_workspace(workspace)
            if node_id == compiled.manifest.root_node:
                raise WorkspaceError("the root node cannot be removed")
            compiled.manifest.get(node_id)
            children = sorted(node.id for node in compiled.manifest.nodes if node.parent == node_id)
            if children:
                raise WorkspaceError(f"node {node_id!r} still owns children: {children!r}")
        except KeyError as error:
            raise ConstructionError(f"unknown node: {node_id!r}") from error
        except WorkspaceError as error:
            raise ConstructionError(str(error)) from error
        action = ActionSpec(
            f"construct.remove:{node_id}",
            CONSTRUCTOR_DRIVER_NAME,
            "remove",
            "poly/construction/remove",
            (),
            claims=frozenset((ActionClaim("poly/construction/remove", f"node:{node_id}"),)),
            environment={"poly.node.id": node_id},
            changes_structure=True,
            required_capability="workspace.construct",
        )
        return _construction_plan("remove", (action,))


@dataclass(frozen=True, slots=True)
class ConstructionActionHandler:
    name: str = CONSTRUCTOR_DRIVER_NAME

    def execute(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        try:
            if action.operation == "poly/construction/init":
                return self._init(action, context)
            if action.operation == "poly/construction/reconcile":
                compile_workspace(context.workspace)
                return DriverExecutionResult(True, "reconciled Poly workspace")
            if action.operation == "poly/construction/add":
                return self._add(action, context)
            if action.operation == "poly/construction/remove":
                return self._remove(action, context)
            if action.operation in {
                "poly/construction/nature-add",
                "poly/construction/nature-remove",
            }:
                return self._nature(action, context)
            return DriverExecutionResult(
                False, f"unsupported construction operation: {action.operation}"
            )
        except (KeyError, OSError, json.JSONDecodeError, WorkspaceError) as error:
            return DriverExecutionResult(False, str(error))

    def _init(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        name = action.environment.get("poly.workspace.name", "").strip()
        identifier = action.environment.get("poly.workspace.id", "").strip()
        create_workspace_files(context.workspace, identifier, name)
        return DriverExecutionResult(True, f"initialized Poly workspace {name!r}")

    def _add(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        spec = json.loads(action.environment["poly.node.spec"])
        if not isinstance(spec, dict):
            raise WorkspaceError("node specification must be a mapping")
        node_id = str(spec["id"])
        natures_value = spec.get("natures", [])
        if not isinstance(natures_value, list) or not all(
            isinstance(nature, str) for nature in natures_value
        ):
            raise WorkspaceError("node natures must be a string list")
        source_value = spec.get("source")
        source = None
        locked = None
        if source_value is not None:
            if not isinstance(source_value, dict):
                raise WorkspaceError("node source must be a mapping")
            source = SourceDeclaration(
                str(source_value["driver"]),
                str(source_value["url"]),
                str(source_value["ref"]) if "ref" in source_value else None,
            )
            resolution_path = context.run_directory / "resolutions" / f"{node_id}.json"
            resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
            if not isinstance(resolution, dict):
                raise WorkspaceError("source resolution must be a mapping")
            locked = LockedSource(
                node_id,
                source.driver,
                source.url,
                source.ref,
                str(resolution["commit"]),
                str(resolution["ref-kind"]),
            )
        compiled = add_manifest_node(
            context.workspace,
            node_id=node_id,
            parent=str(spec["parent"]),
            kind=str(spec["kind"]),
            path=str(spec["path"]),
            natures=tuple(natures_value),
            source=source,
            locked_source=locked,
        )
        return DriverExecutionResult(
            True,
            f"added node {node_id!r}",
            {"path": compiled.manifest.get(node_id).workspace_path},
        )

    def _remove(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        node_id = action.environment["poly.node.id"]
        remove_manifest_node(context.workspace, node_id)
        return DriverExecutionResult(True, f"removed node {node_id!r}")

    def _nature(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        node_id = action.environment["poly.node.id"]
        value = json.loads(action.environment["poly.node.natures"])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise WorkspaceError("node natures must be a string list")
        add = action.operation.endswith("nature-add")
        compiled = set_manifest_node_natures(context.workspace, node_id, tuple(value), add=add)
        current = compiled.manifest.get(node_id).natures
        verb = "added to" if add else "removed from"
        return DriverExecutionResult(
            True,
            f"natures {', '.join(value)} {verb} {node_id!r}",
            {"natures": list(current)},
        )


def constructor_driver() -> DriverRegistration:
    return DriverRegistration(
        DriverManifest(
            CONSTRUCTOR_DRIVER_NAME,
            "0.2.0",
            DRIVER_API_VERSION,
            frozenset((DriverCapability.FACADE, DriverCapability.PLAN, DriverCapability.EXECUTE)),
            "Poly root workspace composition action handler",
            ("poly/module", "poly/repository", "poly/workspace"),
        ),
        planners=(ConstructionPlanningProvider(),),
        handlers=(ConstructionActionHandler(),),
        facades=(ModuleAddFacade(),),
    )


def _facade_string(request: FacadeRequest, name: str) -> str:
    value = request.values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ConstructionError(f"facade argument {name!r} is required")
    return value


def _facade_values(request: FacadeRequest, name: str) -> tuple[str, ...]:
    value = request.values.get(name)
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    return (value,)


def read_workspace_definition(workspace: Path) -> dict[str, JsonValue]:
    try:
        return validate_workspace(workspace).manifest.semantic()
    except WorkspaceError as error:
        raise ConstructionError(str(error)) from error


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


def _required_parameter(request: PlanningRequest, name: str) -> str:
    value: str = request.parameters.get(name, "").strip()
    if not value:
        raise ConstructionError(f"missing required parameter: {name}")
    return value


def _root_node_id(request: PlanningRequest) -> str:
    roots = [node.id for node in request.inventory.nodes if "poly/workspace" in node.natures]
    if len(roots) != 1:
        raise ConstructionError("workspace root node is unavailable")
    return str(roots[0])


__all__ = [
    "CONSTRUCTOR_DRIVER_NAME",
    "WORKSPACE_MANIFEST",
    "WORKSPACE_SCHEMA",
    "ConstructionActionHandler",
    "ConstructionError",
    "ConstructionPlanner",
    "ConstructionPlanningProvider",
    "constructor_driver",
    "read_workspace_definition",
]
