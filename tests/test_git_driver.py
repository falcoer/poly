from __future__ import annotations

import subprocess
from pathlib import Path

from poly.driver import DriverCapability, InspectionContext
from poly.driver.testkit import (
    assert_inspection_side_effect_free,
    assert_manifest_compatible,
    assert_planning_deterministic,
)
from poly.drivers.git import (
    GIT_DRIVER_NAME,
    GitInspectionProvider,
    GitPlanningProvider,
    git_driver,
)
from poly.model import Inventory, Node, PlanningRequest
from poly.planning import Planner


def _git(path: Path, *arguments: str) -> str:
    process = subprocess.run(
        ("git", "-C", str(path), *arguments),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return process.stdout.strip()


def _repository(path: Path, filename: str = "tracked.txt") -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(("git", "init", "-b", "main", str(path)), check=True, capture_output=True)
    _git(path, "config", "user.name", "Poly Test")
    _git(path, "config", "user.email", "poly@example.invalid")
    (path / filename).write_text("initial\n")
    _git(path, "add", filename)
    _git(path, "commit", "-m", "initial")
    return _git(path, "rev-parse", "HEAD")


def test_git_driver_manifest_uses_public_sdk() -> None:
    registration = git_driver()
    registration.validate()
    assert_manifest_compatible(registration.manifest)
    assert registration.manifest.name == GIT_DRIVER_NAME
    assert registration.manifest.capabilities == frozenset(
        (DriverCapability.INSPECT, DriverCapability.PLAN, DriverCapability.EXECUTE)
    )


def test_inspection_discovers_root_and_nested_repositories(tmp_path: Path) -> None:
    root_head = _repository(tmp_path)
    nested = tmp_path / "tools" / "nested"
    nested_head = _repository(nested, "nested.txt")
    (nested / "untracked.txt").write_text("dirty")

    result = GitInspectionProvider().inspect(InspectionContext(tmp_path))

    assert result.diagnostics == ()
    assert [node.id for node in result.nodes] == ["git:.", "git:tools/nested"]
    root, child = result.nodes
    assert root.metadata["git.branch"] == "main"
    assert root.metadata["git.head"] == root_head
    assert root.metadata["git.clean"] is False  # nested repository is untracked by root
    assert child.metadata["git.head"] == nested_head
    assert child.metadata["git.clean"] is False
    assert child.relations[0].kind == "git/nested-under"
    assert child.relations[0].target == root.id


def test_inspection_is_repeatable_and_read_only(tmp_path: Path) -> None:
    _repository(tmp_path)
    provider = GitInspectionProvider()
    assert_inspection_side_effect_free(provider, InspectionContext(tmp_path))


def test_status_planning_accepts_git_nodes_and_explains_rejections(tmp_path: Path) -> None:
    _repository(tmp_path)
    inspected = GitInspectionProvider().inspect(InspectionContext(tmp_path))
    non_git = Node("docs", "docs", ("documentation",))
    inventory = Inventory((*inspected.nodes, non_git))
    request = PlanningRequest("status", inventory, ("git:.", "docs"), {"strategy": "short"})
    provider = GitPlanningProvider()

    proposal = assert_planning_deterministic(provider, request, tmp_path)
    plan = Planner((provider,)).negotiate(request)

    assert [action.id for action in proposal.actions] == ["git.status:git:."]
    assert proposal.actions[0].command == (
        "git",
        "-C",
        ".",
        "status",
        "--short",
        "--branch",
    )
    assert proposal.rejected[0].missing == ("nature:git/repository",)
    assert plan.ready_action_ids == ("git.status:git:.",)
