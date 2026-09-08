"""Measure cold and warm Poly inspection preparation on a synthetic Maven workspace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from poly.application import InspectionSnapshot, inspect_workspace
from poly.cli import build_registry

_SCHEMA = "poly.inspection-benchmark/v1"


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modules",
        type=_positive_integer,
        default=600,
        help="number of Maven child modules to generate (default: 600)",
    )
    parser.add_argument("--output", type=Path, required=True, help="JSON benchmark report path")
    options = parser.parse_args(arguments)

    document = measure(options.modules)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(document, sort_keys=True))
    return 0


def measure(module_count: int) -> dict[str, Any]:
    """Build a disposable fixture and record only inspection preparation timings."""

    with TemporaryDirectory(prefix="poly-inspection-benchmark-") as temporary:
        workspace = Path(temporary)
        _write_workspace(workspace, module_count)
        registry = build_registry()
        cold = inspect_workspace(registry, workspace)
        warm = inspect_workspace(registry, workspace)
    return {
        "schema": _SCHEMA,
        "fixture": {
            "maven_modules": module_count,
            "maven_pom_files": module_count + 1,
        },
        "preparation": {
            "cold": _measurement(cold),
            "warm": _measurement(warm),
            "equivalent": cold.inventory == warm.inventory
            and cold.diagnostics == warm.diagnostics
            and cold.available_verbs == warm.available_verbs,
        },
        "maven_execution": {
            "included": False,
            "elapsed_ms": None,
        },
    }


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _measurement(snapshot: InspectionSnapshot) -> dict[str, int | str]:
    return {
        "cache_state": snapshot.cache_state,
        "elapsed_ms": snapshot.elapsed_ms,
        "nodes": len(snapshot.inventory.nodes),
        "diagnostics": len(snapshot.diagnostics),
    }


def _write_workspace(workspace: Path, module_count: int) -> None:
    (workspace / ".poly").mkdir()
    modules = [f"module-{index:04d}" for index in range(module_count)]
    (workspace / "pom.xml").write_text(_pom("benchmark-reactor", modules=modules), encoding="utf-8")
    for module in modules:
        module_directory = workspace / module
        module_directory.mkdir()
        (module_directory / "pom.xml").write_text(_pom(module), encoding="utf-8")


def _pom(artifact_id: str, *, modules: list[str] | None = None) -> str:
    modules_xml = ""
    packaging_xml = ""
    if modules:
        packaging_xml = "  <packaging>pom</packaging>\n"
        modules_xml = (
            "  <modules>\n"
            + "".join(f"    <module>{module}</module>\n" for module in modules)
            + "  </modules>\n"
        )
    return (
        '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
        "  <modelVersion>4.0.0</modelVersion>\n"
        "  <groupId>example.benchmark</groupId>\n"
        f"  <artifactId>{artifact_id}</artifactId>\n"
        "  <version>1.0.0</version>\n"
        f"{packaging_xml}{modules_xml}"
        "</project>\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
