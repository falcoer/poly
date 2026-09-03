from __future__ import annotations

import json
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from poly.cli import main
from poly.workspace import validate_workspace


def _git(directory: Path, *arguments: str) -> str:
    process = subprocess.run(
        ("git", "-C", str(directory), *arguments),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return process.stdout.strip()


def _configure(directory: Path) -> None:
    _git(directory, "config", "user.email", "poly@example.test")
    _git(directory, "config", "user.name", "Poly Test")


def _remote(tmp_path: Path, name: str = "service") -> tuple[Path, Path, str]:
    source = tmp_path / f"{name}-source"
    source.mkdir()
    _git(source, "init", "--quiet")
    _configure(source)
    (source / "content.txt").write_text("one\n", encoding="utf-8")
    _git(source, "add", "content.txt")
    _git(source, "commit", "--quiet", "-m", "initial")
    _git(source, "branch", "-M", "main")
    remote = tmp_path / f"{name}.git"
    subprocess.run(("git", "clone", "--quiet", "--bare", str(source), str(remote)), check=True)
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    return source, remote, _git(source, "rev-parse", "HEAD")


def _advance(source: Path, text: str) -> str:
    (source / "content.txt").write_text(text, encoding="utf-8")
    _git(source, "add", "content.txt")
    _git(source, "commit", "--quiet", "-m", text.strip())
    if not _git(source, "remote"):
        raise AssertionError("source has no remote")
    _git(source, "push", "--quiet", "origin", "main")
    return _git(source, "rev-parse", "HEAD")


def _attach_source(source: Path, remote: Path) -> None:
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "--quiet", "-u", "origin", "main")


