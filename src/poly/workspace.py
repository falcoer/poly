"""Versioned authored workspace files and rebuildable compiled state."""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from io import StringIO
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from poly.model import Inventory, JsonValue, Metadata, Node, NodeRelation

WORKSPACE_SCHEMA = "poly.workspace/v1"
WORKSPACE_LOCK_SCHEMA = "poly.workspace-lock/v1"
WORKSPACE_STATE_SCHEMA = "poly.workspace-state/v1"
WORKSPACE_MANIFEST = "poly.yaml"
WORKSPACE_LOCK = "poly.lock.yaml"
PROVISIONAL_WORKSPACE_MANIFEST = ".poly/workspace.json"
COMPILED_WORKSPACE = ".poly/state/workspace.json"

MANAGED_IGNORE_BEGIN = "# BEGIN poly managed"
MANAGED_IGNORE_END = "# END poly managed"

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_COMMIT = re.compile(r"[0-9a-fA-F]{40,64}\Z")
_KINDS = frozenset(("workspace", "repository", "module"))
_MANIFEST_FIELDS = frozenset(("schema", "workspace", "nodes"))
_WORKSPACE_FIELDS = frozenset(("id", "name", "root-node"))
_NODE_FIELDS = frozenset(("id", "parent", "kind", "path", "source", "natures"))
_SOURCE_FIELDS = frozenset(("driver", "url", "ref"))
_LOCK_FIELDS = frozenset(("schema", "manifest-digest", "sources"))
_LOCK_SOURCE_FIELDS = frozenset(("driver", "url", "requested-ref", "resolved"))
_RESOLVED_FIELDS = frozenset(("commit", "ref-kind"))


class WorkspaceError(ValueError):
    """An authored workspace file is unsafe or incompatible."""


@dataclass(frozen=True, slots=True)
class SourceDeclaration:
    driver: str
    url: str
    ref: str | None = None

    def semantic(self) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = {"driver": self.driver, "url": self.url}
        if self.ref is not None:
            value["ref"] = self.ref
        return value


@dataclass(frozen=True, slots=True)
class WorkspaceNode:
    id: str
    kind: str
    path: str
    workspace_path: str
    parent: str | None = None
    source: SourceDeclaration | None = None
    natures: tuple[str, ...] = ()

    def semantic(self) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = {
            "id": self.id,
            "kind": self.kind,
            "path": self.path,
        }
        if self.parent is not None:
            value["parent"] = self.parent
        if self.source is not None:
            value["source"] = self.source.semantic()
        if self.natures:
            value["natures"] = list(self.natures)
        return value


