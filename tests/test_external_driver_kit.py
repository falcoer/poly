from __future__ import annotations

import sys
from importlib.metadata import EntryPoint
from itertools import permutations
from pathlib import Path

import pytest

from poly.driver import (
    DriverDiscoveryError,
    DriverRegistry,
    ExternalDriverSpec,
    discover_external_drivers,
    load_external_driver,
)
from poly.driver.cli import main as driver_test_main
from poly.driver.scaffold import DriverScaffoldError, scaffold_driver


def _driver_module(path: Path) -> None:
    path.write_text(
        """from dataclasses import dataclass
from poly.driver import DRIVER_API_VERSION, DriverCapability, DriverManifest, DriverRegistration
from poly.model import DriverProposal, PlanningRequest

@dataclass(frozen=True)
class Planner:
    name: str
    verbs: frozenset[str]
    def propose(self, request: PlanningRequest) -> DriverProposal:
        return DriverProposal(self.name)

def registration(name: str, verb: str, api: str = DRIVER_API_VERSION) -> DriverRegistration:
    return DriverRegistration(
        DriverManifest(name, "1.2.3", api, frozenset((DriverCapability.PLAN,))),
        planners=(Planner(name, frozenset((verb,))),),
    )

def alpha(): return registration("driver.alpha", "alpha-run")
def bravo(): return registration("driver.bravo", "bravo-run")
def duplicate_alpha(): return registration("driver.alpha", "other-run")
def collide_alpha(): return registration("driver.alpha-collision", "shared-run")
def collide_bravo(): return registration("driver.bravo-collision", "shared-run")
def incompatible(): return registration("driver.future", "future-run", "2.0")
""",
        encoding="utf-8",
    )


def test_scaffold_generates_complete_external_repository(tmp_path: Path) -> None:
    target = tmp_path / "driver"
    source = Path(__file__).parents[1]

    result = scaffold_driver("sample-tech", target, poly_source=source)

    assert result.driver_name == "poly.driver.sample-tech"
    assert result.package_name == "poly_driver_sample_tech"
    assert result.files == tuple(
        sorted(
            (
                ".github/workflows/ci.yml",
                ".gitignore",
                "README.md",
                "poly-driver.toml",
                "pyproject.toml",
                "src/poly_driver_sample_tech/__init__.py",
                "src/poly_driver_sample_tech/driver.py",
                "tests/fixtures/workspace/sample.project",
                "tests/test_driver.py",
            )
        )
    )
    all_content = "\n".join(
        path.read_text(encoding="utf-8") for path in target.rglob("*") if path.is_file()
    )
    assert "__DRIVER_NAME__" not in all_content
    assert '"poly>=0.12.0,<0.13"' in all_content
    assert f'poly = {{ path = "{source.resolve().as_posix()}", editable = true }}' in all_content

    with pytest.raises(DriverScaffoldError, match="not empty"):
        scaffold_driver("another", target)
    with pytest.raises(DriverScaffoldError, match="kebab-case"):
        scaffold_driver("Not Valid", tmp_path / "invalid")


def test_generated_driver_loads_and_validates_through_public_convention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "driver"
    scaffold_driver("sample-tech", target, poly_source=Path(__file__).parents[1])
    monkeypatch.syspath_prepend(str(target / "src"))

    spec = ExternalDriverSpec.from_file(target / "poly-driver.toml")
    registration = load_external_driver(spec)

    assert registration.manifest.name == "poly.driver.sample-tech"
    assert driver_test_main(["validate", str(target / "poly-driver.toml")]) == 0
    assert '"api_version": "1.1"' in capsys.readouterr().out
    assert (
        driver_test_main(
            [
                "inspect",
                "poly_driver_sample_tech:driver",
                "--workspace",
                str(target / "tests/fixtures/workspace"),
            ]
        )
        == 0
    )
    assert '"nodes": [' in capsys.readouterr().out
    assert (
        driver_test_main(
            [
                "determinism",
                "poly_driver_sample_tech:driver",
                "--workspace",
                str(target / "tests/fixtures/workspace"),
                "--verb",
                "sample-status",
            ]
        )
        == 0
    )
    sys.modules.pop("poly_driver_sample_tech", None)
    sys.modules.pop("poly_driver_sample_tech.driver", None)


