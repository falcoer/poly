from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

FIXED_DATE = "2026-01-01T00:00:00+00:00"
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Poly Acceptance",
    "GIT_AUTHOR_EMAIL": "poly-acceptance@example.invalid",
    "GIT_AUTHOR_DATE": FIXED_DATE,
    "GIT_COMMITTER_NAME": "Poly Acceptance",
    "GIT_COMMITTER_EMAIL": "poly-acceptance@example.invalid",
    "GIT_COMMITTER_DATE": FIXED_DATE,
}


def _run(arguments: list[str], *, cwd: Path | None = None) -> str:
    process = subprocess.run(
        arguments,
        cwd=cwd,
        env=GIT_ENV,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return process.stdout.strip()


def _git(directory: Path, *arguments: str) -> str:
    return _run(["git", "-C", str(directory), *arguments])


def _init_repository(directory: Path) -> None:
    directory.mkdir(parents=True)
    _run(["git", "init", "--quiet", "-b", "main", str(directory)])
    _git(directory, "config", "user.name", "Poly Acceptance")
    _git(directory, "config", "user.email", "poly-acceptance@example.invalid")


def _commit(directory: Path, message: str) -> str:
    _git(directory, "add", ".")
    _git(directory, "commit", "--quiet", "-m", message)
    return _git(directory, "rev-parse", "HEAD")


def _bare_clone(source: Path, target: Path) -> None:
    _run(["git", "clone", "--quiet", "--bare", str(source), str(target)])
    _git(target, "symbolic-ref", "HEAD", "refs/heads/main")


def _pom(artifact_id: str, *, parent: bool = False, modules: tuple[str, ...] = ()) -> str:
    parent_xml = ""
    group = "  <groupId>example.acceptance</groupId>\n"
    version = "  <version>1.0.0</version>\n"
    if parent:
        parent_xml = (
            "  <parent>\n"
            "    <groupId>example.acceptance</groupId>\n"
            "    <artifactId>alpha-reactor</artifactId>\n"
            "    <version>1.0.0</version>\n"
            "  </parent>\n"
        )
        group = ""
        version = ""
    modules_xml = ""
    if modules:
        modules_xml = "  <modules>\n" + "".join(
            f"    <module>{module}</module>\n" for module in modules
        ) + "  </modules>\n"
    packaging = "  <packaging>pom</packaging>\n" if modules else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
        "  <modelVersion>4.0.0</modelVersion>\n"
        f"{parent_xml}{group}  <artifactId>{artifact_id}</artifactId>\n"
        f"{version}{packaging}{modules_xml}</project>\n"
    )


def _child_repository(output: Path, name: str, *, maven: bool = False) -> tuple[str, Path]:
    source = output / f"{name}-source"
    _init_repository(source)
    (source / "content.txt").write_text(f"{name} locked content\n", encoding="utf-8")
    if maven:
        (source / ".gitignore").write_text("target/\n**/target/\n", encoding="utf-8")
        (source / "pom.xml").write_text(
            _pom("alpha-reactor", modules=("module-a", "module-b")), encoding="utf-8"
        )
        for module in ("module-a", "module-b"):
            module_dir = source / module
            module_dir.mkdir()
            (module_dir / "pom.xml").write_text(
                _pom(module, parent=True), encoding="utf-8"
            )
    commit = _commit(source, f"fixture: {name}")
    remote = output / "remotes" / f"{name}.git"
    _bare_clone(source, remote)
    return commit, source