@dataclass(frozen=True, slots=True)
class WorkspaceManifest:
    id: str
    root_node: str
    nodes: tuple[WorkspaceNode, ...]
    name: str | None = None

    @property
    def digest(self) -> str:
        payload = json.dumps(
            self.semantic(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"

    def semantic(self) -> dict[str, JsonValue]:
        workspace: dict[str, JsonValue] = {"id": self.id, "root-node": self.root_node}
        if self.name is not None:
            workspace["name"] = self.name
        return {
            "schema": WORKSPACE_SCHEMA,
            "workspace": workspace,
            "nodes": [node.semantic() for node in sorted(self.nodes, key=lambda item: item.id)],
        }

    def get(self, node_id: str) -> WorkspaceNode:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)


@dataclass(frozen=True, slots=True)
class LockedSource:
    node_id: str
    driver: str
    url: str
    requested_ref: str | None
    commit: str
    ref_kind: str

    def semantic(self) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = {
            "driver": self.driver,
            "url": self.url,
            "resolved": {"commit": self.commit, "ref-kind": self.ref_kind},
        }
        if self.requested_ref is not None:
            value["requested-ref"] = self.requested_ref
        return value


@dataclass(frozen=True, slots=True)
class WorkspaceLock:
    manifest_digest: str
    sources: tuple[LockedSource, ...] = ()

    def semantic(self) -> dict[str, JsonValue]:
        return {
            "schema": WORKSPACE_LOCK_SCHEMA,
            "manifest-digest": self.manifest_digest,
            "sources": {
                source.node_id: source.semantic()
                for source in sorted(self.sources, key=lambda item: item.node_id)
            },
        }


@dataclass(frozen=True, slots=True)
class CompiledWorkspace:
    manifest: WorkspaceManifest
    lock: WorkspaceLock

    @property
    def inventory(self) -> Inventory:
        locked = {source.node_id: source for source in self.lock.sources}
        return Inventory(
            tuple(_declared_node(node, locked.get(node.id)) for node in self.manifest.nodes)
        )


def load_manifest(workspace: Path) -> WorkspaceManifest:
    workspace = workspace.resolve()
    _reject_provisional_manifest(workspace)
    if not (workspace / WORKSPACE_MANIFEST).is_file():
        raise WorkspaceError(f"workspace is not initialized: {workspace / WORKSPACE_MANIFEST}")
    raw = _load_yaml(workspace / WORKSPACE_MANIFEST)
    return _parse_manifest(raw, workspace)


def load_lock(workspace: Path, manifest: WorkspaceManifest) -> WorkspaceLock:
    raw = _load_yaml(workspace.resolve() / WORKSPACE_LOCK)
    return _parse_lock(raw, manifest)


def validate_workspace(workspace: Path) -> CompiledWorkspace:
    workspace = workspace.resolve()
    manifest = load_manifest(workspace)
    lock = load_lock(workspace, manifest)
    _managed_ignore_parts(workspace / ".gitignore")
    return CompiledWorkspace(manifest, lock)


def validate_initialization_target(workspace: Path) -> None:
    workspace = workspace.resolve()
    if (workspace / WORKSPACE_MANIFEST).exists() or (workspace / WORKSPACE_LOCK).exists():
        raise WorkspaceError("workspace authored files already exist")
    _reject_provisional_manifest(workspace)
    _managed_ignore_parts(workspace / ".gitignore")


def validate_manifest_value(workspace: Path, value: object) -> WorkspaceManifest:
    return _parse_manifest(value, workspace.resolve())


def compile_workspace(workspace: Path) -> CompiledWorkspace:
    """Validate authored files, reconcile ignore rules, and write disposable state."""

    workspace = workspace.resolve()
    compiled = validate_workspace(workspace)
    reconcile_gitignore(workspace, compiled.manifest)
    _atomic_json(workspace / COMPILED_WORKSPACE, _compiled_state(compiled))
    return compiled


def _compiled_state(compiled: CompiledWorkspace) -> dict[str, JsonValue]:
    return {
        "schema": WORKSPACE_STATE_SCHEMA,
        "manifest-digest": compiled.manifest.digest,
        "workspace": {
            "id": compiled.manifest.id,
            "name": compiled.manifest.name,
            "root-node": compiled.manifest.root_node,
        },
        "nodes": [
            {
                **node.semantic(),
                "workspace-path": node.workspace_path,
                "state": "declared",
            }
            for node in sorted(compiled.manifest.nodes, key=lambda item: item.id)
        ],
        "lock": compiled.lock.semantic(),
    }


def reconcile_inventory(
    declared: CompiledWorkspace | None, observations: tuple[Node, ...]
) -> Inventory:
    if declared is None:
        return Inventory(observations)

    manifest = declared.manifest
    locked = {source.node_id: source for source in declared.lock.sources}
    nodes_by_id = {node.id: _declared_node(node, locked.get(node.id)) for node in manifest.nodes}
    id_map: dict[str, str] = {}
    for observed in observations:
        target = _declared_identity(manifest, observed)
        id_map[observed.id] = target or observed.id

    for observed in observations:
        target_id = id_map[observed.id]
        relations = tuple(
            NodeRelation(relation.kind, id_map.get(relation.target, relation.target))
            for relation in observed.relations
            if id_map.get(relation.target, relation.target) != target_id
        )
        if target_id in nodes_by_id:
            nodes_by_id[target_id] = _merge_node(nodes_by_id[target_id], observed, relations)
        else:
            metadata = dict(observed.metadata)
            metadata["poly.state"] = "observed-only"
            nodes_by_id[target_id] = Node(
                target_id,
                observed.path,
                observed.natures,
                metadata,
                relations,
            )
    return Inventory(tuple(nodes_by_id.values()))


def create_workspace_files(workspace: Path, workspace_id: str, name: str) -> CompiledWorkspace:
    workspace = workspace.resolve()
    validate_initialization_target(workspace)
    root_id = "root"
    manifest = WorkspaceManifest(
        _identifier(workspace_id, "workspace id"),
        root_id,
        (WorkspaceNode(root_id, "workspace", ".", "."),),
        _non_empty(name, "workspace name"),
    )
    lock = WorkspaceLock(manifest.digest)
    _write_yaml(workspace / WORKSPACE_MANIFEST, manifest.semantic())
    _write_yaml(workspace / WORKSPACE_LOCK, lock.semantic())
    return compile_workspace(workspace)


def add_manifest_node(
    workspace: Path,
    *,
    node_id: str,
    parent: str,
    kind: str,
    path: str,
    natures: tuple[str, ...] = (),
    source: SourceDeclaration | None = None,
    locked_source: LockedSource | None = None,
) -> CompiledWorkspace:
    workspace = workspace.resolve()
    validate_workspace(workspace)
    raw_manifest = _load_yaml(workspace / WORKSPACE_MANIFEST)
    raw_lock = _load_yaml(workspace / WORKSPACE_LOCK)
    nodes = _mapping_sequence(raw_manifest, "nodes", "manifest nodes")
    specification: CommentedMap = CommentedMap()
    specification["id"] = node_id
    specification["parent"] = parent
    specification["kind"] = kind
    specification["path"] = path
    if source is not None:
        specification["source"] = CommentedMap(source.semantic())
    if natures:
        specification["natures"] = CommentedSeq(natures)
    nodes.append(specification)
    candidate = _parse_manifest(raw_manifest, workspace)
    if source is not None:
        if locked_source is None or locked_source.node_id != node_id:
            raise WorkspaceError(f"source node {node_id!r} requires a resolved lock entry")
        sources = _mapping_value(raw_lock, "sources", "lock sources")
        sources[node_id] = CommentedMap(locked_source.semantic())
    _update_lock_for_manifest(raw_lock, candidate)
    return _commit_workspace_files(workspace, raw_manifest, raw_lock)


def set_manifest_node_natures(
    workspace: Path, node_id: str, natures: tuple[str, ...], *, add: bool
) -> CompiledWorkspace:
    """Atomically add or remove authored nature assertions on one node."""

    workspace = workspace.resolve()
    validate_workspace(workspace)
    normalized = tuple(sorted({_non_empty(item, "nature") for item in natures}))
    if not normalized:
        raise WorkspaceError("at least one nature is required")
    raw_manifest = _load_yaml(workspace / WORKSPACE_MANIFEST)
    raw_lock = _load_yaml(workspace / WORKSPACE_LOCK)
    nodes = _mapping_sequence(raw_manifest, "nodes", "manifest nodes")
    matches = [value for value in nodes if _mapping(value).get("id") == node_id]
    if len(matches) != 1:
        raise WorkspaceError(f"unknown node: {node_id!r}")
    node = _mapping(matches[0], f"node {node_id!r}")
    current = set(_string_tuple(node.get("natures", []), f"node {node_id!r}.natures"))
    if add:
        current.update(normalized)
    else:
        current.difference_update(normalized)
    if current:
        node["natures"] = CommentedSeq(sorted(current))
    else:
        node.pop("natures", None)
    candidate = _parse_manifest(raw_manifest, workspace)
    _update_lock_for_manifest(raw_lock, candidate)
    return _commit_workspace_files(workspace, raw_manifest, raw_lock)


def update_locked_sources(
    workspace: Path, resolutions: dict[str, tuple[str, str]]
) -> CompiledWorkspace:
    """Atomically replace selected immutable resolutions without changing intent."""

    workspace = workspace.resolve()
    compiled = validate_workspace(workspace)
    known = {source.node_id: source for source in compiled.lock.sources}
    unknown = sorted(set(resolutions) - set(known))
    if unknown:
        raise WorkspaceError(f"unknown locked source nodes: {unknown!r}")
    raw_lock = _load_yaml(workspace / WORKSPACE_LOCK)
    raw_sources = _mapping_value(raw_lock, "sources", "lock sources")
    for node_id, (commit, ref_kind) in sorted(resolutions.items()):
        if not _COMMIT.fullmatch(commit):
            raise WorkspaceError(f"lock source {node_id!r} has no immutable full Git commit")
        raw_source = _mapping(raw_sources[node_id], f"lock sources.{node_id}")
        raw_source["resolved"] = CommentedMap(
            {"commit": commit.lower(), "ref-kind": _non_empty(ref_kind, "ref-kind")}
        )
    _parse_lock(raw_lock, compiled.manifest)
    _write_yaml(workspace / WORKSPACE_LOCK, raw_lock)
    return compile_workspace(workspace)


def remove_manifest_node(workspace: Path, node_id: str) -> CompiledWorkspace:
    workspace = workspace.resolve()
    compiled = validate_workspace(workspace)
    if node_id == compiled.manifest.root_node:
        raise WorkspaceError("the root node cannot be removed")
    children = sorted(node.id for node in compiled.manifest.nodes if node.parent == node_id)
    if children:
        raise WorkspaceError(f"node {node_id!r} still owns children: {children!r}")
    raw_manifest = _load_yaml(workspace / WORKSPACE_MANIFEST)
    raw_lock = _load_yaml(workspace / WORKSPACE_LOCK)
    nodes = _mapping_sequence(raw_manifest, "nodes", "manifest nodes")
    matches = [index for index, value in enumerate(nodes) if _mapping(value).get("id") == node_id]
    if not matches:
        raise WorkspaceError(f"unknown node: {node_id!r}")
    del nodes[matches[0]]
    candidate = _parse_manifest(raw_manifest, workspace)
    sources = _mapping_value(raw_lock, "sources", "lock sources")
    sources.pop(node_id, None)
    _update_lock_for_manifest(raw_lock, candidate)
    _write_yaml(workspace / WORKSPACE_MANIFEST, raw_manifest)
    _write_yaml(workspace / WORKSPACE_LOCK, raw_lock)
    return compile_workspace(workspace)


def reconcile_gitignore(workspace: Path, manifest: WorkspaceManifest) -> Path:
    path = workspace.resolve() / ".gitignore"
    _atomic_text(path, _managed_gitignore_text(path, manifest))
    return path


def _managed_gitignore_text(path: Path, manifest: WorkspaceManifest) -> str:
    prefix, suffix = _managed_ignore_parts(path)
    repositories = sorted(
        {
            node.workspace_path
            for node in manifest.nodes
            if node.kind == "repository" and node.id != manifest.root_node
        },
        key=lambda value: (value.casefold(), value),
    )
    managed = [MANAGED_IGNORE_BEGIN, "/.poly/"]
    managed.extend(f"/{_escape_gitignore(item)}/" for item in repositories)
    managed.append(MANAGED_IGNORE_END)
    lines = list(prefix)
    if lines and lines[-1] != "":
        lines.append("")
    lines.extend(managed)
    if suffix:
        if suffix[0] != "":
            lines.append("")
        lines.extend(suffix)
    return "\n".join(lines).rstrip("\n") + "\n"


def _commit_workspace_files(
    workspace: Path, raw_manifest: CommentedMap, raw_lock: CommentedMap
) -> CompiledWorkspace:
    manifest = _parse_manifest(raw_manifest, workspace)
    lock = _parse_lock(raw_lock, manifest)
    compiled = CompiledWorkspace(manifest, lock)
    _atomic_text_set(
        {
            workspace / WORKSPACE_MANIFEST: _yaml_text(raw_manifest),
            workspace / WORKSPACE_LOCK: _yaml_text(raw_lock),
            workspace / ".gitignore": _managed_gitignore_text(workspace / ".gitignore", manifest),
            workspace / COMPILED_WORKSPACE: json.dumps(
                _compiled_state(compiled), indent=2, ensure_ascii=False, sort_keys=True
            )
            + "\n",
        }
    )
    return compiled


def workspace_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.strip().casefold()).strip("-._")
    return _identifier(normalized or "workspace", "workspace id")


