"""Read-only Git inspection and status planning."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from poly.driver import (
    DRIVER_API_VERSION,
    DriverCapability,
    DriverExecutionResult,
    DriverManifest,
    DriverRegistration,
    ExecutionContext,
    FacadeArgument,
    FacadeRequest,
    InspectionContext,
    InspectionDiagnostic,
    InspectionResult,
)
from poly.model import (
    ActionClaim,
    ActionSpec,
    Constraint,
    DriverProposal,
    Metadata,
    Node,
    NodeRelation,
    PlanningRequest,
    RejectedCandidate,
)
from poly.workspace import WorkspaceError, update_locked_sources, validate_workspace

GIT_DRIVER_NAME = "poly.driver.git"
_COMMIT = re.compile(r"[0-9a-fA-F]{40,64}\Z")


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
                metadata = self._metadata(context, root)
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

    def _metadata(self, context: InspectionContext, root: Path) -> Metadata:
        workspace = context.workspace
        inside = self._git(root, "rev-parse", "--is-inside-work-tree")
        if inside != "true":
            raise GitInspectionError(f"{root} is not a Git worktree")
        branch_process = self._run(root, "symbolic-ref", "--quiet", "--short", "HEAD")
        branch = branch_process.stdout.strip() if branch_process.returncode == 0 else None
        head_process = self._run(root, "rev-parse", "--verify", "HEAD")
        head = head_process.stdout.strip() if head_process.returncode == 0 else None
        status = self._git(root, "status", "--porcelain=v1", "--untracked-files=normal")
        bare = self._git(root, "rev-parse", "--is-bare-repository") == "true"
        remote_process = self._run(root, "remote", "get-url", "origin")
        metadata: Metadata = {
            "git.root": _relative(workspace, root),
            "git.branch": branch,
            "git.head": head,
            "git.clean": not bool(status),
            "git.detached": branch is None and head is not None,
            "git.bare": bare,
            "git.remote.origin.url": (
                remote_process.stdout.strip() if remote_process.returncode == 0 else None
            ),
        }
        locked_value = context.parameters.get("poly.git.locked-sources", "{}")
        try:
            locked = json.loads(locked_value)
        except json.JSONDecodeError:
            locked = {}
        if isinstance(locked, dict):
            locked_source = locked.get(_relative(workspace, root))
            locked_commit = locked_source.get("commit") if isinstance(locked_source, dict) else None
            if isinstance(locked_commit, str) and head is not None:
                metadata["git.lock.commit"] = locked_commit
                metadata["git.lock.state"] = self._lock_state(root, head, locked_commit)
                if context.parameters.get("poly.git.remote") == "true" and isinstance(
                    locked_source, dict
                ):
                    url = locked_source.get("url")
                    requested = locked_source.get("ref")
                    if isinstance(url, str):
                        remote_commit = self._remote_commit(
                            url, requested if isinstance(requested, str) else None
                        )
                        metadata["git.remote.commit"] = remote_commit
                        metadata["git.remote.lock-state"] = (
                            "current" if remote_commit == locked_commit else "advanced"
                        )
        return metadata

    def _remote_commit(self, url: str, requested: str | None) -> str:
        patterns = (
            ("HEAD",)
            if requested is None
            else (
                requested,
                f"refs/heads/{requested}",
                f"refs/tags/{requested}*",
            )
        )
        try:
            process = subprocess.run(
                ("git", "ls-remote", url, *patterns),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.command_timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GitInspectionError(f"cannot inspect remote {url}: {error}") from error
        if process.returncode != 0:
            raise GitInspectionError(process.stderr.strip() or f"cannot inspect remote {url}")
        values = [
            line.partition("\t")[0]
            for line in process.stdout.splitlines()
            if "\t" in line and _COMMIT.fullmatch(line.partition("\t")[0])
        ]
        if not values:
            raise GitInspectionError(f"remote reference {requested or 'HEAD'!r} is unavailable")
        return values[-1].lower()

    def _lock_state(self, root: Path, head: str, locked: str) -> str:
        if head == locked:
            return "current"
        if self._run(root, "merge-base", "--is-ancestor", locked, head).returncode == 0:
            return "ahead-of-lock"
        if self._run(root, "merge-base", "--is-ancestor", head, locked).returncode == 0:
            return "behind-lock"
        if self._run(root, "cat-file", "-e", f"{locked}^{{commit}}").returncode != 0:
            return "locked-commit-unavailable"
        return "diverged"

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
class RepositoryAddFacade:
    """User-facing syntax for declaring or adopting a Git repository."""

    name: str = "repository"
    verb: str = "add"
    description: str = "add a Git repository to the workspace composition"
    arguments: tuple[FacadeArgument, ...] = (
        FacadeArgument("node_id", ("node_id",), required=True),
        FacadeArgument("node_path", ("--path",), required=True, help="workspace-relative path"),
        FacadeArgument("parent", ("--parent",), help="parent node"),
        FacadeArgument("nature", ("--nature",), repeatable=True, help="declared nature"),
        FacadeArgument("repo", ("--repo",), help="Git repository URL"),
        FacadeArgument("ref", ("--ref",), help="branch, tag, or commit"),
        FacadeArgument("depth", ("--depth",), help="shallow clone depth (default: complete)"),
    )

    def translate(self, request: FacadeRequest) -> dict[str, str]:
        node_path = _facade_string(request, "node_path")
        parameters = dict(request.parameters)
        parameters.update(
            {
                "poly.node.id": _facade_string(request, "node_id"),
                "poly.node.path": node_path,
                "poly.node.kind": "repository",
                "poly.node.natures": ",".join(_facade_values(request, "nature")),
            }
        )
        parent = request.values.get("parent")
        if isinstance(parent, str) and parent:
            parameters["poly.node.parent"] = parent
        repository = request.values.get("repo")
        requested_ref = request.values.get("ref")
        existing = request.workspace / node_path
        if not repository and (existing / ".git").exists():
            repository = _git_value(existing, "remote", "get-url", "origin")
            requested_ref = requested_ref or _git_value(
                existing, "symbolic-ref", "--quiet", "--short", "HEAD"
            )
        if isinstance(repository, str) and repository:
            parameters["poly.source.url"] = _repository_url(repository)
        if isinstance(requested_ref, str) and requested_ref:
            parameters["poly.source.ref"] = requested_ref
        depth = request.values.get("depth")
        if isinstance(depth, str) and depth:
            parameters["poly.source.depth"] = _positive_depth(depth)
        return parameters


@dataclass(frozen=True, slots=True)
class GitPlanningProvider:
    name: str = GIT_DRIVER_NAME
    verbs: frozenset[str] = frozenset(("add", "bootstrap", "hydrate", "lock", "status", "update"))

    def propose(self, request: PlanningRequest) -> DriverProposal:
        if request.verb == "add":
            return self._add(request)
        if request.verb == "bootstrap":
            return self._bootstrap(request)
        if request.verb in {"hydrate", "update", "lock"}:
            return self._sources(request)
        return self._status(request)

    def _bootstrap(self, request: PlanningRequest) -> DriverProposal:
        url = request.parameters.get("poly.source.url", "").strip()
        path = request.parameters.get("poly.node.path", "").strip()
        if not url or not path:
            return DriverProposal(
                self.name,
                rejected=(
                    RejectedCandidate(
                        self.name,
                        "git/bootstrap",
                        "root bootstrap requires poly.source.url and poly.node.path",
                    ),
                ),
            )
        node_id = "root-bootstrap"
        resolution = f"poly/source-resolved:{node_id}"
        checkout = f"git/checkout-ready:{node_id}"
        available = f"git/commit-available:{node_id}"
        checked = f"git/head-checked:{node_id}"
        environment = {
            "poly.node.id": node_id,
            "poly.node.path": path,
            "poly.source.url": url,
            "poly.source.ref": request.parameters.get("poly.source.ref", ""),
            "poly.workspace.path": str(request.workspace or ""),
        }
        actions = (
            ActionSpec(
                "git.resolve:root-bootstrap",
                self.name,
                "bootstrap",
                "git/resolve-source",
                (),
                produces=frozenset((Constraint(resolution),)),
                claims=frozenset((ActionClaim("git/resolve-source", "node:root-bootstrap"),)),
                environment=environment,
                required_capability="git.materialize",
            ),
            self._materialization_action(
                "prepare", node_id, path, environment, resolution, checkout, "bootstrap"
            ),
            self._materialization_action(
                "fetch", node_id, path, environment, checkout, available, "bootstrap"
            ),
            self._materialization_action(
                "checkout", node_id, path, environment, available, checked, "bootstrap"
            ),
            ActionSpec(
                "git.verify:root-bootstrap",
                self.name,
                "bootstrap",
                "git/verify-head",
                (),
                requires=frozenset((Constraint(checked),)),
                claims=frozenset((ActionClaim("git/verify-head", "node:root-bootstrap"),)),
                environment=environment,
                required_capability="git.materialize",
            ),
        )
        return DriverProposal(self.name, actions)

    def _status(self, request: PlanningRequest) -> DriverProposal:
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

    def _add(self, request: PlanningRequest) -> DriverProposal:
        url = request.parameters.get("poly.source.url")
        if not url:
            return DriverProposal(self.name)
        node_id = request.parameters.get("poly.node.id", "").strip()
        path = request.parameters.get("poly.node.path", "").strip()
        if not node_id or not path:
            return DriverProposal(
                self.name,
                rejected=(
                    RejectedCandidate(
                        self.name,
                        "git/resolve-source",
                        "Git-backed add requires poly.node.id and poly.node.path",
                    ),
                ),
            )
        ref = request.parameters.get("poly.source.ref", "")
        resolution = f"poly/source-resolved:{node_id}"
        environment = {
            "poly.node.id": node_id,
            "poly.node.path": path,
            "poly.source.url": url,
            "poly.source.ref": ref,
            "poly.source.depth": request.parameters.get("poly.source.depth", ""),
            "poly.workspace.path": str(request.workspace or ""),
        }
        actions = (
            ActionSpec(
                f"git.resolve:{node_id}",
                self.name,
                "add",
                "git/resolve-source",
                (),
                produces=frozenset((Constraint(resolution),)),
                claims=frozenset((ActionClaim("git/resolve-source", f"node:{node_id}"),)),
                environment=environment,
                required_capability="git.materialize",
            ),
        )
        return DriverProposal(self.name, actions)

    def _sources(self, request: PlanningRequest) -> DriverProposal:
        actions: list[ActionSpec] = []
        rejected: list[RejectedCandidate] = []
        selected_sources = {
            node.id
            for node in request.inventory.select(request.selected_node_ids)
            if isinstance(node.metadata.get("poly.source.url"), str)
        }
        for node in request.inventory.select(request.selected_node_ids):
            url = node.metadata.get("poly.source.url")
            commit = node.metadata.get("poly.lock.commit")
            if not isinstance(url, str) or not isinstance(commit, str):
                continue
            environment = {
                "poly.node.id": node.id,
                "poly.node.path": node.path,
                "poly.source.url": url,
                "poly.source.ref": str(node.metadata.get("poly.source.ref") or ""),
                "poly.source.depth": str(
                    request.parameters.get("poly.source.depth")
                    or node.metadata.get("poly.source.depth")
                    or ""
                ),
                "poly.source.unshallow": request.parameters.get("poly.source.unshallow", ""),
                "poly.lock.commit": commit,
                "poly.lock.ref-kind": str(node.metadata.get("poly.lock.ref-kind") or "commit"),
                "poly.workspace.path": str(request.workspace or ""),
            }
            if request.verb == "lock":
                if request.parameters.get("poly.lock.from-workspace") != "true":
                    rejected.append(
                        RejectedCandidate(
                            self.name,
                            "git/lock-from-workspace",
                            "lock requires --from-workspace",
                            (node.id,),
                        )
                    )
                    continue
                actions.append(
                    ActionSpec(
                        f"git.lock:{node.id}",
                        self.name,
                        "lock",
                        "git/lock-from-workspace",
                        (node.id,),
                        requested_node_ids=(node.id,),
                        claims=frozenset(
                            (ActionClaim("git/lock-from-workspace", f"node:{node.id}"),)
                        ),
                        environment=environment,
                        changes_structure=True,
                        required_capability="git.materialize",
                    )
                )
                continue
            prerequisites: list[str] = []
            parent = node.metadata.get("poly.parent")
            if isinstance(parent, str) and parent in selected_sources:
                prerequisites.append(f"git/head-verified:{parent}")
            if request.verb == "update":
                resolution = f"poly/source-resolved:{node.id}"
                actions.append(
                    ActionSpec(
                        f"git.resolve:{node.id}",
                        self.name,
                        "update",
                        "git/resolve-source",
                        (node.id,),
                        requested_node_ids=(node.id,),
                        produces=frozenset((Constraint(resolution),)),
                        claims=frozenset((ActionClaim("git/resolve-source", f"node:{node.id}"),)),
                        environment=environment,
                        required_capability="git.materialize",
                    )
                )
                prerequisites.append(resolution)
            checkout = f"git/checkout-ready:{node.id}"
            available = f"git/commit-available:{node.id}"
            checked = f"git/head-checked:{node.id}"
            verified = f"git/head-verified:{node.id}"
            actions.extend(
                (
                    self._materialization_action(
                        "prepare",
                        node.id,
                        node.path,
                        environment,
                        tuple(prerequisites),
                        checkout,
                        request.verb,
                    ),
                    self._materialization_action(
                        "fetch",
                        node.id,
                        node.path,
                        environment,
                        checkout,
                        available,
                        request.verb,
                    ),
                    self._materialization_action(
                        "checkout",
                        node.id,
                        node.path,
                        environment,
                        available,
                        checked,
                        request.verb,
                    ),
                    ActionSpec(
                        f"git.verify:{node.id}",
                        self.name,
                        request.verb,
                        "git/verify-head",
                        (node.id,),
                        requested_node_ids=(node.id,),
                        requires=frozenset((Constraint(checked),)),
                        produces=frozenset((Constraint(verified),)),
                        claims=frozenset((ActionClaim("git/verify-head", f"node:{node.id}"),)),
                        environment=environment,
                        required_capability="git.materialize",
                    ),
                )
            )
            if request.verb == "update":
                actions.append(
                    ActionSpec(
                        f"git.update-lock:{node.id}",
                        self.name,
                        "update",
                        "git/update-lock",
                        (node.id,),
                        requested_node_ids=(node.id,),
                        requires=frozenset((Constraint(verified),)),
                        claims=frozenset((ActionClaim("git/update-lock", f"node:{node.id}"),)),
                        environment=environment,
                        changes_structure=True,
                        required_capability="git.materialize",
                    )
                )
        return DriverProposal(self.name, tuple(actions), tuple(rejected))

    def _materialization_action(
        self,
        phase: str,
        node_id: str,
        path: str,
        environment: dict[str, str],
        required: str | tuple[str, ...],
        produced: str,
        verb: str,
    ) -> ActionSpec:
        operation = f"git/{phase}"
        if phase == "prepare" and self._checkout_exists(path, environment):
            operation = "git/adopt"
        elif phase == "prepare":
            operation = "git/clone"
        new_node = verb in {"add", "bootstrap"}
        required_keys = (required,) if isinstance(required, str) and required else required
        return ActionSpec(
            f"git.{phase}:{node_id}",
            self.name,
            verb,
            operation,
            (() if new_node else (node_id,)),
            requested_node_ids=(() if new_node else (node_id,)),
            requires=frozenset(Constraint(item) for item in required_keys),
            produces=frozenset((Constraint(produced),)),
            claims=frozenset((ActionClaim(operation, f"path:{path}"),)),
            environment=environment,
            changes_structure=phase in {"prepare", "checkout"},
            required_capability="git.materialize",
        )

    def _checkout_exists(self, path: str, environment: dict[str, str]) -> bool:
        # The operation remains frozen; the handler revalidates the observed state.
        workspace = environment.get("poly.workspace.path")
        return bool(workspace and (Path(workspace) / path / ".git").exists())


@dataclass(frozen=True, slots=True)
class GitActionHandler:
    name: str = GIT_DRIVER_NAME
    command_timeout_seconds: float = 60.0
    clone_timeout_seconds: float = 600.0

    def execute(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        try:
            operation = action.operation
            if operation == "git/resolve-source":
                return self._resolve(action, context)
            if operation == "git/clone":
                return self._clone(action, context)
            if operation == "git/adopt":
                return self._adopt(action, context)
            if operation == "git/fetch":
                return self._fetch(action, context)
            if operation == "git/checkout":
                return self._checkout(action, context)
            if operation == "git/verify-head":
                return self._verify(action, context)
            if operation == "git/update-lock":
                return self._update_lock(action, context)
            if operation == "git/lock-from-workspace":
                return self._lock_from_workspace(action, context)
            return DriverExecutionResult(False, f"unsupported Git operation: {operation}")
        except (GitInspectionError, OSError, ValueError, WorkspaceError) as error:
            return DriverExecutionResult(False, str(error))

    def _resolve(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        url = action.environment["poly.source.url"]
        requested = action.environment.get("poly.source.ref") or None
        commit, ref_kind = self._resolve_remote(url, requested)
        node_id = action.environment["poly.node.id"]
        target = context.run_directory / "resolutions" / f"{node_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"commit": commit, "ref-kind": ref_kind}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return DriverExecutionResult(
            True,
            f"resolved {requested or 'HEAD'} to {commit}",
            {"commit": commit, "ref-kind": ref_kind},
        )

    def _resolve_remote(self, url: str, requested: str | None) -> tuple[str, str]:
        arguments = ["git", "ls-remote"]
        exact_commit = requested.lower() if requested and _COMMIT.fullmatch(requested) else None
        if requested is None:
            arguments.extend(("--symref", url, "HEAD"))
        elif exact_commit is not None:
            arguments.append(url)
        else:
            arguments.extend((url, requested, f"refs/heads/{requested}", f"refs/tags/{requested}*"))
        process = self._run_process(tuple(arguments))
        if process.returncode != 0:
            raise GitInspectionError(process.stderr.strip() or f"cannot resolve {url}")
        refs: dict[str, str] = {}
        head_kind = "commit"
        for line in process.stdout.splitlines():
            if line.startswith("ref:"):
                parts = line.split()
                if len(parts) >= 3 and parts[2] == "HEAD" and parts[1].startswith("refs/heads/"):
                    head_kind = "branch"
                continue
            commit, separator, ref_name = line.partition("\t")
            if separator and _COMMIT.fullmatch(commit):
                refs[ref_name] = commit.lower()
        if exact_commit is not None:
            if exact_commit in refs.values():
                return exact_commit, "commit"
            raise GitInspectionError(f"commit {requested!r} is not advertised by {url}")
        if requested is None:
            head_commit = refs.get("HEAD")
            if head_commit:
                return head_commit, head_kind
        else:
            tag = refs.get(f"refs/tags/{requested}^{{}}") or refs.get(f"refs/tags/{requested}")
            branch = refs.get(f"refs/heads/{requested}")
            direct = refs.get(requested)
            if requested.startswith("refs/heads/") and direct:
                return direct, "branch"
            if requested.startswith("refs/tags/") and direct:
                return direct, "tag"
            if branch:
                return branch, "branch"
            if tag:
                return tag, "tag"
            if direct:
                return direct, "commit"
        raise GitInspectionError(f"reference {requested or 'HEAD'!r} does not exist in {url}")

    def _clone(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        target = self._target(action, context)
        if (target / ".git").exists():
            return self._adopt(action, context)
        if target.exists() and any(target.iterdir()):
            raise GitInspectionError(f"clone target is not empty: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        process = self._git_process(
            context.workspace,
            "clone",
            "--no-checkout",
            *(
                ("--depth", action.environment["poly.source.depth"])
                if action.environment.get("poly.source.depth")
                else ()
            ),
            action.environment["poly.source.url"],
            str(target),
        )
        self._ensure_success(process, f"cannot clone {action.environment['poly.source.url']}")
        marker = context.run_directory / "cloned" / action.environment["poly.node.id"]
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("fresh\n", encoding="utf-8")
        persistent_marker = target / ".git" / "poly-fresh-clone"
        persistent_marker.write_text("fresh\n", encoding="utf-8")
        return DriverExecutionResult(True, f"cloned {target}")

    def _adopt(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        target = self._target(action, context)
        self._ensure_repository(target)
        partial = self._git(target, "config", "--get-regexp", r"^remote\..*\.promisor$")
        if partial.returncode == 0 and partial.stdout.strip():
            raise GitInspectionError(f"partial clone is unsupported: {target}")
        remote = self._git(target, "remote", "get-url", "origin")
        self._ensure_success(remote, f"repository has no origin remote: {target}")
        expected = self._normalize_url(action.environment["poly.source.url"], context.workspace)
        actual = self._normalize_url(remote.stdout.strip(), target)
        if actual != expected:
            raise GitInspectionError(
                f"origin URL mismatch for {target}: expected {expected!r}, found {actual!r}"
            )
        return DriverExecutionResult(True, f"adopted existing checkout {target}")

    def _fetch(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        target = self._target(action, context)
        commit, _kind = self._resolution(action, context)
        if action.environment.get("poly.source.unshallow") == "true":
            shallow = self._git(target, "rev-parse", "--is-shallow-repository")
            self._ensure_success(shallow, f"cannot inspect repository depth: {target}")
            if shallow.stdout.strip().lower() == "true":
                process = self._git(target, "fetch", "--unshallow", "--tags", "origin")
                self._ensure_success(process, f"cannot unshallow {target}")
                return DriverExecutionResult(True, f"unshallowed {target}")
        if self._has_commit(target, commit):
            return DriverExecutionResult(True, f"commit {commit} already available")
        process = self._git(target, "fetch", "--tags", "--prune", "origin")
        self._ensure_success(process, f"cannot fetch {target}")
        if not self._has_commit(target, commit):
            process = self._git(target, "fetch", "origin", commit)
            self._ensure_success(process, f"locked commit {commit} is unavailable from origin")
        return DriverExecutionResult(True, f"fetched locked commit {commit}")

    def _checkout(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        target = self._target(action, context)
        commit, ref_kind = self._resolution(action, context)
        run_marker = context.run_directory / "cloned" / action.environment["poly.node.id"]
        persistent_marker = target / ".git" / "poly-fresh-clone"
        fresh_checkout = run_marker.is_file() or persistent_marker.is_file()
        head = self._git(target, "rev-parse", "--verify", "HEAD")
        if head.returncode == 0 and head.stdout.strip() == commit:
            if fresh_checkout:
                self._ensure_success(
                    self._git(target, "reset", "--hard", commit),
                    f"cannot populate fresh checkout {target}",
                )
                persistent_marker.unlink(missing_ok=True)
            return DriverExecutionResult(True, f"HEAD already matches {commit}")
        if not fresh_checkout:
            status = self._git(target, "status", "--porcelain=v1", "--untracked-files=normal")
            self._ensure_success(status, f"cannot inspect worktree {target}")
            if status.stdout.strip():
                raise GitInspectionError(f"refusing to move dirty worktree: {target}")
        requested = action.environment.get("poly.source.ref", "")
        if ref_kind == "branch" and requested and not requested.startswith("refs/"):
            if fresh_checkout:
                self._ensure_success(
                    self._git(target, "checkout", "--force", "-B", requested, commit),
                    f"cannot populate fresh branch {requested}",
                )
                self._ensure_success(
                    self._git(target, "reset", "--hard", commit),
                    f"cannot populate fresh branch {requested}",
                )
            else:
                exists = self._git(target, "show-ref", "--verify", f"refs/heads/{requested}")
                if exists.returncode == 0:
                    self._ensure_success(
                        self._git(target, "checkout", requested),
                        f"cannot checkout branch {requested}",
                    )
                    self._ensure_success(
                        self._git(target, "merge", "--ff-only", commit),
                        f"branch {requested} cannot move safely to locked commit {commit}",
                    )
                else:
                    self._ensure_success(
                        self._git(target, "checkout", "--force", "-b", requested, commit),
                        f"cannot create branch {requested}",
                    )
                    self._ensure_success(
                        self._git(target, "reset", "--hard", commit),
                        f"cannot populate fresh branch {requested}",
                    )
        else:
            self._ensure_success(
                self._git(target, "checkout", "--force", "--detach", commit),
                f"cannot checkout locked commit {commit}",
            )
            self._ensure_success(
                self._git(target, "reset", "--hard", commit),
                f"cannot populate locked commit {commit}",
            )
        if fresh_checkout:
            persistent_marker.unlink(missing_ok=True)
        return DriverExecutionResult(True, f"checked out {commit}")

    def _verify(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        target = self._target(action, context)
        commit, _kind = self._resolution(action, context)
        head = self._git(target, "rev-parse", "--verify", "HEAD")
        self._ensure_success(head, f"cannot read HEAD for {target}")
        actual = head.stdout.strip()
        if actual != commit:
            raise GitInspectionError(
                f"HEAD mismatch for {target}: expected {commit}, found {actual}"
            )
        return DriverExecutionResult(True, f"verified HEAD {commit}", {"commit": commit})

    def _update_lock(self, action: ActionSpec, context: ExecutionContext) -> DriverExecutionResult:
        node_id = action.environment["poly.node.id"]
        commit, ref_kind = self._resolution(action, context)
        update_locked_sources(context.workspace, {node_id: (commit, ref_kind)})
        return DriverExecutionResult(True, f"updated lock for {node_id} to {commit}")

    def _lock_from_workspace(
        self, action: ActionSpec, context: ExecutionContext
    ) -> DriverExecutionResult:
        target = self._target(action, context)
        self._ensure_repository(target)
        status = self._git(target, "status", "--porcelain=v1", "--untracked-files=normal")
        self._ensure_success(status, f"cannot inspect worktree {target}")
        if status.stdout.strip():
            raise GitInspectionError(f"refusing to lock dirty worktree: {target}")
        head = self._git(target, "rev-parse", "--verify", "HEAD")
        self._ensure_success(head, f"cannot read HEAD for {target}")
        node_id = action.environment["poly.node.id"]
        ref_kind = action.environment.get("poly.lock.ref-kind", "commit")
        update_locked_sources(context.workspace, {node_id: (head.stdout.strip(), ref_kind)})
        return DriverExecutionResult(
            True, f"adopted local HEAD for {node_id}: {head.stdout.strip()}"
        )

    def _resolution(self, action: ActionSpec, context: ExecutionContext) -> tuple[str, str]:
        node_id = action.environment["poly.node.id"]
        resolution_path = context.run_directory / "resolutions" / f"{node_id}.json"
        if resolution_path.is_file():
            value = json.loads(resolution_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return str(value["commit"]), str(value["ref-kind"])
        compiled = validate_workspace(context.workspace)
        source = next(item for item in compiled.lock.sources if item.node_id == node_id)
        return source.commit, source.ref_kind

    def _target(self, action: ActionSpec, context: ExecutionContext) -> Path:
        return (context.workspace / action.environment["poly.node.path"]).resolve()

    def _ensure_repository(self, target: Path) -> None:
        if not (target / ".git").exists():
            raise GitInspectionError(f"target is not a Git checkout: {target}")

    def _has_commit(self, target: Path, commit: str) -> bool:
        return self._git(target, "cat-file", "-e", f"{commit}^{{commit}}").returncode == 0

    def _git(self, directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self._run_process(("git", "-C", str(directory), *arguments))

    def _git_process(self, directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self._run_process(
            ("git", "-C", str(directory), *arguments),
            timeout_seconds=self.clone_timeout_seconds,
        )

    def _run_process(
        self, command: tuple[str, ...], *, timeout_seconds: float | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=(
                    self.command_timeout_seconds if timeout_seconds is None else timeout_seconds
                ),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GitInspectionError(f"cannot execute {' '.join(command)}: {error}") from error

    def _ensure_success(self, process: subprocess.CompletedProcess[str], message: str) -> None:
        if process.returncode != 0:
            raise GitInspectionError(f"{message}: {process.stderr.strip()}")

    def _normalize_url(self, value: str, relative_to: Path) -> str:
        if value.startswith("file://"):
            parsed = urlsplit(value)
            file_path = unquote(parsed.path)
            if os.name == "nt" and file_path.startswith("/"):
                file_path = file_path[1:]
            return str(Path(file_path).resolve()).removesuffix(".git")
        if "://" in value or value.startswith("git@"):
            return value.removesuffix("/").removesuffix(".git")
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = relative_to / candidate
        return str(candidate.resolve()).removesuffix(".git")


def git_driver() -> DriverRegistration:
    manifest = DriverManifest(
        name=GIT_DRIVER_NAME,
        version="0.1.0",
        api_version=DRIVER_API_VERSION,
        capabilities=frozenset(
            (
                DriverCapability.FACADE,
                DriverCapability.INSPECT,
                DriverCapability.PLAN,
                DriverCapability.EXECUTE,
            )
        ),
        description="Git repository inspection, materialization, and lock management",
        natures=("git/repository",),
    )
    return DriverRegistration(
        manifest=manifest,
        inspectors=(GitInspectionProvider(),),
        planners=(GitPlanningProvider(),),
        handlers=(GitActionHandler(),),
        facades=(RepositoryAddFacade(),),
    )


def _facade_string(request: FacadeRequest, name: str) -> str:
    value = request.values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise GitInspectionError(f"facade argument {name!r} is required")
    return value


def _facade_values(request: FacadeRequest, name: str) -> tuple[str, ...]:
    value = request.values.get(name)
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    return (value,)


def _git_value(directory: Path, *arguments: str) -> str | None:
    process = subprocess.run(
        ("git", "-C", str(directory), *arguments),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    value = process.stdout.strip()
    return value if process.returncode == 0 and value else None


def _repository_url(value: str) -> str:
    if "://" in value or value.startswith("git@"):
        return value
    candidate = Path(value)
    if candidate.is_absolute() or candidate.exists():
        return candidate.resolve().as_uri()
    return value


def _positive_depth(value: str) -> str:
    try:
        depth = int(value)
    except ValueError as error:
        raise ValueError("Git clone depth must be a positive integer") from error
    if depth < 1:
        raise ValueError("Git clone depth must be a positive integer")
    return str(depth)


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
