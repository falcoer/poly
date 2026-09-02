from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


def _run(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        arguments,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and process.returncode != 0:
        raise AssertionError(
            f"command failed ({process.returncode}): {' '.join(arguments)}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    return process


def _git(directory: Path, *arguments: str) -> str:
    return _run(["git", "-C", str(directory), *arguments]).stdout.strip()


def _poly(poly: Path, arguments: list[str], output: Path, name: str) -> str:
    process = _run([str(poly), *arguments])
    (output / f"{name}.stdout.txt").write_text(process.stdout, encoding="utf-8")
    (output / f"{name}.stderr.txt").write_text(process.stderr, encoding="utf-8")
    return process.stdout


def _json_command(poly: Path, arguments: list[str], output: Path, name: str) -> dict[str, Any]:
    value = _poly(poly, [*arguments, "--format", "json"], output, name)
    document = json.loads(value)
    (output / f"{name}.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return document


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_hashes(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for current, directory_names, file_names in os.walk(root):
        directory_names[:] = sorted(
            name for name in directory_names if name not in {".git", ".poly"}
        )
        directory = Path(current)
        for name in sorted(file_names):
            path = directory / name
            relative = path.relative_to(root).as_posix()
            values[relative] = _sha256(path)
    return values


def _snapshot(workspace: Path) -> dict[str, Any]:
    children = {name: workspace / "repos" / name for name in ("alpha", "beta")}
    return {
        "authored": {
            name: _sha256(workspace / name)
            for name in ("poly.yaml", "poly.lock.yaml", ".gitignore")
        },
        "worktree-files": _tree_hashes(workspace),
        "root-index-tree": _git(workspace, "write-tree"),
        "root-status": _git(workspace, "status", "--porcelain=v1"),
        "children": {
            name: {
                "head": _git(path, "rev-parse", "HEAD"),
                "status": _git(path, "status", "--porcelain=v1"),
            }
            for name, path in children.items()
        },
    }


def _decode_xml(element: ET.Element) -> Any:
    kind = element.attrib["type"]
    if kind == "object":
        return {child.attrib["name"]: _decode_xml(child) for child in element}
    if kind == "array":
        return [_decode_xml(child) for child in element]
    if kind == "null":
        return None
    if kind == "boolean":
        return element.text == "true"
    if kind == "number":
        text = element.text or "0"
        return float(text) if "." in text else int(text)
    return element.text or ""


def _decode_yaml(value: str) -> Any:
    return YAML(typ="safe").load(StringIO(value))


def _inventory_ids(document: dict[str, Any]) -> list[str]:
    return sorted(str(node["id"]) for node in document["inventory"]["nodes"])


def _write_action_logs(output: Path, documents: dict[str, dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for report_name, document in documents.items():
        plan = document.get("plan") or {}
        owners = {
            str(action.get("id")): action.get("driver")
            for action in plan.get("planned_actions", [])
            if isinstance(action, dict)
        }
        run = document.get("run") or {}
        for action in run.get("actions", []):
            if not isinstance(action, dict):
                continue
            attempt = action.get("attempt") if isinstance(action.get("attempt"), dict) else {}
            rows.append(
                {
                    "report": report_name,
                    "action-id": action.get("action_id"),
                    "owner": owners.get(str(action.get("action_id"))),
                    "state": action.get("state"),
                    "message": attempt.get("summary"),
                    "stdout": attempt.get("stdout"),
                    "stderr": attempt.get("stderr"),
                    "exit-code": attempt.get("exit_code"),
                }
            )
    (output / "action-logs.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run(poly: Path, fixture: Path, output: Path, platform_name: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    expected = json.loads((fixture / "fixture-commits.json").read_text(encoding="utf-8"))
    workspace = fixture / "workspace"
    if workspace.exists():
        raise AssertionError(f"acceptance workspace already exists: {workspace}")

    version = _run([str(poly), "--version"]).stdout.strip()
    assert version == "poly 0.12.2", version
    root_remote = (fixture / "remotes" / "root.git").resolve()
    bootstrap = _json_command(
        poly,
        ["init", str(root_remote), str(workspace), "--ref", "main"],
        output,
        "01-bootstrap",
    )
    assert bootstrap["kind"] == "bootstrap"
    assert [phase["name"] for phase in bootstrap["phases"]] == [
        "root-bootstrap",
        "recursive-hydration",
    ]
    run_id = str(bootstrap["plan"]["id"])
    assert _git(workspace, "rev-parse", "HEAD") == expected["root"]
    for child in ("alpha", "beta"):
        assert _git(workspace / "repos" / child, "rev-parse", "HEAD") == expected[child]
    assert (workspace / "repos" / "alpha" / "module-a" / "pom.xml").is_file()
    assert (workspace / "repos" / "alpha" / "module-b" / "pom.xml").is_file()

    reports: dict[str, dict[str, Any]] = {"bootstrap": bootstrap}
    recovered: dict[str, str] = {}
    for format_name in ("json", "yaml", "xml"):
        text = _poly(
            poly,
            ["report", run_id, "--workspace", str(workspace), "--format", format_name],
            output,
            f"02-report-{format_name}",
        )
        recovered[format_name] = text
        (output / f"report.{format_name}").write_text(text, encoding="utf-8")
    text_report = _poly(
        poly,
        [
            "report",
            run_id,
            "--workspace",
            str(workspace),
            "--format",
            "text",
            "-vv",
            "--color",
            "never",
        ],
        output,
        "02-report-text",
    )
    (output / "report.txt").write_text(text_report, encoding="utf-8")
    json_report = json.loads(recovered["json"])
    assert _decode_yaml(recovered["yaml"]) == json_report
    assert _decode_xml(ET.fromstring(recovered["xml"])) == json_report
    assert json_report == bootstrap
    planned_ids = [str(action["id"]) for action in json_report["plan"]["planned_actions"]]
    assert all(action_id in text_report for action_id in planned_ids)
    assert str(json_report["run"]["status"]) in text_report
    parity = {
        "structured-equal": True,
        "text-contains-plan-actions": True,
        "text-contains-run-status": True,
        "run-id": run_id,
    }
    (output / "report-parity.json").write_text(
        json.dumps(parity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    drivers = _json_command(poly, ["drivers", "--workspace", str(workspace)], output, "03-drivers")
    installed = next(
        item for item in drivers["drivers"] if item["name"] == "poly.driver.sample-tech"
    )
    assert installed["status"] == "loaded"
    assert str(installed["origin"]).startswith("installed:")

    inspected = _json_command(
        poly, ["inspect", "--workspace", str(workspace)], output, "04-inspect"
    )
    canonical_ids = _inventory_ids(inspected)
    assert canonical_ids == sorted(expected["canonical-node-ids"])
    by_id = {node["id"]: node for node in inspected["inventory"]["nodes"]}
    assert "git/repository" in by_id["alpha"]["natures"]
    assert "git/repository" in by_id["beta"]["natures"]
    assert "maven/aggregator" in by_id["alpha-reactor"]["natures"]
    assert "maven/module" in by_id["alpha-module-a"]["natures"]
    assert "maven/module" in by_id["alpha-module-b"]["natures"]
    assert "sample/project" in by_id["root"]["natures"]

    status = _json_command(
        poly,
        ["status", "--workspace", str(workspace), "--select", "alpha,beta"],
        output,
        "05-status",
    )
    verify = _json_command(
        poly,
        ["verify", "--workspace", str(workspace), "--select", "alpha-reactor"],
        output,
        "06-verify",
    )
    external = _json_command(
        poly,
        ["sample-status", "--workspace", str(workspace), "--select", "root"],
        output,
        "07-external-driver",
    )
    reports.update({"status": status, "verify": verify, "external": external})
    assert _inventory_ids(status) == canonical_ids
    assert _inventory_ids(verify) == canonical_ids
    assert _inventory_ids(external) == canonical_ids
    assert verify["run"]["status"] == "succeeded"
    assert external["run"]["status"] == "succeeded"

    initial_inventory = inspected["inventory"]
    (output / "canonical-inventory-before-rebuild.json").write_text(
        json.dumps(initial_inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.rmtree(workspace / ".poly")
    rebuilt = _json_command(
        poly, ["inspect", "--workspace", str(workspace)], output, "08-rebuild-inspect"
    )
    assert rebuilt["inventory"] == initial_inventory
    assert (workspace / ".poly" / "state" / "inventory.json").is_file()
    (output / "canonical-inventory-final.json").write_text(
        json.dumps(rebuilt["inventory"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    before_hydrate = _snapshot(workspace)
    repeated = _json_command(
        poly, ["hydrate", "--workspace", str(workspace)], output, "09-repeat-hydrate"
    )
    reports["repeat-hydrate"] = repeated
    after_hydrate = _snapshot(workspace)
    assert after_hydrate == before_hydrate
    (output / "idempotence.json").write_text(
        json.dumps(
            {"before": before_hydrate, "after": after_hydrate, "equal": True},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    beta_file = workspace / "repos" / "beta" / "content.txt"
    beta_file.write_text(beta_file.read_text(encoding="utf-8") + "local change\n", encoding="utf-8")
    root_after_child = _git(workspace, "status", "--porcelain=v1")
    beta_status = _git(workspace / "repos" / "beta", "status", "--porcelain=v1")
    assert root_after_child == ""
    assert beta_status
    manifest = workspace / "poly.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + "# composition change\n", encoding="utf-8"
    )
    root_after_composition = _git(workspace, "status", "--porcelain=v1")
    assert "poly.yaml" in root_after_composition
    git_states = {
        "root-after-child-change": root_after_child,
        "root-after-composition-change": root_after_composition,
        "children": {
            name: {
                "head": _git(workspace / "repos" / name, "rev-parse", "HEAD"),
                "status": _git(workspace / "repos" / name, "status", "--porcelain=v1"),
            }
            for name in ("alpha", "beta")
        },
        "root-index-tree": _git(workspace, "write-tree"),
    }
    (output / "git-states.json").write_text(
        json.dumps(git_states, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "fixture-commits.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_action_logs(output, reports)

    environment = {
        "platform": platform_name,
        "system": platform.platform(),
        "python": sys.version,
        "poly": version,
        "git": _run(["git", "--version"]).stdout.strip(),
        "maven": _run(["mvn.cmd" if os.name == "nt" else "mvn", "--version"]).stdout.splitlines()[
            0
        ],
        "run-id": run_id,
    }
    (output / "environment.json").write_text(
        json.dumps(environment, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    root_commit = expected["root"]
    alpha_commit = expected["alpha"]
    beta_commit = expected["beta"]
    node_ids = ", ".join(canonical_ids)
    summary = f"""# Poly 0.12 clean-workstation acceptance — {platform_name}

- Poly: `{version}`
- Bootstrap report id: `{run_id}`
- Root fixture commit: `{root_commit}`
- Alpha locked commit: `{alpha_commit}`
- Beta locked commit: `{beta_commit}`
- Canonical node identifiers: {node_ids}
- External driver: `poly.driver.sample-tech` loaded from an installed wheel
- Maven: multi-module `alpha-reactor` verified successfully
- Report recovery: text, JSON, YAML and XML retained; structured documents are equal
- Generated state: `.poly/` removed and reconstructed with identical canonical inventory
- Repeated hydration: no authored file, worktree, root index, child HEAD or Git status change
- Git isolation: a beta child edit leaves the root clean; a `poly.yaml` edit dirties the root

Result: **PASS**
"""
    (output / "SUMMARY.md").write_text(summary, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poly", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    args = parser.parse_args()
    run(args.poly.resolve(), args.fixture.resolve(), args.output.resolve(), args.platform)


if __name__ == "__main__":
    main()