def _parse_manifest(raw: object, workspace: Path) -> WorkspaceManifest:
    root = _mapping(raw, "manifest root")
    _known_fields(root, _MANIFEST_FIELDS, "manifest")
    if root.get("schema") != WORKSPACE_SCHEMA:
        raise WorkspaceError(f"unsupported workspace schema: {root.get('schema')!r}")
    workspace_value = _mapping(root.get("workspace"), "workspace")
    _known_fields(workspace_value, _WORKSPACE_FIELDS, "workspace")
    identifier = _identifier(workspace_value.get("id"), "workspace id")
    root_node = _identifier(workspace_value.get("root-node"), "workspace root-node")
    name_value = workspace_value.get("name")
    name = None if name_value is None else _non_empty(name_value, "workspace name")
    nodes_value = root.get("nodes")
    if not isinstance(nodes_value, list) or not nodes_value:
        raise WorkspaceError("manifest nodes must be a non-empty list")

    provisional: list[
        tuple[str, str | None, str, str, SourceDeclaration | None, tuple[str, ...]]
    ] = []
    seen: set[str] = set()
    for index, raw_node in enumerate(nodes_value):
        node = _mapping(raw_node, f"nodes[{index}]")
        _known_fields(node, _NODE_FIELDS, f"nodes[{index}]")
        node_id = _identifier(node.get("id"), f"nodes[{index}].id")
        if node_id in seen:
            raise WorkspaceError(f"duplicate node identifier: {node_id!r}")
        seen.add(node_id)
        kind = _string(node.get("kind"), f"nodes[{index}].kind")
        if kind not in _KINDS:
            raise WorkspaceError(f"nodes[{index}].kind is unsupported: {kind!r}")
        parent_value = node.get("parent")
        parent = (
            None if parent_value is None else _identifier(parent_value, f"nodes[{index}].parent")
        )
        path = _relative_path(node.get("path"), f"nodes[{index}].path")
        source = _parse_source(node.get("source"), f"nodes[{index}].source")
        natures = _string_tuple(node.get("natures", []), f"nodes[{index}].natures")
        provisional.append((node_id, parent, kind, path, source, natures))

    by_id = {item[0]: item for item in provisional}
    if root_node not in by_id:
        raise WorkspaceError(f"workspace root-node does not exist: {root_node!r}")
    roots = [item for item in provisional if item[1] is None]
    if len(roots) != 1 or roots[0][0] != root_node:
        raise WorkspaceError("manifest must contain exactly one parentless root node")
    if roots[0][2] != "workspace" or roots[0][3] != "." or roots[0][4] is not None:
        raise WorkspaceError("root node must be kind 'workspace', path '.', and have no source")
    for node_id, parent, kind, _path, source, _natures in provisional:
        if node_id != root_node and parent is None:
            raise WorkspaceError(f"non-root node has no parent: {node_id!r}")
        if parent is not None and parent not in by_id:
            raise WorkspaceError(f"node {node_id!r} has unknown parent {parent!r}")
        if kind == "workspace" and node_id != root_node:
            raise WorkspaceError("only the root node may use kind 'workspace'")
        if source is not None and kind != "repository":
            raise WorkspaceError(f"only repository nodes may declare a source: {node_id!r}")

    resolved: dict[str, str] = {}
    visiting: list[str] = []

    def resolve(node_id: str) -> str:
        if node_id in resolved:
            return resolved[node_id]
        if node_id in visiting:
            cycle = " -> ".join((*visiting[visiting.index(node_id) :], node_id))
            raise WorkspaceError(f"node parent cycle: {cycle}")
        visiting.append(node_id)
        _current_id, parent, _kind, path, _source, _natures = by_id[node_id]
        if parent is None:
            result = "."
        else:
            parent_path = resolve(parent)
            result_path = PurePosixPath(parent_path) / PurePosixPath(path)
            result = result_path.as_posix()
        visiting.pop()
        resolved[node_id] = result
        _safe_workspace_path(workspace, result, node_id)
        return result

    for node_id in sorted(by_id):
        resolve(node_id)
    _validate_collisions(provisional, resolved)
    nodes = tuple(
        WorkspaceNode(
            node_id,
            kind,
            path,
            resolved[node_id],
            parent,
            source,
            natures,
        )
        for node_id, parent, kind, path, source, natures in provisional
    )
    return WorkspaceManifest(identifier, root_node, nodes, name)


