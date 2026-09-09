from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

import pytest

from poly.cli import main
from poly.driver import ExecutionContext, FacadeRequest
from poly.driver.testkit import assert_manifest_compatible, assert_planning_deterministic
from poly.drivers.eclipse import (
    PAYLOAD,
    PROFILE,
    PROJECT,
    EclipseDriver,
    EclipseFacade,
    _managed,
    _name,
    _path,
    eclipse_driver,
)
from poly.model import Inventory, Node, PlanningRequest
from poly.planning import Planner


def _request(workspace: Path) -> PlanningRequest:
    nodes = (
        Node("git:root", ".", ("git/repository",)),
        Node("git:api", "services/api é & #", ("git/repository",)),
        Node("maven:api", "services/api é & #", ("maven/project",)),
        Node("git:web", "web", ("git/repository",)),
    )
    for node in nodes:
        (workspace / node.path).mkdir(parents=True, exist_ok=True)
    return PlanningRequest(
        "configure",
        Inventory(nodes),
        tuple(node.id for node in nodes),
        {"tool": "eclipse", "poly.selection.mode": "implicit"},
        workspace=workspace,
    )


def _context(workspace: Path) -> ExecutionContext:
    return ExecutionContext(workspace, workspace / ".poly/runs/eclipse")


def test_navigation_generation_lifecycle(tmp_path: Path) -> None:
    request = _request(tmp_path)
    provider = EclipseDriver()
    registration = eclipse_driver()
    registration.validate()
    assert_manifest_compatible(registration.manifest)
    proposal = assert_planning_deterministic(provider, request, tmp_path)
    assert not proposal.rejected
    (action,) = proposal.actions
    assert action.requested_node_ids == ("git:api", "git:web", "maven:api")
    assert {claim.scope for claim in action.claims} == {PROFILE, PROJECT}
    assert action.execution_resources and not action.changes_structure
    payload = json.loads(action.environment[PAYLOAD])
    assert set(payload["changes"].values()) == {"create"}
    result = provider.execute(action, _context(tmp_path))
    assert result.success and result.details["changed_files"] == 2
    assert {Path(output.target).relative_to(tmp_path).as_posix() for output in result.outputs} == {
        PROFILE,
        PROJECT,
    }
    project = tmp_path / PROJECT
    tree = ET.fromstring(project.read_bytes())
    assert tree.findtext("name") == tmp_path.name + "-navigation"
    links = tree.findall("linkedResources/link")
    assert len(links) == 2  # Same-path Git and Maven observations share one folder.
    assert {unquote(link.findtext("locationURI", "")) for link in links} == {
        "PARENT-1-PROJECT_LOC/services/api é & #",
        "PARENT-1-PROJECT_LOC/web",
    }
    assert str(tmp_path) not in project.read_text()
    before = project.stat().st_mtime_ns
    profile_before = (tmp_path / PROFILE).stat().st_mtime_ns
    (tmp_path / ".eclipse/custom.txt").write_text("user customization")
    second = provider.propose(request).actions[0]
    assert json.loads(second.environment[PAYLOAD])["changes"][PROJECT] == "unchanged"
    assert provider.execute(second, _context(tmp_path)).details["changed_files"] == 0
    assert project.stat().st_mtime_ns == before
    assert (tmp_path / PROFILE).stat().st_mtime_ns == profile_before

    # Editing authored intent regenerates only the managed project.
    profile = json.loads((tmp_path / PROFILE).read_text())
    profile["project_name"] = "QC navigation"
    profile["nodes"] = ["git:web"]
    (tmp_path / PROFILE).write_text(json.dumps(profile))
    third = provider.propose(request).actions[0]
    assert provider.execute(third, _context(tmp_path)).success
    assert ET.fromstring(project.read_bytes()).findtext("name") == "QC navigation"
    assert (tmp_path / ".eclipse/custom.txt").read_text() == "user customization"


@pytest.mark.parametrize("relative", [PROFILE, PROJECT, "poly.yaml", "poly.lock.yaml"])
def test_stale_inputs_refuse_all_writes(tmp_path: Path, relative: str) -> None:
    request = _request(tmp_path)
    provider = EclipseDriver()
    action = provider.propose(request).actions[0]
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("intervening user edit")
    result = provider.execute(action, _context(tmp_path))
    assert not result.success and "stale plan" in result.summary
    assert target.read_text() == "intervening user edit"
    assert not result.outputs


@pytest.mark.parametrize("content", ["manual", "<?xml version='1.0'?><projectDescription/>"])
def test_unmanaged_project_is_preserved(tmp_path: Path, content: str) -> None:
    request = _request(tmp_path)
    target = tmp_path / PROJECT
    target.parent.mkdir()
    target.write_text(content)
    proposal = EclipseDriver().propose(request)
    assert proposal.actions[0].requires and "manually modified" in proposal.rejected[0].reason
    assert target.read_text() == content
    assert Planner((EclipseDriver(),)).negotiate(request).status == "blocked"
    assert not EclipseDriver().execute(proposal.actions[0], _context(tmp_path)).success


def test_modified_managed_project_is_rejected(tmp_path: Path) -> None:
    request = _request(tmp_path)
    provider = EclipseDriver()
    assert provider.execute(provider.propose(request).actions[0], _context(tmp_path)).success
    project = tmp_path / PROJECT
    project.write_bytes(project.read_bytes().replace(b"navigation", b"custom", 1))
    assert provider.propose(request).rejected


