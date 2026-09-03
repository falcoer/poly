from __future__ import annotations

import json
from pathlib import Path

import pytest

import poly.cli as cli
from poly.model import ActionClaim, ActionSpec, Constraint, RejectedCandidate
from poly.persistence import StateStore
from poly.prepared import (
    PreparedPlanError,
    action_document,
    deferred_commands,
    deferred_document,
    plan_from_document,
    rejected_document,
)


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

    retained = StateStore(tmp_path).load_prepared_plan()
    assert retained["prepared"]["state"] == "planned"
    assert retained["prepared"]["command_count"] == 2
    assert retained["resolution"]["status"] == "conflict"


def test_deferred_journal_validates_previous_state_and_payload(tmp_path: Path) -> None:
    first = deferred_document(
        tmp_path,
        "add",
        ("api",),
        False,
        {"z": "last", "a": "first"},
        "poly add module api --prepare",
    )
    second = deferred_document(
        tmp_path,
        "remove",
        ("api",),
        False,
        {},
        "poly remove api --prepare",
        first,
    )
    commands = deferred_commands(second)
    assert [command["verb"] for command in commands] == ["add", "remove"]
    assert commands[0]["parameters"] == {"a": "first", "z": "last"}

    with pytest.raises(PreparedPlanError, match="not a prepared plan"):
        deferred_document(tmp_path, "add", (), True, {}, "poly add --prepare", {"kind": "x"})
    with pytest.raises(PreparedPlanError, match=r"0\.12\.2"):
        deferred_document(
            tmp_path,
            "add",
            (),
            True,
            {},
            "poly add --prepare",
            {"prepared": {"workspace_fingerprint": "legacy"}},
        )
    with pytest.raises(PreparedPlanError, match="deferred prepared-command journal"):
        deferred_commands({"prepared": {"journal_version": 1}})
    with pytest.raises(PreparedPlanError, match="object list"):
        deferred_commands({"prepared": {"journal_version": 2, "commands": ["invalid"]}})


def test_legacy_frozen_plan_decoder_round_trips_full_action_shape() -> None:
    action = ActionSpec(
        "legacy-action",
        "legacy.driver",
        "add",
        "create",
        ("api",),
        requested_node_ids=("api",),
        requires=frozenset((Constraint("source:ready"),)),
        produces=frozenset((Constraint("target:ready"),)),
        claims=frozenset((ActionClaim("write", "node:api"),)),
        command=("legacy-tool", "apply"),
        environment={"MODE": "legacy"},
        changes_structure=True,
        required_capability="process.execute",
    )
    rejected = RejectedCandidate(
        "other.driver", "create", "not selected", ("other",), ("capability",)
    )
    document = {
        "schema": "poly.report/v1",
        "kind": "prepared-plan",
        "rejected_candidates": [rejected_document(rejected)],
        "plan": {
            "id": "legacy-plan",
            "verb": "prepared",
            "selected_node_ids": ["api"],
            "planned_actions": [action_document(action)],
            "diagnostics": [
                {"code": "legacy.warning", "message": "retained", "action_id": action.id}
            ],
            "status": "blocked",
            "initial_constraints": ["source:ready"],
        },
    }

    decoded = plan_from_document(document)
    assert decoded.id == "legacy-plan"
    assert decoded.status.value == "blocked"
    assert decoded.actions == (action,)
    assert decoded.rejected == (rejected,)
    assert decoded.diagnostics[0].action_id == action.id
    assert Constraint("source:ready") in decoded.initial_constraints