def _parse_lock(raw: object, manifest: WorkspaceManifest) -> WorkspaceLock:
    root = _mapping(raw, "lock root")
    _known_fields(root, _LOCK_FIELDS, "lock")
    if root.get("schema") != WORKSPACE_LOCK_SCHEMA:
        raise WorkspaceError(f"unsupported workspace lock schema: {root.get('schema')!r}")
    digest = _string(root.get("manifest-digest"), "lock manifest-digest")
    if digest != manifest.digest:
        raise WorkspaceError(f"workspace lock is stale: expected {manifest.digest}, found {digest}")
    sources_value = _mapping(root.get("sources"), "lock sources")
    source_ids = tuple(_identifier(node_id, "lock source identifier") for node_id in sources_value)
    declared_sources = {node.id: node for node in manifest.nodes if node.source is not None}
    if manifest.root_node in source_ids:
        raise WorkspaceError("workspace lock must not lock the root repository inside itself")
    if set(source_ids) != set(declared_sources):
        missing = sorted(set(declared_sources) - set(source_ids))
        unknown = sorted(set(source_ids) - set(declared_sources))
        raise WorkspaceError(
            f"workspace lock sources mismatch; missing={missing!r}, unknown={unknown!r}"
        )
    sources: list[LockedSource] = []
    for node_id in sorted(source_ids):
        raw_source = _mapping(sources_value[node_id], f"lock sources.{node_id}")
        _known_fields(raw_source, _LOCK_SOURCE_FIELDS, f"lock sources.{node_id}")
        declared = declared_sources[node_id].source
        assert declared is not None
        driver = _string(raw_source.get("driver"), f"lock sources.{node_id}.driver")
        url = _source_url(raw_source.get("url"), f"lock sources.{node_id}.url")
        requested_value = raw_source.get("requested-ref")
        requested = (
            None
            if requested_value is None
            else _non_empty(requested_value, f"lock sources.{node_id}.requested-ref")
        )
        if (driver, url, requested) != (declared.driver, declared.url, declared.ref):
            raise WorkspaceError(f"lock source {node_id!r} is inconsistent with poly.yaml")
        resolved = _mapping(raw_source.get("resolved"), f"lock sources.{node_id}.resolved")
        _known_fields(resolved, _RESOLVED_FIELDS, f"lock sources.{node_id}.resolved")
        commit = _string(resolved.get("commit"), f"lock sources.{node_id}.resolved.commit")
        if driver == "git" and not _COMMIT.fullmatch(commit):
            raise WorkspaceError(f"lock source {node_id!r} has no immutable full Git commit")
        ref_kind = _non_empty(resolved.get("ref-kind"), f"lock sources.{node_id}.resolved.ref-kind")
        sources.append(LockedSource(node_id, driver, url, requested, commit.lower(), ref_kind))
    return WorkspaceLock(digest, tuple(sources))


