from __future__ import annotations

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


def test_hydrate_fresh_clone_when_locked_commit_precedes_remote_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "--quiet")
    _configure(source)
    (source / "content.txt").write_text("locked\n", encoding="utf-8")
    _git(source, "add", "content.txt")
    _git(source, "commit", "--quiet", "-m", "locked")
    _git(source, "branch", "-M", "main")
    locked = _git(source, "rev-parse", "HEAD")

    remote = tmp_path / "remote.git"
    subprocess.run(("git", "clone", "--quiet", "--bare", str(source), str(remote)), check=True)
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(source, "remote", "add", "origin", str(remote))

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert main(["init", "--workspace", str(workspace), "--name", "Locked hydration"]) == 0
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
                "service",
                "--repo",
                str(remote),
                "--ref",
                "main",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert validate_workspace(workspace).lock.sources[0].commit == locked

    (source / "content.txt").write_text("remote advanced\n", encoding="utf-8")
    _git(source, "add", "content.txt")
    _git(source, "commit", "--quiet", "-m", "remote advanced")
    _git(source, "push", "--quiet", "origin", "main")
    advanced = _git(source, "rev-parse", "HEAD")
    assert advanced != locked

    assert main(["hydrate", "--workspace", str(workspace), "--select", "service"]) == 0
    output = capsys.readouterr().out
    checkout = workspace / "service"
    assert "refusing to move dirty worktree" not in output
    assert _git(checkout, "rev-parse", "HEAD") == locked
    assert _git(checkout, "status", "--porcelain=v1", "--untracked-files=normal") == ""
    assert not (checkout / ".git" / "poly-fresh-clone").exists()

    assert main(["hydrate", "--workspace", str(workspace), "--select", "service"]) == 0
    capsys.readouterr()
    assert _git(checkout, "rev-parse", "HEAD") == locked
    assert _git(checkout, "status", "--porcelain=v1", "--untracked-files=normal") == ""
