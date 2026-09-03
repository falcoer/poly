from __future__ import annotations

import io
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from poly import __version__
from poly.cli import main


class RecordingOutput(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.flushes: list[str] = []

    def flush(self) -> None:
        self.flushes.append(self.getvalue())
        super().flush()


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


def test_cli_reports_installed_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"poly {__version__}\n"
    assert version("poly") == __version__


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
                "verify",
                "--workspace",
                str(tmp_path),
                "--select",
                "maven:.",
                "--plan",
                "--format",
                "yaml",
            ]
        )
        == 0
    )
    planned = capsys.readouterr().out
    assert '"applicable_actions":' in planned
    assert '"ready_action_ids":' in planned


def test_cli_inspect_writes_and_exposes_an_explicit_report_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _workspace(tmp_path)
    report = tmp_path / "reports" / "inspection.json"

    assert (
        main(
            [
                "inspect",
                "--workspace",
                str(tmp_path),
                "--format",
                "json",
                "--output",
                str(report),
                "--color",
                "never",
            ]
        )
        == 0
    )

    terminal = capsys.readouterr().out
    generated = json.loads(report.read_text(encoding="utf-8"))
    assert "✓ SUCCESS  poly inspect" in terminal
    assert "> OUTPUT" in terminal
    assert f"Inspection report: {report}" in terminal
    assert generated["kind"] == "inspection"
    assert generated["outputs"] == [
        {
            "kind": "file",
            "target": str(report),
            "label": "Inspection report",
            "media_type": "application/json",
        }
    ]


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


def test_cli_flushes_heading_and_terminal_action_before_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = RecordingOutput()
    monkeypatch.setattr(sys, "stdout", output)

    assert main(["init", "--workspace", str(tmp_path), "--name", "Streaming"]) == 0

    assert any("INITIALIZING" in value and "SUCCESS" not in value for value in output.flushes)
    assert all("> RUNNING" not in value for value in output.flushes)
    assert "✓ OK" in output.getvalue()
    assert output.getvalue().count("✓ OK") == 1
    assert "✓ SUCCESS  poly init" in output.getvalue()


