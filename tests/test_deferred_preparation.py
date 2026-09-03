from __future__ import annotations

import json
from pathlib import Path

import pytest

import poly.cli as cli


def _init(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["init", "--workspace", str(workspace), "--name", "Deferred"]) == 0
    capsys.readouterr()


def test_prepare_does_not_inspect_or_plan(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path, capsys)
    authored = {
        name: (tmp_path / name).read_bytes()
        for name in ("poly.yaml", "poly.lock.yaml", ".gitignore")
    }

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("prepare must not inspect or plan")

    monkeypatch.setattr(cli, "inspect_workspace", forbidden)
    monkeypatch.setattr(cli, "prepare_planning", forbidden)

    assert (
        cli.main(
            [
                "add",
                "module",
                "api",
                "--path",
                "services/api",
                "--workspace",
                str(tmp_path),
                "--prepare",
                "--format",
                "json",
            ]
        )
        == 0
    )
    document = json.loads(capsys.readouterr().out)
    assert document["kind"] == "prepared-commands"
    assert document["prepared"]["command_count"] == 1
    assert "plan" not in document
    assert {name: (tmp_path / name).read_bytes() for name in authored} == authored


def test_prepare_cli_renders_planned_not_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init(tmp_path, capsys)

    assert (
        cli.main(
            [
                "add",
                "module",
                "api",
                "--path",
                "api",
                "--workspace",
                str(tmp_path),
                "--prepare",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "○ PLANNED  poly add" in output
    assert "1 command in current plan" in output
    assert "Run `poly exec` when the plan is ready." in output
    assert "SUCCESS" not in output
    assert "executable" not in output
    assert "action(s)" not in output


def test_resolution_conflict_is_atomic_and_retains_journal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init(tmp_path, capsys)
    manifest = tmp_path / "poly.yaml"
    before = manifest.read_bytes()

    for path in ("first", "second"):
        assert (
            cli.main(
                [
                    "add",
                    "module",
                    "duplicate",
                    "--path",
                    path,
                    "--workspace",
                    str(tmp_path),
                    "--prepare",
                    "--format",
                    "json",
                ]
            )
            == 0
        )
        capsys.readouterr()

    with pytest.raises(SystemExit):
        cli.main(["exec", "--workspace", str(tmp_path)])
    error = capsys.readouterr().err
    assert "conflict" in error
    assert manifest.read_bytes() == before

    plan_path = tmp_path / ".poly" / "state" / "plan.json"
    retained = json.loads(plan_path.read_text(encoding="utf-8"))
    assert retained["prepared"]["state"] == "planned"
    assert retained["prepared"]["command_count"] == 2
    assert retained["resolution"]["status"] == "conflict"
