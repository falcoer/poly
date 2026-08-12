from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from poly.application import inspect_workspace
from poly.cli import build_registry, main
from poly.model import Node, NodeRelation
from poly.workspace import (
    COMPILED_WORKSPACE,
    MANAGED_IGNORE_BEGIN,
    MANAGED_IGNORE_END,
    PROVISIONAL_WORKSPACE_MANIFEST,
    WORKSPACE_LOCK,
    WORKSPACE_LOCK_SCHEMA,
    WORKSPACE_MANIFEST,
    WORKSPACE_SCHEMA,
    WorkspaceError,
    add_manifest_node,
    compile_workspace,
    create_workspace_files,
    load_manifest,
    reconcile_gitignore,
    reconcile_inventory,
    remove_manifest_node,
    validate_manifest_value,
    validate_workspace,
    workspace_id,
)


def _yaml_write(path: Path, value: object) -> None:
    yaml = YAML()
    yaml.default_flow_style = False
    with path.open("w", encoding="utf-8") as stream:
        yaml.dump(value, stream)


def _manifest(*nodes: dict[str, object]) -> dict[str, Any]:
    return {
        "schema": WORKSPACE_SCHEMA,
        "workspace": {
            "id": "quality-control",
            "name": "Quality Control",
            "root-node": "root",
        },
        "nodes": [
            {"id": "root", "kind": "workspace", "path": "."},
            *nodes,
        ],
    }


def _write_workspace(path: Path, manifest: dict[str, Any]) -> None:
    parsed = validate_manifest_value(path, manifest)
    sources: dict[str, object] = {}
    for node in parsed.nodes:
        if node.source is None:
            continue
        source: dict[str, object] = {
            "driver": node.source.driver,
            "url": node.source.url,
            "resolved": {"commit": "a" * 40, "ref-kind": "branch"},
        }
        if node.source.ref is not None:
            source["requested-ref"] = node.source.ref
        sources[node.id] = source
    _yaml_write(path / WORKSPACE_MANIFEST, manifest)
    _yaml_write(
        path / WORKSPACE_LOCK,
        {
            "schema": WORKSPACE_LOCK_SCHEMA,
            "manifest-digest": parsed.digest,
            "sources": sources,
        },
    )


