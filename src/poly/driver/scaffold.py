"""Generate standalone repositories using Poly's packaged driver template."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

DEFAULT_POLY_DEPENDENCY = "poly>=0.12.0,<0.13"
_TECHNOLOGY = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


class DriverScaffoldError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DriverScaffoldResult:
    target: Path
    distribution_name: str
    package_name: str
    driver_name: str
    files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DriverScaffold:
    """Compatibility-oriented object API for repository generators."""

    def create(
        self,
        technology: str,
        destination: Path,
        *,
        poly_dependency: str = DEFAULT_POLY_DEPENDENCY,
    ) -> tuple[Path, ...]:
        if poly_dependency == DEFAULT_POLY_DEPENDENCY:
            result = scaffold_driver(technology, destination)
        else:
            result = _scaffold(technology, destination, poly_dependency)
        return tuple(result.target / relative for relative in result.files)


def scaffold_driver(
    technology: str,
    target: Path,
    *,
    poly_source: Path | None = None,
) -> DriverScaffoldResult:
    """Create a complete Python driver repository without executing its code."""

    dependency = DEFAULT_POLY_DEPENDENCY
    if poly_source is not None:
        source = poly_source.resolve()
        if not (source / "pyproject.toml").is_file():
            raise DriverScaffoldError(f"Poly source is not a Python project: {source}")
        uv_source = (
            "[tool.uv.sources]\n"
            f"poly = {{ path = {json.dumps(source.as_posix())}, editable = true }}"
        )
        return _scaffold(technology, target, dependency, uv_source)
    return _scaffold(technology, target, dependency)


def _scaffold(
    technology: str, target: Path, dependency: str, uv_source: str = ""
) -> DriverScaffoldResult:
    slug = technology.strip()
    if not _TECHNOLOGY.fullmatch(slug):
        raise DriverScaffoldError("technology must be lowercase kebab-case and start with a letter")
    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        raise DriverScaffoldError(f"destination is not empty: {target}")

    distribution_name = f"poly-driver-{slug}"
    package_name = f"poly_driver_{slug.replace('-', '_')}"
    driver_name = f"poly.driver.{slug}"
    if not dependency.strip():
        raise DriverScaffoldError("Poly dependency must not be empty")

    replacements = {
        "__TECHNOLOGY__": slug,
        "__DIST_NAME__": distribution_name,
        "__PACKAGE_NAME__": package_name,
        "__DRIVER_NAME__": driver_name,
        "__POLY_DEPENDENCY__": dependency,
        "__UV_SOURCE__": uv_source,
    }
    template_root = files("poly.driver.templates.python")
    outputs = {
        ".github/workflows/ci.yml": "github-ci.yml.tmpl",
        ".gitignore": "gitignore.tmpl",
        "README.md": "README.md.tmpl",
        "poly-driver.toml": "poly-driver.toml.tmpl",
        "pyproject.toml": "pyproject.toml.tmpl",
        f"src/{package_name}/__init__.py": "package-init.py.tmpl",
        f"src/{package_name}/driver.py": "driver.py.tmpl",
        "tests/fixtures/workspace/sample.project": None,
        "tests/test_driver.py": "test-driver.py.tmpl",
    }
    written: list[str] = []
    for relative, template_name in sorted(outputs.items()):
        output = target / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "sample\n"
            if template_name is None
            else template_root.joinpath(template_name).read_text(encoding="utf-8")
        )
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
        output.write_text(content, encoding="utf-8")
        written.append(relative)
    return DriverScaffoldResult(
        target,
        distribution_name,
        package_name,
        driver_name,
        tuple(written),
    )