def test_external_driver_spec_rejects_malformed_or_mismatched_drivers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid = tmp_path / "invalid.toml"
    invalid.write_text('[driver]\nname = "broken"\nentrypoint = "missing"\n')
    with pytest.raises(DriverDiscoveryError, match="entrypoint"):
        ExternalDriverSpec.from_file(invalid)

    package = tmp_path / "mismatch.py"
    package.write_text(
        "from poly.drivers.git import git_driver\ndef driver():\n    return git_driver()\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    spec = ExternalDriverSpec("expected.driver", "mismatch:driver")
    with pytest.raises(DriverDiscoveryError, match="does not match"):
        load_external_driver(spec)

    with pytest.raises(DriverDiscoveryError, match="unsupported"):
        ExternalDriverSpec("driver", "mismatch:driver", "2")


def test_installed_entry_points_are_isolated_and_rejected_before_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "entry_driver.py"
    module.write_text(
        "from poly.drivers.git import git_driver\n"
        "def valid(): return git_driver()\n"
        "def invalid(): return object()\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    candidates = (
        EntryPoint("valid", "entry_driver:valid", "poly.drivers"),
        EntryPoint("invalid", "entry_driver:invalid", "poly.drivers"),
    )

    registry = DriverRegistry()
    result = discover_external_drivers(registry, candidates)

    assert result.loaded == ("poly.driver.git",)
    assert result.rejected[0].entry_point == "invalid"
    assert "DriverRegistration" in result.rejected[0].message
    with pytest.raises(DriverDiscoveryError, match="external driver loading failed"):
        result.require_success()


def test_discovery_is_stable_across_entry_point_enumeration_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _driver_module(tmp_path / "ordered_drivers.py")
    monkeypatch.syspath_prepend(str(tmp_path))
    candidates = (
        EntryPoint("bravo", "ordered_drivers:bravo", "poly.drivers"),
        EntryPoint("alpha", "ordered_drivers:alpha", "poly.drivers"),
    )

    inventories = []
    for ordering in permutations(candidates):
        registry = DriverRegistry()
        result = discover_external_drivers(registry, ordering)
        inventories.append(registry.inventory())
        assert result.loaded == ("driver.alpha", "driver.bravo")

    assert inventories[0] == inventories[1]


def test_duplicate_identities_and_verb_collisions_reject_every_ambiguous_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _driver_module(tmp_path / "rejected_drivers.py")
    monkeypatch.syspath_prepend(str(tmp_path))
    duplicate_candidates = (
        EntryPoint("alpha", "rejected_drivers:alpha", "poly.drivers"),
        EntryPoint("duplicate", "rejected_drivers:duplicate_alpha", "poly.drivers"),
    )
    collision_candidates = (
        EntryPoint("alpha", "rejected_drivers:collide_alpha", "poly.drivers"),
        EntryPoint("bravo", "rejected_drivers:collide_bravo", "poly.drivers"),
    )

    for candidates, message in (
        (duplicate_candidates, "duplicate installed driver identity"),
        (collision_candidates, "verb collision"),
    ):
        registry = DriverRegistry()
        result = discover_external_drivers(registry, reversed(candidates))
        assert result.loaded == ()
        assert len(result.rejected) == 2
        assert all(message in diagnostic.message for diagnostic in result.rejected)
        assert all(item.status == "rejected" for item in registry.inventory())


def test_incompatible_protocol_and_import_error_are_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _driver_module(tmp_path / "isolated_drivers.py")
    monkeypatch.syspath_prepend(str(tmp_path))
    candidates = (
        EntryPoint("valid", "isolated_drivers:alpha", "poly.drivers"),
        EntryPoint("future", "isolated_drivers:incompatible", "poly.drivers"),
        EntryPoint("missing", "does_not_exist:driver", "poly.drivers"),
    )

    registry = DriverRegistry()
    result = discover_external_drivers(registry, candidates)

    assert result.loaded == ("driver.alpha",)
    assert {item.identity for item in registry.inventory() if item.status == "rejected"} == {
        "driver.future",
        "missing",
    }
    future = next(item for item in registry.inventory() if item.identity == "driver.future")
    assert future.api_version == "2.0"
    assert future.version == "1.2.3"
    assert future.verbs == ("future-run",)
    messages = " ".join(item.diagnostic or "" for item in registry.inventory())
    assert "requires API 2.0" in messages
    assert "ModuleNotFoundError" in messages