def _git(path: Path, *arguments: str) -> str:
    process = subprocess.run(
        ("git", "-C", str(path), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return process.stdout.strip()


def _repository(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(("git", "init", "-b", "main", str(path)), check=True, capture_output=True)
    _git(path, "config", "user.name", "Poly Test")
    _git(path, "config", "user.email", "poly@example.invalid")
    (path / "tracked.txt").write_text("tracked\n")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "initial")


def _pom(path: Path, artifact: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pom.xml").write_text(
        f"""<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>{artifact}</artifactId>
  <version>1.0.0</version>
</project>
"""
    )


def test_create_compile_and_rebuild_disposable_state(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("target/\n# user rule\n")
    created = create_workspace_files(tmp_path, "example", "Example")

    assert created.manifest.root_node == "root"
    assert created.lock.sources == ()
    assert (tmp_path / WORKSPACE_MANIFEST).read_text().startswith("schema: poly.workspace/v1")
    assert (tmp_path / WORKSPACE_LOCK).is_file()
    assert (tmp_path / COMPILED_WORKSPACE).is_file()
    first_state = (tmp_path / COMPILED_WORKSPACE).read_bytes()
    first_ignore = (tmp_path / ".gitignore").read_bytes()

    compile_workspace(tmp_path)
    assert (tmp_path / COMPILED_WORKSPACE).read_bytes() == first_state
    assert (tmp_path / ".gitignore").read_bytes() == first_ignore

    shutil.rmtree(tmp_path / ".poly")
    rebuilt = compile_workspace(tmp_path)
    assert rebuilt == created
    assert (tmp_path / COMPILED_WORKSPACE).read_bytes() == first_state
    assert "target/\n# user rule" in (tmp_path / ".gitignore").read_text()


def test_manifest_digest_is_semantic_and_order_independent(tmp_path: Path) -> None:
    first = _manifest(
        {"id": "docs", "parent": "root", "kind": "module", "path": "docs"},
        {"id": "app", "parent": "root", "kind": "module", "path": "app"},
    )
    second = deepcopy(first)
    second["nodes"] = list(reversed(second["nodes"]))

    assert (
        validate_manifest_value(tmp_path, first).digest
        == validate_manifest_value(tmp_path, second).digest
    )

    _write_workspace(tmp_path, first)
    text = (tmp_path / WORKSPACE_MANIFEST).read_text()
    (tmp_path / WORKSPACE_MANIFEST).write_text("# composition comment\n" + text)
    assert load_manifest(tmp_path).digest == validate_manifest_value(tmp_path, first).digest


def test_add_and_remove_preserve_comments_and_user_ignore_rules(tmp_path: Path) -> None:
    create_workspace_files(tmp_path, "example", "Example")
    manifest = tmp_path / WORKSPACE_MANIFEST
    manifest.write_text(manifest.read_text().replace("nodes:", "# node list\nnodes:"))
    (tmp_path / ".gitignore").write_text(
        f"dist/\n\n{MANAGED_IGNORE_BEGIN}\n/.poly/\n{MANAGED_IGNORE_END}\n\n*.local\n"
    )

    added = add_manifest_node(
        tmp_path,
        node_id="service-api",
        parent="root",
        kind="repository",
        path="services/api",
    )
    assert added.manifest.get("service-api").workspace_path == "services/api"
    assert "# node list" in manifest.read_text()
    ignore = (tmp_path / ".gitignore").read_text()
    assert ignore.count(MANAGED_IGNORE_BEGIN) == 1
    assert "/services/api/" in ignore
    assert "dist/" in ignore and "*.local" in ignore

    add_manifest_node(
        tmp_path,
        node_id="api-module",
        parent="service-api",
        kind="module",
        path=".",
        natures=("maven/reactor",),
    )
    with pytest.raises(WorkspaceError, match="still owns children"):
        remove_manifest_node(tmp_path, "service-api")
    remove_manifest_node(tmp_path, "api-module")
    removed = remove_manifest_node(tmp_path, "service-api")
    assert {node.id for node in removed.manifest.nodes} == {"root"}
    assert "/services/api/" not in (tmp_path / ".gitignore").read_text()
    assert "# node list" in manifest.read_text()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"unknown": True}), "unknown fields"),
        (
            lambda value: value["nodes"].append(
                {"id": "root", "parent": "root", "kind": "module", "path": "dup"}
            ),
            "duplicate node identifier",
        ),
        (
            lambda value: value["nodes"].extend(
                [
                    {"id": "a", "parent": "b", "kind": "module", "path": "a"},
                    {"id": "b", "parent": "a", "kind": "module", "path": "b"},
                ]
            ),
            "parent cycle",
        ),
        (
            lambda value: value["nodes"].append(
                {"id": "escape", "parent": "root", "kind": "module", "path": "../escape"}
            ),
            "safe relative path",
        ),
        (
            lambda value: value["nodes"].extend(
                [
                    {"id": "first", "parent": "root", "kind": "module", "path": "Apps"},
                    {"id": "second", "parent": "root", "kind": "module", "path": "apps"},
                ]
            ),
            "case-insensitive",
        ),
        (
            lambda value: value["nodes"].append(
                {
                    "id": "repo",
                    "parent": "root",
                    "kind": "repository",
                    "path": "repo",
                    "source": {
                        "driver": "git",
                        "url": "https://user:secret@example.invalid/repo.git",
                    },
                }
            ),
            "embedded credentials",
        ),
    ],
)
def test_manifest_rejects_unsafe_structures(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    value = _manifest()
    mutate(value)
    with pytest.raises(WorkspaceError, match=message):
        validate_manifest_value(tmp_path, value)


def test_manifest_rejects_symlink_escape_and_invalid_shapes(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    try:
        (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("the platform does not permit test symlinks")
    value = _manifest({"id": "escaped", "parent": "root", "kind": "module", "path": "linked/data"})
    with pytest.raises(WorkspaceError, match="escapes the workspace"):
        validate_manifest_value(tmp_path, value)

    malformed = _manifest()
    malformed["nodes"] = []
    with pytest.raises(WorkspaceError, match="non-empty"):
        validate_manifest_value(tmp_path, malformed)
    with pytest.raises(WorkspaceError, match="stable identifier"):
        validate_manifest_value(
            tmp_path,
            {
                **_manifest(),
                "workspace": {"id": "bad id", "root-node": "root"},
            },
        )


def test_lock_rejects_stale_missing_inconsistent_and_nonimmutable_entries(tmp_path: Path) -> None:
    manifest = _manifest(
        {
            "id": "repo",
            "parent": "root",
            "kind": "repository",
            "path": "repo",
            "source": {"driver": "git", "url": "https://EXAMPLE.invalid/repo.git", "ref": "main"},
        }
    )
    _write_workspace(tmp_path, manifest)
    assert validate_workspace(tmp_path).lock.sources[0].url == "https://example.invalid/repo.git"

    lock_path = tmp_path / WORKSPACE_LOCK
    lock = YAML().load(lock_path.read_text())
    lock["manifest-digest"] = "sha256:stale"
    _yaml_write(lock_path, lock)
    with pytest.raises(WorkspaceError, match="lock is stale"):
        validate_workspace(tmp_path)

    _write_workspace(tmp_path, manifest)
    lock = YAML().load(lock_path.read_text())
    lock["sources"] = {}
    _yaml_write(lock_path, lock)
    with pytest.raises(WorkspaceError, match="sources mismatch"):
        validate_workspace(tmp_path)

    _write_workspace(tmp_path, manifest)
    lock = YAML().load(lock_path.read_text())
    lock["sources"]["repo"]["url"] = "https://example.invalid/other.git"
    _yaml_write(lock_path, lock)
    with pytest.raises(WorkspaceError, match="inconsistent"):
        validate_workspace(tmp_path)

    _write_workspace(tmp_path, manifest)
    lock = YAML().load(lock_path.read_text())
    lock["sources"]["repo"]["resolved"]["commit"] = "abc123"
    _yaml_write(lock_path, lock)
    with pytest.raises(WorkspaceError, match="immutable full Git commit"):
        validate_workspace(tmp_path)


def test_gitignore_rejects_malformed_markers_before_changes(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(f"{MANAGED_IGNORE_BEGIN}\n/.poly/\n")
    before = (tmp_path / ".gitignore").read_bytes()
    with pytest.raises(WorkspaceError, match="malformed"):
        create_workspace_files(tmp_path, "example", "Example")
    assert (tmp_path / ".gitignore").read_bytes() == before
    assert not (tmp_path / WORKSPACE_MANIFEST).exists()

    (tmp_path / PROVISIONAL_WORKSPACE_MANIFEST).parent.mkdir(parents=True)
    (tmp_path / PROVISIONAL_WORKSPACE_MANIFEST).write_text("{}")
    (tmp_path / ".gitignore").write_text("")
    with pytest.raises(WorkspaceError, match="provisional"):
        create_workspace_files(tmp_path, "example", "Example")


def test_declared_nodes_receive_git_and_maven_observations(tmp_path: Path) -> None:
    _repository(tmp_path)
    service = tmp_path / "services" / "api"
    _repository(service)
    _pom(service, "api")
    undeclared = tmp_path / "tools" / "local"
    _repository(undeclared)
    manifest = _manifest(
        {"id": "api-repo", "parent": "root", "kind": "repository", "path": "services/api"},
        {
            "id": "api-module",
            "parent": "api-repo",
            "kind": "module",
            "path": ".",
            "natures": ["maven/reactor"],
        },
    )
    _write_workspace(tmp_path, manifest)

    snapshot = inspect_workspace(build_registry(), tmp_path)
    nodes = {node.id: node for node in snapshot.inventory.nodes}

    assert {"root", "api-repo", "api-module", "git:tools/local"}.issubset(nodes)
    assert "git/repository" in nodes["api-repo"].natures
    assert nodes["api-repo"].metadata["poly.state"] == "declared-observed"
    assert "maven/project" in nodes["api-module"].natures
    assert nodes["api-module"].metadata["maven.artifactId"] == "api"
    assert nodes["git:tools/local"].metadata["poly.state"] == "observed-only"
    assert all(node.id != "git:services/api" for node in nodes.values())
    assert all(node.id != "maven:services/api" for node in nodes.values())


def test_inventory_relation_ids_are_rewritten_to_canonical_ids(tmp_path: Path) -> None:
    manifest = _manifest(
        {"id": "parent", "parent": "root", "kind": "repository", "path": "parent"},
        {"id": "child", "parent": "parent", "kind": "repository", "path": "child"},
    )
    _write_workspace(tmp_path, manifest)
    compiled = validate_workspace(tmp_path)
    observed = (
        Node("git:parent", "parent", ("git/repository",)),
        Node(
            "git:parent/child",
            "parent/child",
            ("git/repository",),
            relations=(NodeRelation("git/nested-under", "git:parent"),),
        ),
    )
    inventory = reconcile_inventory(compiled, observed)
    assert NodeRelation("git/nested-under", "parent") in inventory.get("child").relations


def test_cli_rebuild_keeps_root_git_status_limited_to_authored_composition(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _repository(tmp_path)
    assert main(["init", "--workspace", str(tmp_path), "--name", "Demo"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "add",
                "api",
                "--workspace",
                str(tmp_path),
                "--kind",
                "repository",
                "--path",
                "services/api",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "add",
                "web",
                "--workspace",
                str(tmp_path),
                "--kind",
                "repository",
                "--path",
                "apps/web",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "add",
                "api-module",
                "--workspace",
                str(tmp_path),
                "--parent",
                "api",
                "--path",
                ".",
                "--nature",
                "maven/reactor",
            ]
        )
        == 0
    )
    capsys.readouterr()
    child = tmp_path / "services" / "api"
    _repository(child)
    _pom(child, "api")
    _repository(tmp_path / "apps" / "web")
    (child / "local-change.txt").write_text("child only\n")

    status = _git(tmp_path, "status", "--short")
    assert "services/api" not in status
    assert "apps/web" not in status
    assert "poly.yaml" in status
    assert "poly.lock.yaml" in status
    assert ".gitignore" in status
    assert ".poly" not in status

    assert main(["inspect", "--workspace", str(tmp_path), "--format", "json"]) == 0
    first = json.loads(capsys.readouterr().out)["inventory"]
    shutil.rmtree(tmp_path / ".poly")
    assert main(["inspect", "--workspace", str(tmp_path), "--format", "json"]) == 0
    second = json.loads(capsys.readouterr().out)["inventory"]
    assert second == first
    assert (tmp_path / ".poly" / "state" / "inventory.json").is_file()


def test_public_helpers_report_invalid_values(tmp_path: Path) -> None:
    assert workspace_id("My New Workspace") == "my-new-workspace"
    create_workspace_files(tmp_path, "one", "One")
    with pytest.raises(WorkspaceError, match="authored files already exist"):
        create_workspace_files(tmp_path, "two", "Two")
    with pytest.raises(WorkspaceError, match="root node cannot"):
        remove_manifest_node(tmp_path, "root")
    reconcile_gitignore(tmp_path, validate_workspace(tmp_path).manifest)