@pytest.mark.parametrize("profile", ["not json", "[]", "{}", '{"schema":"future"}'])
def test_invalid_profile(tmp_path: Path, profile: str) -> None:
    request = _request(tmp_path)
    (tmp_path / PROFILE).write_text(profile)
    assert EclipseDriver().propose(request).rejected


def test_missing_selection_and_target(tmp_path: Path) -> None:
    request = _request(tmp_path)
    provider = EclipseDriver()
    action = provider.propose(request).actions[0]
    (tmp_path / "web").rmdir()
    assert "hydrate explicitly" in provider.propose(request).rejected[0].reason
    assert not provider.execute(action, _context(tmp_path)).success
    assert provider.propose(replace(request, selected_node_ids=())).rejected
    root = replace(request, selected_node_ids=("git:root",), parameters={"tool": "eclipse"})
    assert "select subdirectories" in provider.propose(root).rejected[0].reason


def test_profile_selection_cannot_silently_change(tmp_path: Path) -> None:
    request = _request(tmp_path)
    provider = EclipseDriver()
    assert provider.execute(provider.propose(request).actions[0], _context(tmp_path)).success
    override = replace(request, selected_node_ids=("git:web",), parameters={"tool": "eclipse"})
    assert "edit user-owned" in provider.propose(override).rejected[0].reason
    renamed = replace(request, parameters={**request.parameters, "eclipse.name": "other"})
    assert "edit user-owned" in provider.propose(renamed).rejected[0].reason
    missing = replace(request, selected_node_ids=("git:web",))
    assert "nodes are missing" in provider.propose(missing).rejected[0].reason


@pytest.mark.parametrize("path", ["../escape", "C:/escape", "C:escape", "a\\b", "/tmp", "a\n"])
def test_nonportable_paths_rejected(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        _path(tmp_path, path)


@pytest.mark.parametrize("name", ["", "..", "x/xx", "CON", "LPT1", " x", "x.", "a\x7f"])
def test_nonportable_names_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="portable"):
        _name(name)


def test_symlinks_rejected_before_and_after_planning(tmp_path: Path) -> None:
    request = _request(tmp_path)
    provider = EclipseDriver()
    action = provider.propose(request).actions[0]
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (tmp_path / ".eclipse").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted")
    assert not provider.execute(action, _context(tmp_path)).success
    assert "linked filesystem" in provider.propose(request).rejected[0].reason
    assert not list(outside.iterdir())


def test_facade_and_non_applicability(tmp_path: Path) -> None:
    facade = EclipseFacade()
    assert facade.translate(FacadeRequest(tmp_path, {"name": "QC"}, {"extra": "x"})) == {
        "tool": "eclipse",
        "eclipse.name": "QC",
        "extra": "x",
    }
    provider = EclipseDriver()
    request = _request(tmp_path)
    assert not provider.propose(replace(request, parameters={})).actions
    assert not provider.propose(replace(request, verb="build")).actions
    assert provider.propose(replace(request, workspace=None)).rejected
    assert not _managed(b"manual")


def test_cli_deferred_and_reconstruction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--format", "json"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "add",
                "module",
                "api",
                "--path",
                "api",
                "--workspace",
                str(tmp_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    (tmp_path / "api").mkdir(exist_ok=True)
    args = ["configure", "eclipse", "--workspace", str(tmp_path), "--format", "json"]
    assert main([*args, "--prepare", "--select", "api"]) == 0
    capsys.readouterr()
    assert not (tmp_path / PROJECT).exists()
    assert main(["exec", "--workspace", str(tmp_path), "--format", "json"]) == 0
    capsys.readouterr()
    before = (tmp_path / PROJECT).read_bytes()
    shutil.rmtree(tmp_path / ".poly")
    assert main(args) == 0
    capsys.readouterr()
    assert (tmp_path / PROJECT).read_bytes() == before
    (tmp_path / PROJECT).write_text("manual")
    assert main([*args, "--plan"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["plan"]["status"] == "blocked"
    assert main(args) == 1
    capsys.readouterr()
    assert (tmp_path / PROJECT).read_text() == "manual"
    assert main(["configure", "eclipse", "--workspace", str(tmp_path), "--plan"]) == 1
    assert "user-owned or manually modified" in capsys.readouterr().out


def test_delivery_failure_exposes_completed_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    provider = EclipseDriver()
    action = provider.propose(request).actions[0]
    original_mkdir = Path.mkdir

    def fail_project_directory(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if path == tmp_path / ".eclipse":
            raise PermissionError("project directory is read-only")
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", fail_project_directory)
    result = provider.execute(action, _context(tmp_path))
    assert not result.success and "read-only" in result.summary
    assert [output.label for output in result.outputs] == [PROFILE]
    monkeypatch.undo()
    assert provider.execute(provider.propose(request).actions[0], _context(tmp_path)).success


def test_cli_plan_and_execute(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "api").mkdir()
    (tmp_path / "api/pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion><groupId>test</groupId>"
        "<artifactId>api</artifactId><version>1</version></project>"
    )
    arguments = ["configure", "eclipse", "--workspace", str(tmp_path), "--format", "json"]
    assert main([*arguments, "--plan"]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["plan"]["status"] == "executable"
    assert not (tmp_path / PROFILE).exists()
    assert main(arguments) == 0
    executed = json.loads(capsys.readouterr().out)
    assert executed["run"]["status"] == "succeeded"
    assert (tmp_path / PROJECT).is_file()
    assert main(arguments) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "run",
                "configure",
                "--workspace",
                str(tmp_path),
                "--parameter",
                "tool=eclipse",
                "--format",
                "json",
            ]
        )
        == 0
    )