def test_cli_rejects_unknown_verbs_and_invalid_parameters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _workspace(tmp_path)

    with pytest.raises(SystemExit):
        main(["unknown", "--workspace", str(tmp_path)])
    assert "invalid choice" in capsys.readouterr().err

    with pytest.raises(SystemExit):
        main(
            [
                "verify",
                "--workspace",
                str(tmp_path),
                "--parameter",
                "invalid",
                "--plan",
            ]
        )
    assert "invalid --parameter" in capsys.readouterr().err

    with pytest.raises(SystemExit):
        main(
            [
                "verify",
                "--workspace",
                str(tmp_path),
                "--select",
                "maven:missing",
                "--plan",
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
                "module",
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


def test_drivers_and_natures_are_listed_from_an_empty_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["drivers", "--workspace", str(tmp_path), "--format", "json"]) == 0
    drivers = json.loads(capsys.readouterr().out)
    assert [driver["name"] for driver in drivers["drivers"]] == [
        "poly.constructor",
        "poly.driver.git",
        "poly.driver.maven",
    ]

    assert main(["nature", "list", "--workspace", str(tmp_path), "--format", "json"]) == 0
    natures = json.loads(capsys.readouterr().out)
    assert [nature["name"] for nature in natures["natures"]] == [
        "git/repository",
        "maven/aggregator",
        "maven/module",
        "maven/project",
        "poly/module",
        "poly/repository",
        "poly/workspace",
    ]


def test_contextual_nature_add_remove_supports_dot_and_multiple_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--name", "Natures"]) == 0
    capsys.readouterr()
    assert main(["add", "module", "module", "--workspace", str(tmp_path), "--path", "module"]) == 0
    capsys.readouterr()
    module = tmp_path / "module"
    module.mkdir()
    monkeypatch.chdir(module)

    assert main(["nature", "add", ".", "z/nature", "a/nature"]) == 0
    added = capsys.readouterr().out
    assert "ADDING NATURES TO module" in added
    assert main(["nature", "remove", "a/nature"]) == 0
    capsys.readouterr()

    assert main(["inspect", "--workspace", str(tmp_path), "--format", "json"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    current = next(node for node in inspected["inventory"]["nodes"] if node["id"] == "module")
    assert "z/nature" in current["natures"]
    assert "a/nature" not in current["natures"]


def test_direct_plan_form_remains_side_effect_free(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--name", "Example"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "add",
                "module",
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

    assert direct["request"]["verb"] == "add"

    _workspace(tmp_path / "plain")
    assert main(["status", "--workspace", str(tmp_path / "plain"), "--format", "json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["request"]["verb"] == "status"
    assert status["run"]["status"] == "succeeded"


def test_cli_prepares_accumulates_executes_and_clears_one_current_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--name", "Prepared"]) == 0
    capsys.readouterr()

    for index, node_id in enumerate(("api", "web"), 1):
        assert (
            main(
                [
                    "add",
                    "module",
                    node_id,
                    "--path",
                    f"services/{node_id}",
                    "--workspace",
                    str(tmp_path),
                    "--prepare",
                    "--format",
                    "json",
                ]
            )
            == 0
        )
        prepared = json.loads(capsys.readouterr().out)
        assert prepared["kind"] == "prepared-commands"
        assert prepared["prepared"]["state"] == "planned"
        assert prepared["prepared"]["command_count"] == index
        assert "plan" not in prepared
        assert "workspace_fingerprint" not in prepared["prepared"]

    assert main(["plan", "--workspace", str(tmp_path), "--format", "json"]) == 0
    current = json.loads(capsys.readouterr().out)
    assert current["kind"] == "prepared-commands"
    assert current["prepared"]["command_count"] == 2
    assert [item["verb"] for item in current["prepared"]["commands"]] == ["add", "add"]
    assert "plan" not in current

    assert main(["exec", "--workspace", str(tmp_path), "--format", "json"]) == 0
    executed = json.loads(capsys.readouterr().out)
    assert isinstance(executed["run"]["plan_id"], str)
    assert executed["run"]["status"] == "succeeded"
    manifest = (tmp_path / "poly.yaml").read_text(encoding="utf-8")
    assert "id: api" in manifest
    assert "id: web" in manifest
    assert not (tmp_path / ".poly" / "state" / "plan.json").exists()

    assert main(["plan", "clean", "--workspace", str(tmp_path), "--format", "json"]) == 0
    empty = json.loads(capsys.readouterr().out)
    assert empty["plan"]["status"] == "empty"


def test_prepared_additions_execute_in_command_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--name", "Ordered"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "add",
                "module",
                "z-parent",
                "--path",
                "parent",
                "--workspace",
                str(tmp_path),
                "--prepare",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "add",
                "module",
                "a-child",
                "--path",
                "parent/child",
                "--parent",
                "z-parent",
                "--workspace",
                str(tmp_path),
                "--prepare",
                "--format",
                "json",
            ]
        )
        == 0
    )
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["prepared"]["command_count"] == 2
    assert "plan" not in prepared

    assert main(["exec", "--workspace", str(tmp_path), "--format", "json"]) == 0
    executed = json.loads(capsys.readouterr().out)
    assert executed["run"]["status"] == "succeeded"
    manifest = (tmp_path / "poly.yaml").read_text(encoding="utf-8")
    assert "id: z-parent" in manifest
    assert "id: a-child" in manifest


def test_nature_prepare_is_side_effect_free_and_blocks_immediate_edits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--name", "Natures"]) == 0
    capsys.readouterr()
    before = (tmp_path / "poly.yaml").read_text(encoding="utf-8")

    assert (
        main(
            [
                "nature",
                "add",
                ".",
                "service/example",
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
    assert (tmp_path / "poly.yaml").read_text(encoding="utf-8") == before

    with pytest.raises(SystemExit):
        main(
            [
                "nature",
                "add",
                ".",
                "service/immediate",
                "--workspace",
                str(tmp_path),
            ]
        )
    assert "prepared plan is active" in capsys.readouterr().err
    assert (tmp_path / "poly.yaml").read_text(encoding="utf-8") == before

    assert main(["exec", "--workspace", str(tmp_path), "--format", "json"]) == 0
    capsys.readouterr()
    assert "service/example" in (tmp_path / "poly.yaml").read_text(encoding="utf-8")


def test_root_bootstrap_prepare_fails_without_cloning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "target"

    with pytest.raises(SystemExit):
        main(
            [
                "init",
                "https://example.test/root.git",
                str(target),
                "--prepare",
            ]
        )

    assert "recursive hydration cannot be frozen" in capsys.readouterr().err
    assert not target.exists()
    assert not (tmp_path / ".poly").exists()


def test_root_bootstrap_honors_plan_in_containing_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--name", "Containing"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "add",
                "module",
                "reserved",
                "--path",
                "nested/target",
                "--workspace",
                str(tmp_path),
                "--prepare",
            ]
        )
        == 0
    )
    capsys.readouterr()
    nested = tmp_path / "nested"
    nested.mkdir()
    target = nested / "target"

    with pytest.raises(SystemExit):
        main(["init", "https://example.test/root.git", str(target)])

    assert "prepared plan is active" in capsys.readouterr().err
    assert not target.exists()


def test_root_bootstrap_honors_prepared_init_in_ancestor_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "init",
                "--workspace",
                str(tmp_path),
                "--name",
                "Pending",
                "--prepare",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert not (tmp_path / "poly.yaml").exists()
    nested = tmp_path / "nested"
    nested.mkdir()
    target = nested / "target"

    with pytest.raises(SystemExit):
        main(["init", "https://example.test/root.git", str(target)])

    assert "prepared plan is active" in capsys.readouterr().err
    assert not target.exists()


def test_root_bootstrap_honors_plan_in_existing_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    _workspace(target)
    assert main(["init", "--workspace", str(target), "--name", "Target"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "add",
                "module",
                "reserved",
                "--path",
                "reserved",
                "--workspace",
                str(target),
                "--prepare",
            ]
        )
        == 0
    )
    capsys.readouterr()

    with pytest.raises(SystemExit):
        main(["init", "https://example.test/root.git", str(target)])

    assert "prepared plan is active" in capsys.readouterr().err
    assert (target / ".poly" / "state" / "plan.json").is_file()


def test_cli_resolves_prepared_commands_against_exec_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--name", "Stale"]) == 0
    capsys.readouterr()
    prepared = [
        "add",
        "module",
        "api",
        "--path",
        "api",
        "--workspace",
        str(tmp_path),
        "--prepare",
    ]
    assert main(prepared) == 0
    capsys.readouterr()

    with pytest.raises(SystemExit):
        main(["status", "--workspace", str(tmp_path)])
    assert "prepared plan is active" in capsys.readouterr().err

    manifest = tmp_path / "poly.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert main(["exec", "--workspace", str(tmp_path), "--format", "json"]) == 0
    executed = json.loads(capsys.readouterr().out)
    assert executed["run"]["status"] == "succeeded"
    assert "id: api" in manifest.read_text(encoding="utf-8")
    assert not (tmp_path / ".poly" / "state" / "plan.json").exists()


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
