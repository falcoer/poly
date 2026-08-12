"""Read-only Git inspection and status planning."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from poly.driver import (
    DRIVER_API_VERSION,
    DriverCapability,
    DriverManifest,
    DriverRegistration,
    InspectionContext,
    InspectionDiagnostic,
    InspectionResult,
)
from poly.model import (
    ActionClaim,
    ActionSpec,
    DriverProposal,
    Metadata,
    Node,
    NodeRelation,
    PlanningRequest,
    RejectedCandidate,
)

GIT_DRIVER_NAME = "poly.driver.git"


@dataclass(frozen=True, slots=True)
class GitInspectionProvider:
    name: str = GIT_DRIVER_NAME
    command_timeout_seconds: float = 5.0

    def inspect(self, context: InspectionContext) -> InspectionResult:
        roots = _discover_repository_roots(context.workspace)
        diagnostics: list[InspectionDiagnostic] = []
        observed: list[tuple[Path, Metadata]] = []
        for root in roots:
            try:
                metadata = self._metadata(context.workspace, root)
            except GitInspectionError as error:
                diagnostics.append(
                    InspectionDiagnostic(
                        code="git.inspect.failed",
                        message=str(error),
                        path=_relative(context.workspace, root),
                    )
                )
                continue
            observed.append((root, metadata))

        nodes = tuple(
            Node(
                id=_node_id(context.workspace, root),
                path=_relative(context.workspace, root),
                natures=("git/repository",),
                metadata=metadata,
                relations=_ownership_relations(context.workspace, root, roots),
            )
            for root, metadata in observed
        )
        return InspectionResult(self.name, nodes, tuple(diagnostics))

    def _metadata(self, workspace: Path, root: Path) -> Metadata:
        inside = self._git(root, "rev-parse", "--is-inside-work-tree")
        if inside != "true":
            raise GitInspectionError(f"{root} is not a Git worktree")
        branch_process = self._run(root, "symbolic-ref", "--quiet", "--short", "HEAD")
        branch = branch_process.stdout.strip() if branch_process.returncode == 0 else None
        head_process = self._run(root, "rev-parse", "--verify", "HEAD")
        head = head_process.stdout.strip() if head_process.returncode == 0 else None
        status = self._git(root, "status", "--porcelain=v1", "--untracked-files=normal")
        bare = self._git(root, "rev-parse", "--is-bare-repository") == "true"
        return {
            "git.root": _relative(workspace, root),
            "git.branch": branch,
            "git.head": head,
            "git.clean": not bool(status),
            "git.detached": branch is None and head is not None,
            "git.bare": bare,
        }

    def _git(self, root: Path, *arguments: str) -> str:
        process = self._run(root, *arguments)
        if process.returncode != 0:
            message = process.stderr.strip() or f"git exited with {process.returncode}"
            raise GitInspectionError(message)
        return process.stdout.strip()

    def _run(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ("git", "-C", str(root), *arguments),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.command_timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GitInspectionError(f"unable to inspect {root}: {error}") from error


class GitInspectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GitPlanningProvider:
    name: str = GIT_DRIVER_NAME
    verbs: frozenset[str] = frozenset(("status",))

    def propose(self, request: PlanningRequest) -> DriverProposal:
        actions: list[ActionSpec] = []
        rejected: list[RejectedCandidate] = []
        for node in request.inventory.select(request.selected_node_ids):
            if "git/repository" not in node.natures:
                rejected.append(
                    RejectedCandidate(
                        driver=self.name,
                        operation="git/status",
                        reason="node is not a Git repository",
                        node_ids=(node.id,),
                        missing=("nature:git/repository",),
                    )
                )
                continue
            actions.append(
                ActionSpec(
                    id=f"git.status:{node.id}",
                    driver=self.name,
                    verb=request.verb,
                    operation="git/status",
                    node_ids=(node.id,),
                    requested_node_ids=(node.id,),
                    claims=frozenset((ActionClaim("git/status", f"node:{node.id}"),)),
                    command=("git", "-C", node.path, "status", "--short", "--branch"),
                )
            )
        return DriverProposal(self.name, tuple(actions), tuple(rejected))


def git_driver() -> DriverRegistration:
    manifest = DriverManifest(
        name=GIT_DRIVER_NAME,
        version="0.1.0",
        api_version=DRIVER_API_VERSION,
        capabilities=frozenset((DriverCapability.INSPECT, DriverCapability.PLAN)),
        description="Read-only Git repository inspection and status planning",
    )
    return DriverRegistration(
        manifest=manifest,
        inspectors=(GitInspectionProvider(),),
        planners=(GitPlanningProvider(),),
    )


def _discover_repository_roots(workspace: Path) -> tuple[Path, ...]:
    roots: list[Path] = []
    for current, directory_names, file_names in os.walk(workspace):
        directory_names[:] = sorted(name for name in directory_names if name != ".git")
        if ".git" in file_names or (Path(current) / ".git").is_dir():
            roots.append(Path(current).resolve())
    return tuple(sorted(set(roots), key=lambda path: path.as_posix()))


def _ownership_relations(
    workspace: Path, root: Path, all_roots: tuple[Path, ...]
) -> tuple[NodeRelation, ...]:
    parents = [
        candidate for candidate in all_roots if candidate != root and candidate in root.parents
    ]
    if not parents:
        return ()
    owner = max(parents, key=lambda candidate: len(candidate.parts))
    return (NodeRelation("git/nested-under", _node_id(workspace, owner)),)


def _relative(workspace: Path, path: Path) -> str:
    relative = path.relative_to(workspace)
    return relative.as_posix() if relative.parts else "."


def _node_id(workspace: Path, root: Path) -> str:
    return f"git:{PurePosixPath(_relative(workspace, root))}"