def test_add_hydrate_eclipse_pull_lock_and_update_journey(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, remote, initial = _remote(tmp_path)
    _attach_source(source, remote)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init", "--quiet")
    _configure(workspace)

    assert main(["init", "--workspace", str(workspace), "--name", "Daily"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "add",
                "repository",
                "service",
                "--workspace",
                str(workspace),
                "--path",
                "services/service",
                "--repo",
                str(remote),
                "--ref",
                "main",
                "--format",
                "json",
            ]
        )
        == 0
    )
    added = json.loads(capsys.readouterr().out)
    operations = {action["operation"] for action in added["plan"]["planned_actions"]}
    assert operations == {"git/resolve-source", "poly/construction/add"}
    assert operations.isdisjoint({"git/clone", "git/fetch", "git/checkout", "git/adopt"})
    child = workspace / "services" / "service"
    assert not child.exists()
    assert validate_workspace(workspace).lock.sources[0].commit == initial

    assert main(["hydrate", "--workspace", str(workspace), "--select", "service"]) == 0
    capsys.readouterr()
    assert _git(child, "rev-parse", "HEAD") == initial

    second = _advance(source, "two\n")
    assert main(["inspect", "--remote", "--workspace", str(workspace), "--format", "json"]) == 0
    remote_inspection = json.loads(capsys.readouterr().out)
    remote_service = next(
        node for node in remote_inspection["inventory"]["nodes"] if node["id"] == "service"
    )
    assert remote_service["metadata"]["git.remote.commit"] == second
    assert remote_service["metadata"]["git.remote.lock-state"] == "advanced"

    _git(child, "fetch", "--quiet", "origin", "main")
    _git(child, "merge", "--ff-only", "FETCH_HEAD")
    assert main(["inspect", "--workspace", str(workspace), "--format", "json"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    service = next(node for node in inspected["inventory"]["nodes"] if node["id"] == "service")
    assert service["metadata"]["git.lock.state"] == "ahead-of-lock"
    assert service["metadata"]["git.head"] == second
    assert service["metadata"]["poly.lock.commit"] == initial

    assert (
        main(
            [
                "lock",
                "--from-workspace",
                "--workspace",
                str(workspace),
                "--select",
                "service",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert validate_workspace(workspace).lock.sources[0].commit == second

    third = _advance(source, "three\n")
    assert main(["update", "--workspace", str(workspace), "--select", "service"]) == 0
    capsys.readouterr()
    assert _git(child, "rev-parse", "HEAD") == third
    assert validate_workspace(workspace).lock.sources[0].commit == third

    # Git for Windows can mark packed or hard-linked objects as read-only.
    # Clear that bit before simulating a checkout removed outside Poly.
    for entry in child.rglob("*"):
        entry.chmod(entry.stat().st_mode | stat.S_IWUSR)
    shutil.rmtree(child)
    assert main(["hydrate", "--workspace", str(workspace), "--select", "service"]) == 0
    capsys.readouterr()
    assert _git(child, "rev-parse", "HEAD") == third
    assert main(["hydrate", "--workspace", str(workspace), "--select", "service"]) == 0
    repeated = capsys.readouterr().out
    assert "already matches" in repeated

    _git(workspace, "add", ".")
    staged = set(_git(workspace, "diff", "--cached", "--name-only").splitlines())
    assert "services/service/content.txt" not in staged
    assert {".gitignore", "poly.yaml", "poly.lock.yaml"}.issubset(staged)


def test_three_repository_additions_share_one_prepared_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    remotes = {name: _remote(tmp_path, name)[1] for name in ("alpha", "beta", "gamma")}
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert main(["init", "--workspace", str(workspace), "--name", "Prepared sources"]) == 0
    capsys.readouterr()
    authored = {
        name: (workspace / name).read_bytes()
        for name in ("poly.yaml", "poly.lock.yaml", ".gitignore")
    }

    for name, remote in remotes.items():
        assert (
            main(
                [
                    "add",
                    "repository",
                    name,
                    "--path",
                    f"repos/{name}",
                    "--repo",
                    str(remote),
                    "--ref",
                    "main",
                    "--workspace",
                    str(workspace),
                    "--prepare",
                    "--format",
                    "json",
                ]
            )
            == 0
        )
        capsys.readouterr()
        assert {filename: (workspace / filename).read_bytes() for filename in authored} == authored

    assert main(["plan", "--workspace", str(workspace), "--format", "json"]) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["kind"] == "prepared-commands"
    assert prepared["prepared"]["command_count"] == 3
    assert len(prepared["prepared"]["commands"]) == 3
    assert "plan" not in prepared

    assert main(["exec", "--workspace", str(workspace), "--format", "json"]) == 0
    executed = json.loads(capsys.readouterr().out)
    assert isinstance(executed["run"]["plan_id"], str)
    assert {source.node_id for source in validate_workspace(workspace).lock.sources} == set(remotes)


def test_existing_checkout_is_adopted_and_dirty_update_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, remote, initial = _remote(tmp_path, "existing")
    _attach_source(source, remote)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert main(["init", "--workspace", str(workspace), "--name", "Adopt"]) == 0
    capsys.readouterr()
    existing = workspace / "existing"
    subprocess.run(("git", "clone", "--quiet", str(remote), str(existing)), check=True)

    assert (
        main(
            [
                "add",
                "repository",
                "existing",
                "--workspace",
                str(workspace),
                "--path",
                "existing",
            ]
        )
        == 0
    )
    report = capsys.readouterr().out
    assert "git/adopt" not in report
    assert validate_workspace(workspace).lock.sources[0].commit == initial
    assert main(["hydrate", "--workspace", str(workspace), "--select", "existing"]) == 0
    report = capsys.readouterr().out
    assert "git/adopt" in report

    advanced = _advance(source, "advanced\n")
    (existing / "local.txt").write_text("dirty\n", encoding="utf-8")
    assert main(["update", "--workspace", str(workspace), "--select", "existing"]) == 1
    failed = capsys.readouterr().out
    assert "refusing to move dirty worktree" in failed
    assert validate_workspace(workspace).lock.sources[0].commit == initial
    assert _git(existing, "rev-parse", "HEAD") != advanced


def test_root_bootstrap_recursively_restores_two_locked_children(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first_source, first_remote, first_commit = _remote(tmp_path, "first")
    second_source, second_remote, second_commit = _remote(tmp_path, "second")
    _attach_source(first_source, first_remote)
    _attach_source(second_source, second_remote)

    control = tmp_path / "control"
    control.mkdir()
    _git(control, "init", "--quiet")
    _configure(control)
    assert main(["init", "--workspace", str(control), "--name", "Bootstrap"]) == 0
    capsys.readouterr()
    for node_id, path, remote, parent in (
        ("first", "children/first", first_remote, None),
        ("second", "nested", second_remote, "first"),
    ):
        assert (
            main(
                [
                    "add",
                    "repository",
                    node_id,
                    "--workspace",
                    str(control),
                    "--path",
                    path,
                    "--repo",
                    str(remote),
                    "--ref",
                    "main",
                    *(["--parent", parent] if parent else []),
                ]
            )
            == 0
        )
        capsys.readouterr()
    _git(control, "add", ".")
    _git(control, "commit", "--quiet", "-m", "workspace composition")
    _git(control, "branch", "-M", "main")
    control_remote = tmp_path / "control.git"
    subprocess.run(
        ("git", "clone", "--quiet", "--bare", str(control), str(control_remote)), check=True
    )
    _git(control_remote, "symbolic-ref", "HEAD", "refs/heads/main")

    restored = tmp_path / "restored"
    assert (
        main(
            [
                "init",
                str(control_remote),
                str(restored),
                "--ref",
                "main",
                "--format",
                "json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["kind"] == "bootstrap"
    assert [phase["name"] for phase in report["phases"]] == [
        "root-bootstrap",
        "recursive-hydration",
    ]
    assert _git(restored / "children" / "first", "rev-parse", "HEAD") == first_commit
    assert _git(restored / "children" / "first" / "nested", "rev-parse", "HEAD") == second_commit

    (restored / "children" / "first" / "content.txt").write_text("local change\n", encoding="utf-8")
    assert _git(restored, "status", "--porcelain") == ""


def test_tag_and_full_sha_references_are_locked_immutably(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, remote, commit = _remote(tmp_path, "refs")
    _attach_source(source, remote)
    _git(source, "tag", "v1")
    _git(source, "push", "--quiet", "origin", "v1")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert main(["init", "--workspace", str(workspace), "--name", "Refs"]) == 0
    capsys.readouterr()

    for node_id, reference in (("tagged", "v1"), ("pinned", commit)):
        assert (
            main(
                [
                    "add",
                    "repository",
                    node_id,
                    "--workspace",
                    str(workspace),
                    "--path",
                    node_id,
                    "--repo",
                    str(remote),
                    "--ref",
                    reference,
                ]
            )
            == 0
        )
        capsys.readouterr()

    locked = {source.node_id: source for source in validate_workspace(workspace).lock.sources}
    assert locked["tagged"].commit == commit
    assert locked["tagged"].ref_kind == "tag"
    assert locked["pinned"].commit == commit
    assert locked["pinned"].ref_kind == "commit"


def test_add_resolution_failure_preserves_all_composition_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _source, remote, _commit = _remote(tmp_path, "failure")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert main(["init", "--workspace", str(workspace), "--name", "Atomic"]) == 0
    capsys.readouterr()
    paths = (
        workspace / "poly.yaml",
        workspace / "poly.lock.yaml",
        workspace / ".gitignore",
        workspace / ".poly" / "state" / "workspace.json",
    )
    before = {path: path.read_bytes() for path in paths}

    assert (
        main(
            [
                "add",
                "repository",
                "broken",
                "--workspace",
                str(workspace),
                "--path",
                "broken",
                "--repo",
                str(remote),
                "--ref",
                "does-not-exist",
            ]
        )
        == 1
    )
    assert "does not exist" in capsys.readouterr().out
    assert {path: path.read_bytes() for path in paths} == before
    assert not (workspace / "broken").exists()


def test_add_rolls_back_a_mid_transaction_write_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert main(["init", "--workspace", str(workspace), "--name", "Rollback"]) == 0
    capsys.readouterr()
    paths = (
        workspace / "poly.yaml",
        workspace / "poly.lock.yaml",
        workspace / ".gitignore",
        workspace / ".poly" / "state" / "workspace.json",
    )
    before = {path: path.read_bytes() for path in paths}
    original_replace = Path.replace

    def fail_lock_replacement(path: Path, target: Path) -> Path:
        if path.suffix == ".tmp" and target == workspace / "poly.lock.yaml":
            raise OSError("simulated lock replacement failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_lock_replacement)
    assert (
        main(
            [
                "add",
                "module",
                "module",
                "--workspace",
                str(workspace),
                "--path",
                "module",
            ]
        )
        == 1
    )
    assert "simulated lock replacement failure" in capsys.readouterr().out
    assert {path: path.read_bytes() for path in paths} == before
    assert not list(workspace.glob(".*.tmp"))
    assert not list(workspace.glob(".*.bak"))
