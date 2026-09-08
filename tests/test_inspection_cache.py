from __future__ import annotations

from pathlib import Path

from poly.application import inspect_workspace
from poly.cli import build_registry


def _pom(workspace: Path, artifact_id: str) -> None:
    (workspace / "pom.xml").write_text(
        f"""<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>example</groupId>
  <artifactId>{artifact_id}</artifactId>
  <version>1.0.0</version>
</project>
""",
        encoding="utf-8",
    )


def test_inspection_cache_reuses_exact_input_and_invalidates_changed_pom(
    tmp_path: Path,
) -> None:
    (tmp_path / ".poly").mkdir()
    _pom(tmp_path, "first")
    registry = build_registry()

    cold = inspect_workspace(registry, tmp_path)
    hit = inspect_workspace(registry, tmp_path)

    assert cold.cache_state == "cold"
    assert hit.cache_state == "hit"
    assert hit.inventory == cold.inventory
    cache = tmp_path / ".poly" / "state" / "inspection" / "inspection-v1.json"
    assert cache.is_file()

    _pom(tmp_path, "second")
    invalidated = inspect_workspace(registry, tmp_path)

    assert invalidated.cache_state == "cold"
    assert invalidated.inventory.nodes[0].metadata["maven.artifactId"] == "second"


def test_inspection_cache_refresh_bypasses_a_valid_entry(tmp_path: Path) -> None:
    (tmp_path / ".poly").mkdir()
    _pom(tmp_path, "application")
    registry = build_registry()

    inspect_workspace(registry, tmp_path)
    forced = inspect_workspace(registry, tmp_path, refresh=True)
    after = inspect_workspace(registry, tmp_path)

    assert forced.cache_state == "refresh"
    assert after.cache_state == "hit"


def test_inspection_cache_is_invalidated_by_remote_mode(tmp_path: Path) -> None:
    (tmp_path / ".poly").mkdir()
    _pom(tmp_path, "application")
    registry = build_registry()

    inspect_workspace(registry, tmp_path)
    remote = inspect_workspace(registry, tmp_path, remote=True)

    assert remote.cache_state == "cold"
