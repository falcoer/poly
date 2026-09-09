"""Portable Eclipse navigation projects, implemented only against the public SDK.

The shared JSON profile is user-owned. Only the generated .project is managed;
its in-file content digest detects manual edits without disposable runtime state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import quote
from xml.etree import ElementTree as ET

from poly.driver import (
    DriverCapability,
    DriverExecutionResult,
    DriverManifest,
    DriverRegistration,
    ExecutionContext,
    FacadeArgument,
    FacadeRequest,
    OutputReference,
)
from poly.model import (
    ActionClaim,
    ActionSpec,
    Constraint,
    DriverProposal,
    Node,
    PlanningRequest,
    RejectedCandidate,
)

PROFILE = "poly.eclipse.json"
PROJECT = ".eclipse/.project"
SCHEMA = "poly.eclipse/v1"
PAYLOAD = "POLY_ECLIPSE_CHANGES"
_HEADER = b'<?xml version="1.0" encoding="UTF-8"?>\n'
_MARKER = b"<!-- poly:eclipse-navigation/v1 sha256="


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _path(workspace: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or parts.is_absolute()
        or ".." in parts.parts
        or PureWindowsPath(relative).drive
        or any(ord(char) < 32 for char in relative)
    ):
        raise ValueError(f"unsafe workspace-relative path: {relative!r}")
    target = workspace
    for part in parts.parts:
        target = target / part
        if target.is_symlink() or target.is_junction():
            raise ValueError(f"linked filesystem paths are unsupported: {relative}")
    return target


def _read(workspace: Path, relative: str) -> bytes | None:
    path = _path(workspace, relative)
    return path.read_bytes() if path.exists() else None


def _fingerprint(content: bytes | None) -> str | None:
    return None if content is None else _digest(content)


def _name(value: str) -> str:
    if (
        not value.strip()
        or value != value.strip()
        or value.endswith(".")
        or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', value)
        or value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL"}
        or re.fullmatch(r"(?i)(COM|LPT)[1-9](\..*)?", value)
    ):
        raise ValueError("Eclipse project name must be a portable, non-empty filename")
    return value


def _managed(content: bytes) -> bool:
    try:
        header, marker, body = content.split(b"\n", 2)
        return header + b"\n" == _HEADER and marker == _MARKER + _digest(body).encode() + b" -->"
    except ValueError:
        return False


def _project(name: str, nodes: tuple[Node, ...]) -> bytes:
    root = ET.Element("projectDescription")
    ET.SubElement(root, "name").text = name
    ET.SubElement(root, "comment").text = f"Poly navigation/v1; shared intent: ../{PROFILE}"
    for tag in ("projects", "buildSpec", "natures"):
        ET.SubElement(root, tag)
    links = ET.SubElement(root, "linkedResources")
    for relative in sorted({node.path for node in nodes}):
        link = ET.SubElement(links, "link")
        basename = re.sub(r"[^A-Za-z0-9_-]", "_", PurePosixPath(relative).name)[:48]
        ET.SubElement(link, "name").text = f"{basename}-{_digest(relative.encode())[:12]}"
        ET.SubElement(link, "type").text = "2"
        ET.SubElement(link, "locationURI").text = "PARENT-1-PROJECT_LOC/" + quote(
            relative, safe="/"
        )
    ET.indent(root, space="  ")
    serialized: bytes = ET.tostring(root, encoding="utf-8")
    body = serialized + b"\n"
    return _HEADER + _MARKER + _digest(body).encode() + b" -->\n" + body


class EclipseFacade:
    name = "eclipse"
    verb = "configure"
    description = "prepare a portable Eclipse navigation project"
    arguments = (FacadeArgument("name", ("--name",), help="project name on first generation"),)

    def translate(self, request: FacadeRequest) -> dict[str, str]:
        parameters = dict(request.parameters)
        parameters["tool"] = "eclipse"
        name = request.values.get("name")
        if isinstance(name, str):
            parameters["eclipse.name"] = _name(name)
        return parameters


class EclipseDriver:
    name = "eclipse"
    verbs = frozenset(("configure",))

    def propose(self, request: PlanningRequest) -> DriverProposal:
        if request.verb != "configure" or request.parameters.get("tool") != "eclipse":
            return DriverProposal(self.name)
        try:
            return self._propose(request)
        except (ValueError, OSError, KeyError) as error:
            return DriverProposal(
                self.name,
                actions=(
                    ActionSpec(
                        "eclipse:configure",
                        self.name,
                        request.verb,
                        "eclipse/configure",
                        request.selected_node_ids,
                        requested_node_ids=request.selected_node_ids,
                        requires=frozenset((Constraint("eclipse/configuration/valid"),)),
                        required_capability="driver.execute",
                        environment={"POLY_ECLIPSE_ERROR": str(error)},
                    ),
                ),
                rejected=(
                    RejectedCandidate(
                        self.name, "eclipse/configure", str(error), request.selected_node_ids
                    ),
                ),
            )

    def _propose(self, request: PlanningRequest) -> DriverProposal:
        workspace = request.workspace
        if workspace is None:
            raise ValueError("Eclipse configuration requires a workspace planning context")
        old_profile = _read(workspace, PROFILE)
        explicit = request.parameters.get("poly.selection.mode") != "implicit"
        if old_profile is not None:
            profile = json.loads(old_profile)
            if (
                not isinstance(profile, dict)
                or set(profile) != {"schema", "profile", "project_name", "nodes"}
                or profile["schema"] != SCHEMA
                or profile["profile"] != "navigation"
                or not isinstance(profile["project_name"], str)
                or not isinstance(profile["nodes"], list)
                or not all(isinstance(item, str) for item in profile["nodes"])
            ):
                raise ValueError(
                    f"{PROFILE}: expected {SCHEMA} navigation profile with name and nodes"
                )
            name = _name(profile["project_name"])
            selected = tuple(sorted(set(profile["nodes"])))
            if (explicit and selected != request.selected_node_ids) or (
                "eclipse.name" in request.parameters and request.parameters["eclipse.name"] != name
            ):
                raise ValueError(
                    f"edit user-owned {PROFILE} to change its project name or selection"
                )
            if not set(selected).issubset(request.selected_node_ids):
                raise ValueError(
                    f"{PROFILE}: selected nodes are missing; inspect and update the profile"
                )
        else:
            name = _name(request.parameters.get("eclipse.name", workspace.name + "-navigation"))
            selected = tuple(
                node.id
                for node in request.inventory.select(request.selected_node_ids)
                if explicit or node.path not in (".", ".eclipse")
            )
            profile = {
                "schema": SCHEMA,
                "profile": "navigation",
                "project_name": name,
                "nodes": list(selected),
            }
        nodes = request.inventory.select(selected)
        if not nodes:
            raise ValueError("select at least one existing workspace subdirectory for Eclipse")
        for node in nodes:
            path = _path(workspace, node.path)
            if node.path == "." or PurePosixPath(node.path).parts[0] in {".eclipse", ".poly"}:
                raise ValueError(
                    f"{node.id}: select subdirectories, not the root or generated state"
                )
            if not path.is_dir():
                raise ValueError(
                    f"{node.id}: directory {node.path!r} is absent; hydrate explicitly first"
                )
        old_project = _read(workspace, PROJECT)
        if old_project is not None and not _managed(old_project):
            raise ValueError(
                f"{PROJECT}: user-owned or manually modified; move it aside before retrying"
            )
        content = _project(name, nodes)
        inputs = {
            path: _fingerprint(_read(workspace, path))
            for path in (PROFILE, PROJECT, "poly.yaml", "poly.lock.yaml")
        }
        files = {PROJECT: content.decode()}
        if old_profile is None:
            files[PROFILE] = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"
        payload = {
            "schema": SCHEMA,
            "inputs": inputs,
            "files": files,
            "directories": sorted({node.path for node in nodes}),
            "changes": {
                path: "create"
                if inputs[path] is None
                else "unchanged"
                if _digest(text.encode()) == inputs[path]
                else "update"
                for path, text in files.items()
            },
        }
        action = ActionSpec(
            "eclipse:configure",
            self.name,
            request.verb,
            "eclipse/configure",
            selected,
            requested_node_ids=selected,
            claims=frozenset(ActionClaim("file/write", path) for path in (PROFILE, PROJECT)),
            environment={PAYLOAD: json.dumps(payload, sort_keys=True, ensure_ascii=False)},
            required_capability="driver.execute",
            execution_resources=frozenset(("workspace:eclipse-configuration",)),
            concurrency_safe=False,
        )
        return DriverProposal(self.name, (action,))

    def execute(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        delivered: list[OutputReference] = []
        try:
            if "POLY_ECLIPSE_ERROR" in action.environment:
                raise ValueError(action.environment["POLY_ECLIPSE_ERROR"])
            payload = json.loads(action.environment[PAYLOAD])
            if payload["schema"] != SCHEMA or set(payload["files"]) - {PROFILE, PROJECT}:
                raise ValueError("unsupported Eclipse configuration action payload")
            workspace = context.workspace
            for relative, expected in payload["inputs"].items():
                if _fingerprint(_read(workspace, relative)) != expected:
                    raise ValueError(
                        f"stale plan: {relative} changed; review a new configuration plan"
                    )
            for relative in payload["directories"]:
                if not _path(workspace, relative).is_dir():
                    raise ValueError(f"stale plan: linked directory {relative} is absent")
            changed = 0
            # Save intent first: a failed second write can safely be retried.
            for relative in sorted(payload["files"], reverse=True):
                text = payload["files"][relative]
                target = _path(workspace, relative)
                content = text.encode("utf-8")
                previous = _read(workspace, relative)
                if _fingerprint(previous) != payload["inputs"][relative]:
                    raise ValueError(f"stale plan: {relative} changed during execution")
                if previous != content:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if previous is None:
                        with target.open("xb") as stream:
                            stream.write(content)
                    else:
                        # Atomic replacement avoids a half-written .project after interruption.
                        descriptor, temporary = tempfile.mkstemp(
                            prefix=".poly-eclipse-", dir=target.parent
                        )
                        try:
                            with os.fdopen(descriptor, "wb") as stream:
                                stream.write(content)
                            if _read(workspace, relative) != previous:
                                raise ValueError(f"stale plan: {relative} changed during execution")
                            os.replace(temporary, target)
                        finally:
                            Path(temporary).unlink(missing_ok=True)
                    changed += 1
                delivered.append(OutputReference("file", str(target), relative))
            return DriverExecutionResult(
                True,
                f"Eclipse navigation ready; {changed} files changed",
                {"profile": "navigation", "changed_files": changed},
                outputs=tuple(delivered),
            )
        except (OSError, ValueError, KeyError, TypeError) as error:
            return DriverExecutionResult(False, str(error), outputs=tuple(delivered))


def eclipse_driver() -> DriverRegistration:
    provider = EclipseDriver()
    return DriverRegistration(
        DriverManifest(
            "eclipse",
            "0.13.2",
            "1.1",
            frozenset((DriverCapability.PLAN, DriverCapability.EXECUTE, DriverCapability.FACADE)),
            "Portable Eclipse workspace navigation",
        ),
        planners=(provider,),
        handlers=(provider,),
        facades=(EclipseFacade(),),
    )
