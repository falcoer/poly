"""Reusable black-box conformance assertions for every Poly driver."""

from __future__ import annotations

import hashlib
from pathlib import Path

from poly.driver.api import InspectionContext, InspectionProvider, PlanningProvider
from poly.driver.manifest import DriverManifest
from poly.model import DriverProposal, PlanningRequest


class DriverConformanceError(AssertionError):
    pass


def assert_manifest_compatible(manifest: DriverManifest) -> None:
    manifest.ensure_compatible()
    restored = DriverManifest.from_dict(manifest.to_dict())
    if restored != manifest:
        raise DriverConformanceError("manifest does not round-trip through its public mapping")


def assert_planning_deterministic(
    provider: PlanningProvider, request: PlanningRequest, workspace: Path
) -> DriverProposal:
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise DriverConformanceError(f"test workspace does not exist: {workspace}")
    before = workspace_fingerprint(workspace)
    first = provider.propose(request)
    middle = workspace_fingerprint(workspace)
    second = provider.propose(request)
    after = workspace_fingerprint(workspace)
    if first != second:
        raise DriverConformanceError("identical planning requests produced different proposals")
    if before != middle or middle != after:
        raise DriverConformanceError("planning changed the workspace")
    if first.driver != provider.name:
        raise DriverConformanceError("proposal driver does not match provider name")
    wrong = sorted(action.id for action in first.actions if action.verb != request.verb)
    if wrong:
        raise DriverConformanceError(f"provider proposed actions for another verb: {wrong!r}")
    return first


def assert_inspection_side_effect_free(
    provider: InspectionProvider, context: InspectionContext
) -> None:
    before = workspace_fingerprint(context.workspace)
    first = provider.inspect(context)
    middle = workspace_fingerprint(context.workspace)
    second = provider.inspect(context)
    after = workspace_fingerprint(context.workspace)
    if first != second:
        raise DriverConformanceError("identical inspections produced different results")
    if before != middle or middle != after:
        raise DriverConformanceError("inspection changed the workspace")
    if first.driver != provider.name:
        raise DriverConformanceError("inspection driver does not match provider name")


def workspace_fingerprint(workspace: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace).as_posix()
        if ".git" in path.relative_to(workspace).parts:
            continue
        digest.update(relative.encode())
        if path.is_symlink():
            digest.update(b"\0symlink\0")
            digest.update(path.readlink().as_posix().encode())
        elif path.is_file():
            digest.update(b"\0file\0")
            digest.update(path.read_bytes())
        elif path.is_dir():
            digest.update(b"\0directory\0")
    return digest.hexdigest()