def _parse_source(value: object, where: str) -> SourceDeclaration | None:
    if value is None:
        return None
    source = _mapping(value, where)
    _known_fields(source, _SOURCE_FIELDS, where)
    driver = _identifier(source.get("driver"), f"{where}.driver")
    url = _source_url(source.get("url"), f"{where}.url")
    ref_value = source.get("ref")
    ref = None if ref_value is None else _non_empty(ref_value, f"{where}.ref")
    return SourceDeclaration(driver, url, ref)


def _declared_node(node: WorkspaceNode, locked: LockedSource | None = None) -> Node:
    metadata: Metadata = {
        "poly.state": "declared",
        "poly.kind": node.kind,
        "poly.declared-path": node.path,
        "poly.workspace-path": node.workspace_path,
        "poly.parent": node.parent,
    }
    if node.source is not None:
        metadata.update(
            {
                "poly.source.driver": node.source.driver,
                "poly.source.url": node.source.url,
                "poly.source.ref": node.source.ref,
            }
        )
    if locked is not None:
        metadata.update(
            {
                "poly.lock.commit": locked.commit,
                "poly.lock.ref-kind": locked.ref_kind,
            }
        )
    natures = set(node.natures)
    natures.add(f"poly/{node.kind}")
    relations = (NodeRelation("poly/parent", node.parent),) if node.parent is not None else ()
    return Node(node.id, node.workspace_path, tuple(natures), metadata, relations)


