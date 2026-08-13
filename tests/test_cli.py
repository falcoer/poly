from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from poly.cli import main


def _workspace(path: Path) -> None:
    subprocess.run(("git", "init", "--quiet", str(path)), check=True)
    (path / "pom.xml").write_text(
        """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>application</artifactId>
  <version>1.0.0</version>
</project>
"""
    )


def test_cli_inspect_actions_and_plan_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _workspace(tmp_path)

    assert main(["inspect", "--workspace", str(tmp_path), "--format", "json"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert {node["id"] for node in inspected["inventory"]["nodes"]} == {
        "git:.",
        "maven:.",
    }
    assert "verify" in inspected["available_verbs"]

    assert (
        main(
            [
                "actions",
                "verify",
                "--workspace",
                str(tmp_path),
                "--select",
                "maven:.",
                "--format",
                "json",
            ]
        )
        == 0
    )
    actions = json.loads(capsys.readouterr().out)
    assert actions["verbs"][0]["applicable_actions"][0]["id"] == "maven.verify:maven:."

    assert (
        main(
            [
                "plan",
                "verify",
                "--workspace",
                str(tmp_path),
                "--select",
                "maven:.",
                "--format",
                "yaml",
            ]
        )
        == 0
    )
    planned = capsys.readouterr().out
    assert '"applicable_actions":' in planned
    assert '"ready_action_ids":' in planned


def test_cli_executes_git_status_and_reports_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _workspace(tmp_path)

    exit_code = main(
        [
            "run",
            "status",
            "--workspace",
            str(tmp_path),
            "--select",
            "git:.",
            "--format",
            "json",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["run"]["status"] == "succeeded"
    assert report["run"]["actions"][0]["state"] == "succeeded"
    assert report["run"]["actions"][0]["attempt"]["exit_code"] == 0
    assert (tmp_path / ".poly" / "runs" / report["plan"]["id"]).is_dir()


def test_cli_rejects_unknown_verbs_and_invalid_parameters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _workspace(tmp_path)

    with pytest.raises(SystemExit):
        main(["plan", "unknown", "--workspace", str(tmp_path)])
    assert "unknown verb" in capsys.readouterr().err

    with pytest.raises(SystemExit):
        main(
            [
                "plan",
                "verify",
                "--workspace",
                str(tmp_path),
                "--parameter",
                "invalid",
            ]
        )
    assert "invalid --parameter" in capsys.readouterr().err

    with pytest.raises(SystemExit):
        main(
            [
                "plan",
                "verify",
                "--workspace",
                str(tmp_path),
                "--select",
                "maven:missing",
            ]
        )
    assert "unknown node" in capsys.readouterr().err


def test_cli_init_add_persist_and_render_construction_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "init",
                "--workspace",
                str(tmp_path),
                "--name",
                "Example",
                "--format",
                "json",
            ]
        )
        == 0
    )
    initialized = json.loads(capsys.readouterr().out)
    init_id = initialized["plan"]["id"]
    assert initialized["run"]["status"] == "succeeded"

    assert (
        main(
            [
                "add",
                "service",
                "--workspace",
                str(tmp_path),
                "--path",
                "services/service",
                "--nature",
                "maven/module",
                "--format",
                "xml",
            ]
        )
        == 0
    )
    assert "poly-report" in capsys.readouterr().out
    assert (tmp_path / "poly.yaml").is_file()
    assert (tmp_path / "poly.lock.yaml").is_file()

    assert (
        main(
            [
                "report",
                init_id,
                "--workspace",
                str(tmp_path),
                "--format",
                "yaml",
            ]
        )
        == 0
    )
    recovered = capsys.readouterr().out
    assert '"kind": "run"' in recovered
    assert '"status": "succeeded"' in recovered

    assert main(["inspect", "--workspace", str(tmp_path), "--format", "json"]) == 0
    capsys.readouterr()
    assert (tmp_path / ".poly" / "state" / "inventory.json").is_file()

    assert main(["controllers", "--workspace", str(tmp_path), "--format", "json"]) == 0
    controllers = json.loads(capsys.readouterr().out)
    assert controllers["controllers"][0]["name"] == "local"
    assert controllers["controllers"][0]["capabilities"] == [
        "driver.execute",
        "git.materialize",
        "process.execute",
        "workspace.construct",
    ]

    assert main(["drivers", "--workspace", str(tmp_path), "--format", "json"]) == 0
    drivers = json.loads(capsys.readouterr().out)
    assert {driver["name"] for driver in drivers["drivers"]} == {
        "poly.constructor",
        "poly.driver.git",
        "poly.driver.maven",
    }


def test_direct_and_expert_verb_forms_share_the_same_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--name", "Example"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "add",
                "service",
                "--workspace",
                str(tmp_path),
                "--path",
                "services/service",
                "--plan",
                "--format",
                "json",
            ]
        )
        == 0
    )
    direct = json.loads(capsys.readouterr().out)
    assert not (tmp_path / "services" / "service").exists()

    assert (
        main(
            [
                "plan",
                "add",
                "--workspace",
                str(tmp_path),
                "--parameter",
                "poly.node.id=service",
                "--parameter",
                "poly.node.path=services/service",
                "--parameter",
                "poly.node.kind=module",
                "--parameter",
                "poly.node.natures=",
                "--format",
                "json",
            ]
        )
        == 0
    )
    expert = json.loads(capsys.readouterr().out)
    assert direct["plan"] == expert["plan"]

    _workspace(tmp_path / "plain")
    assert main(["status", "--workspace", str(tmp_path / "plain"), "--format", "json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["request"]["verb"] == "status"
    assert status["run"]["status"] == "succeeded"


def test_cli_generates_external_driver_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "driver"
    source = Path(__file__).parents[1]

    assert (
        main(
            [
                "driver",
                "new",
                "sample-tech",
                "--path",
                str(target),
                "--poly-source",
                str(source),
            ]
        )
        == 0
    )

    assert "Created poly-driver-sample-tech" in capsys.readouterr().out
    assert (target / "poly-driver.toml").is_file()
