"""Deterministic, disposable cache for canonical workspace inspection data."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from poly.driver import DriverInventoryItem, InspectionDiagnostic
from poly.model import Inventory, JsonValue, Node, NodeRelation
from poly.workspace import PROVISIONAL_WORKSPACE_MANIFEST, WORKSPACE_LOCK, WORKSPACE_MANIFEST

CACHE_SCHEMA = "poly.inspection-cache/v1"
_CACHE_FILE = "inspection-v1.json"
_SKIPPED_DIRECTORIES = {".git", ".poly", ".venv", "node_modules", "target"}


def fingerprint(
    workspace: Path, drivers: tuple[DriverInventoryItem, ...], *, remote: bool
) -> dict[str, JsonValue]:
    """Describe every authored input that can change the cached inspection model."""

    return {
        "remote": remote,
        "drivers": [
            {
                "identity": driver.identity,
                "version": driver.version,
                "api_version": driver.api_version,
                "status": driver.status,
            }
            for driver in drivers
        ],
        "sources": [
            {"path": path.relative_to(workspace).as_posix(), "sha256": _digest(path)}
            for path in _source_paths(workspace)
        ],
    }


def load(
    workspace: Path, expected_fingerprint: dict[str, JsonValue]
) -> tuple[Inventory, tuple[InspectionDiagnostic, ...]] | None:
    """Load an exact cache hit, treating corrupt or obsolete cache data as a miss."""

    path = _cache_path(workspace)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != CACHE_SCHEMA:
        return None
    if raw.get("fingerprint") != expected_fingerprint:
        return None
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        return None
    try:
        return _inventory(payload), _diagnostics(payload)
    except (TypeError, ValueError):
        return None


def save(
    workspace: Path,
    source_fingerprint: dict[str, JsonValue],
    inventory: Inventory,
    diagnostics: tuple[InspectionDiagnostic, ...],
) -> Path:
    """Atomically replace the cache with canonical inspection observations."""

    path = _cache_path(workspace)
    document: dict[str, JsonValue] = {
        "schema": CACHE_SCHEMA,
        "fingerprint": source_fingerprint,
        "payload": {
            "nodes": [
                {
                    "id": node.id,
                    "path": node.path,
                    "natures": list(node.natures),
                    "metadata": dict(node.metadata),
                    "relations": [
                        {"kind": relation.kind, "target": relation.target}
                        for relation in node.relations
                    ],
                }
                for node in inventory.nodes
            ],
            "diagnostics": [
                {"code": diagnostic.code, "message": diagnostic.message, "path": diagnostic.path}
                for diagnostic in diagnostics
            ],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _cache_path(workspace: Path) -> Path:
    return workspace / ".poly" / "state" / "inspection" / _CACHE_FILE


def _source_paths(workspace: Path) -> tuple[Path, ...]:
    paths = [
        workspace / name
        for name in (WORKSPACE_MANIFEST, WORKSPACE_LOCK, PROVISIONAL_WORKSPACE_MANIFEST)
        if (workspace / name).is_file()
    ]
    for current, directories, files in os.walk(workspace):
        current_path = Path(current)
        if ".git" in directories:
            head = current_path / ".git" / "HEAD"
            if head.is_file():
                paths.append(head)
        if ".git" in files:
            paths.append(current_path / ".git")
        directories[:] = sorted(name for name in directories if name not in _SKIPPED_DIRECTORIES)
        if "pom.xml" in files:
            paths.append((current_path / "pom.xml").resolve())
    return tuple(sorted(set(paths), key=lambda path: path.as_posix()))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(payload: dict[str, object]) -> Inventory:
    values = payload.get("nodes")
    if not isinstance(values, list):
        raise ValueError("cached nodes are missing")
    nodes: list[Node] = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("cached node is invalid")
        relations = value.get("relations", [])
        metadata = value.get("metadata", {})
        natures = value.get("natures", [])
        if (
            not isinstance(relations, list)
            or not isinstance(metadata, dict)
            or not isinstance(natures, list)
            or not isinstance(value.get("id"), str)
            or not isinstance(value.get("path"), str)
        ):
            raise ValueError("cached node is incompatible")
        nodes.append(
            Node(
                value["id"],
                value["path"],
                tuple(str(nature) for nature in natures),
                metadata,
                tuple(
                    NodeRelation(str(relation["kind"]), str(relation["target"]))
                    for relation in relations
                    if isinstance(relation, dict)
                    and isinstance(relation.get("kind"), str)
                    and isinstance(relation.get("target"), str)
                ),
            )
        )
    return Inventory(tuple(nodes))


def _diagnostics(payload: dict[str, object]) -> tuple[InspectionDiagnostic, ...]:
    values = payload.get("diagnostics")
    if not isinstance(values, list):
        raise ValueError("cached diagnostics are missing")
    diagnostics = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("cached diagnostic is invalid")
        code, message, path = value.get("code"), value.get("message"), value.get("path")
        if (
            not isinstance(code, str)
            or not isinstance(message, str)
            or not isinstance(path, str | None)
        ):
            raise ValueError("cached diagnostic is incompatible")
        diagnostics.append(InspectionDiagnostic(code, message, path))
    return tuple(sorted(diagnostics))