def _declared_identity(manifest: WorkspaceManifest, observed: Node) -> str | None:
    candidates = [node for node in manifest.nodes if node.workspace_path == observed.path]
    if "git/repository" in observed.natures:
        boundaries = [node for node in candidates if node.kind in {"workspace", "repository"}]
        return boundaries[0].id if len(boundaries) == 1 else None
    if "maven/project" in observed.natures:
        modules = [node for node in candidates if node.kind == "module"]
        if len(modules) == 1:
            return modules[0].id
    if len(candidates) == 1:
        return candidates[0].id
    return None


def _merge_node(base: Node, observed: Node, relations: tuple[NodeRelation, ...]) -> Node:
    metadata = dict(base.metadata)
    for key, value in observed.metadata.items():
        if key in metadata and metadata[key] != value:
            raise WorkspaceError(f"inspector metadata collision for node {base.id!r}: {key}")
        metadata[key] = value
    metadata["poly.state"] = "declared-observed"
    return Node(
        base.id,
        base.path,
        (*base.natures, *observed.natures),
        metadata,
        (*base.relations, *relations),
    )


def _validate_collisions(
    nodes: list[tuple[str, str | None, str, str, SourceDeclaration | None, tuple[str, ...]]],
    resolved: dict[str, str],
) -> None:
    by_folded: dict[str, list[str]] = {}
    for node_id, _parent, _kind, _path, _source, _natures in nodes:
        by_folded.setdefault(resolved[node_id].casefold(), []).append(node_id)
    lookup = {item[0]: item for item in nodes}
    for folded, identifiers in sorted(by_folded.items()):
        if len(identifiers) < 2:
            continue
        actual = {resolved[node_id] for node_id in identifiers}
        if len(actual) > 1:
            raise WorkspaceError(
                f"case-insensitive workspace path collision at {folded!r}: {sorted(identifiers)!r}"
            )
        non_overlay = [
            node_id
            for node_id in identifiers
            if not (lookup[node_id][2] == "module" and lookup[node_id][3] == ".")
        ]
        if len(non_overlay) > 1 or len(non_overlay) == len(identifiers):
            raise WorkspaceError(
                f"workspace path collision at {next(iter(actual))!r}: {sorted(identifiers)!r}"
            )