def _manifest(alpha_commit: str, beta_commit: str) -> tuple[str, str, str]:
    del alpha_commit, beta_commit
    manifest = """schema: poly.workspace/v1
workspace:
  id: clean-workstation
  name: Clean workstation acceptance
  root-node: root
nodes:
  - id: root
    kind: workspace
    path: .
  - id: alpha
    parent: root
    kind: repository
    path: repos/alpha
    source:
      driver: git
      url: ../remotes/alpha.git
      ref: main
  - id: alpha-reactor
    parent: alpha
    kind: module
    path: .
    natures:
      - maven/reactor
  - id: alpha-module-a
    parent: alpha-reactor
    kind: module
    path: module-a
  - id: alpha-module-b
    parent: alpha-reactor
    kind: module
    path: module-b
  - id: beta
    parent: root
    kind: repository
    path: repos/beta
    source:
      driver: git
      url: ../remotes/beta.git
      ref: main
"""
    semantic: dict[str, Any] = {
        "schema": "poly.workspace/v1",
        "workspace": {
            "id": "clean-workstation",
            "name": "Clean workstation acceptance",
            "root-node": "root",
        },
        "nodes": sorted(
            [
                {"id": "root", "kind": "workspace", "path": "."},
                {
                    "id": "alpha",
                    "parent": "root",
                    "kind": "repository",
                    "path": "repos/alpha",
                    "source": {"driver": "git", "url": "../remotes/alpha.git", "ref": "main"},
                },
                {
                    "id": "alpha-reactor",
                    "parent": "alpha",
                    "kind": "module",
                    "path": ".",
                    "natures": ["maven/reactor"],
                },
                {
                    "id": "alpha-module-a",
                    "parent": "alpha-reactor",
                    "kind": "module",
                    "path": "module-a",
                },
                {
                    "id": "alpha-module-b",
                    "parent": "alpha-reactor",
                    "kind": "module",
                    "path": "module-b",
                },
                {
                    "id": "beta",
                    "parent": "root",
                    "kind": "repository",
                    "path": "repos/beta",
                    "source": {"driver": "git", "url": "../remotes/beta.git", "ref": "main"},
                },
            ],
            key=lambda item: str(item["id"]),
        ),
    }
    payload = json.dumps(semantic, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    digest = f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"
    ignore = """# BEGIN poly managed
/.poly/
/repos/alpha/
/repos/beta/
# END poly managed
"""
    return manifest, digest, ignore


def _lock(digest: str, alpha_commit: str, beta_commit: str) -> str:
    return f"""schema: poly.workspace-lock/v1
manifest-digest: {digest}
sources:
  alpha:
    driver: git
    url: ../remotes/alpha.git
    requested-ref: main
    resolved:
      commit: {alpha_commit}
      ref-kind: branch
  beta:
    driver: git
    url: ../remotes/beta.git
    requested-ref: main
    resolved:
      commit: {beta_commit}
      ref-kind: branch
"""


def build(output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"fixture output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "remotes").mkdir()
    alpha_commit, alpha_source = _child_repository(output, "alpha", maven=True)
    beta_commit, beta_source = _child_repository(output, "beta")

    root_source = output / "root-source"
    _init_repository(root_source)
    manifest, digest, ignore = _manifest(alpha_commit, beta_commit)
    (root_source / "poly.yaml").write_text(manifest, encoding="utf-8")
    (root_source / "poly.lock.yaml").write_text(
        _lock(digest, alpha_commit, beta_commit), encoding="utf-8"
    )
    (root_source / ".gitignore").write_text(ignore, encoding="utf-8")
    (root_source / "sample.project").write_text("external driver fixture\n", encoding="utf-8")
    root_commit = _commit(root_source, "fixture: clean workstation composition")
    _bare_clone(root_source, output / "remotes" / "root.git")

    commits = {
        "schema": "poly.acceptance-fixture/v1",
        "root": root_commit,
        "alpha": alpha_commit,
        "beta": beta_commit,
        "locked": {"alpha": alpha_commit, "beta": beta_commit},
        "canonical-node-ids": [
            "alpha",
            "alpha-module-a",
            "alpha-module-b",
            "alpha-reactor",
            "beta",
            "root",
        ],
    }
    (output / "fixture-commits.json").write_text(
        json.dumps(commits, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for source in (alpha_source, beta_source, root_source):
        subprocess.run(
            ["python", "-c", "import shutil,sys; shutil.rmtree(sys.argv[1])", str(source)],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.output.resolve())


if __name__ == "__main__":
    main()
