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