def _update_lock_for_manifest(raw_lock: dict[Any, Any], manifest: WorkspaceManifest) -> None:
    raw_lock["manifest-digest"] = manifest.digest
    sources = _mapping_value(raw_lock, "sources", "lock sources")
    declared = {node.id for node in manifest.nodes if node.source is not None}
    for node_id in tuple(sources):
        if node_id not in declared:
            del sources[node_id]
    _parse_lock(raw_lock, manifest)


def _managed_ignore_parts(path: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except (OSError, UnicodeError) as error:
        raise WorkspaceError(f"cannot read root .gitignore: {error}") from error
    lines = text.splitlines()
    begins = [index for index, line in enumerate(lines) if line == MANAGED_IGNORE_BEGIN]
    ends = [index for index, line in enumerate(lines) if line == MANAGED_IGNORE_END]
    if not begins and not ends:
        return tuple(lines), ()
    if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
        raise WorkspaceError("root .gitignore has malformed or duplicate Poly managed markers")
    return tuple(lines[: begins[0]]), tuple(lines[ends[0] + 1 :])


def _reject_provisional_manifest(workspace: Path) -> None:
    provisional = workspace / PROVISIONAL_WORKSPACE_MANIFEST
    if provisional.is_file():
        raise WorkspaceError(
            f"provisional {PROVISIONAL_WORKSPACE_MANIFEST} is unsupported; migrate its authored "
            f"composition to {WORKSPACE_MANIFEST} and remove the provisional file"
        )


def _safe_workspace_path(workspace: Path, value: str, node_id: str) -> None:
    candidate = (workspace / value).resolve(strict=False)
    try:
        candidate.relative_to(workspace)
    except ValueError as error:
        raise WorkspaceError(f"node {node_id!r} escapes the workspace through {value!r}") from error


def _relative_path(value: object, where: str) -> str:
    text = _string(value, where)
    if "\\" in text:
        raise WorkspaceError(f"{where} must use forward slashes")
    if text == ".":
        return text
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise WorkspaceError(f"{where} must be a safe relative path: {text!r}")
    normalized = path.as_posix()
    if normalized.startswith("//") or re.match(r"^[A-Za-z]:", normalized):
        raise WorkspaceError(f"{where} must be workspace-relative: {text!r}")
    return normalized


def _source_url(value: object, where: str) -> str:
    url = _non_empty(value, where)
    if any(character.isspace() for character in url):
        raise WorkspaceError(f"{where} must not contain whitespace")
    parsed = urlsplit(url)
    if parsed.password is not None or (parsed.scheme in {"http", "https"} and parsed.username):
        raise WorkspaceError(f"{where} must not contain embedded credentials")
    if parsed.scheme:
        hostname = parsed.hostname
        if not hostname and parsed.scheme != "file":
            raise WorkspaceError(f"{where} has no host")
        if parsed.scheme in {"http", "https"}:
            netloc = hostname or ""
            if parsed.port is not None:
                netloc = f"{netloc}:{parsed.port}"
            return urlunsplit(
                (parsed.scheme.lower(), netloc.lower(), parsed.path, parsed.query, "")
            )
    return url


def _load_yaml(path: Path) -> CommentedMap:
    yaml = _yaml()
    try:
        value = yaml.load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise WorkspaceError(f"required workspace file does not exist: {path}") from error
    except (OSError, UnicodeError, YAMLError, ValueError) as error:
        raise WorkspaceError(f"cannot read workspace file {path}: {error}") from error
    return _mapping(value, str(path))


def _write_yaml(path: Path, value: object) -> None:
    _atomic_text(path, _yaml_text(value))


def _yaml_text(value: object) -> str:
    stream = StringIO()
    try:
        _yaml().dump(value, stream)
    except YAMLError as error:
        raise WorkspaceError(f"cannot serialize workspace YAML: {error}") from error
    return stream.getvalue()


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.allow_duplicate_keys = False
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.preserve_quotes = True
    return yaml


def _atomic_json(path: Path, value: dict[str, JsonValue]) -> None:
    _atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    except OSError as error:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise WorkspaceError(f"cannot atomically write {path}: {error}") from error


def _atomic_text_set(values: dict[Path, str]) -> None:
    """Replace a related set of files as one recoverable workspace transaction."""

    transaction = f"{os.getpid()}-{id(values)}"
    temporaries: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    touched: list[Path] = []
    try:
        for path, value in values.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{transaction}.tmp")
            temporary.write_text(value, encoding="utf-8")
            temporaries[path] = temporary
        for path in values:
            backup = path.with_name(f".{path.name}.{transaction}.bak") if path.exists() else None
            if backup is not None:
                path.replace(backup)
            backups[path] = backup
            touched.append(path)
            temporaries[path].replace(path)
    except OSError as error:
        for path in reversed(touched):
            backup = backups.get(path)
            with suppress(OSError):
                path.unlink(missing_ok=True)
                if backup is not None and backup.exists():
                    backup.replace(path)
        raise WorkspaceError(f"cannot atomically update workspace files: {error}") from error
    finally:
        for temporary in temporaries.values():
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
        for backup in backups.values():
            if backup is not None:
                with suppress(OSError):
                    backup.unlink(missing_ok=True)


def _mapping(value: object, where: str = "value") -> CommentedMap:
    if not isinstance(value, dict):
        raise WorkspaceError(f"{where} must be a mapping")
    return value  # type: ignore[return-value]


def _mapping_value(root: dict[Any, Any], key: str, where: str) -> CommentedMap:
    return _mapping(root.get(key), where)


def _mapping_sequence(root: dict[Any, Any], key: str, where: str) -> CommentedSeq:
    value = root.get(key)
    if not isinstance(value, list):
        raise WorkspaceError(f"{where} must be a list")
    return value  # type: ignore[return-value]


def _known_fields(value: dict[Any, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise WorkspaceError(f"{where} contains unknown fields: {unknown!r}")


def _string(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise WorkspaceError(f"{where} must be a string")
    return value


def _non_empty(value: object, where: str) -> str:
    text = _string(value, where).strip()
    if not text:
        raise WorkspaceError(f"{where} must not be empty")
    return text


def _identifier(value: object, where: str) -> str:
    text = _non_empty(value, where)
    if not _IDENTIFIER.fullmatch(text):
        raise WorkspaceError(f"{where} is not a stable identifier: {text!r}")
    return text


def _string_tuple(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WorkspaceError(f"{where} must be a string list")
    normalized = tuple(_non_empty(item, where) for item in value)
    if len(normalized) != len(set(normalized)):
        raise WorkspaceError(f"{where} contains duplicates")
    return tuple(sorted(normalized))


def _escape_gitignore(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in "*?[]":
        escaped = escaped.replace(character, f"\\{character}")
    return escaped
