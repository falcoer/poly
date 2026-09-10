from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest

from poly.driver import (
    BlueprintDefinition,
    BlueprintParameter,
    DriverRegistry,
    ExecutionContext,
    ExtensionProtocolError,
    FacadeRequest,
    load_plugin_entrypoint,
)
from poly.model import PlanStatus
from poly.runtime import Executor, LocalActionRunner, RunStatus


def registry(monkeypatch: pytest.MonkeyPatch) -> DriverRegistry:
    fixture = Path(__file__).resolve().parents[1] / "examples" / "eclipse-contract"
    monkeypatch.syspath_prepend(str(fixture))
    registration = load_plugin_entrypoint("eclipse_contract:plugin")
    result = DriverRegistry()
    result.register_plugin(registration)
    return result


def test_external_facade_blueprint_plan_and_hydration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from poly.application import inspect_workspace, prepare_planning
    from poly.construction import constructor_driver
    from poly.hydration import hydration_driver
    from poly.workspace import create_workspace_files

    loaded = registry(monkeypatch)
    loaded.register(constructor_driver())
    loaded.register(hydration_driver(loaded))
    create_workspace_files(tmp_path, "demo", "Demo")
    resolved = loaded.contributions.resolve_blueprint(
        "eclipse-workspace", {"project_name": "Test & Java"}, version="1.0.0"
    )
    assert json.loads(json.dumps(resolved.to_dict()))["parameters"] == {
        "project_name": "Test & Java"
    }
    (tmp_path / "eclipse.yaml").write_text('name: "Test & Java"', encoding="utf-8")
    facade = loaded.contributions.facade("add", "eclipse-configuration")
    parameters = facade.translate(
        FacadeRequest(tmp_path, {"node_id": "ide", "configuration_file": "eclipse.yaml"})
    )
    inspection = inspect_workspace(loaded, tmp_path, declared_only=True)
    add = prepare_planning(loaded, inspection, "add", (), parameters).plan
    runner = LocalActionRunner(registry=loaded)
    result = Executor(runner).execute(add, ExecutionContext(tmp_path, tmp_path / ".poly/runs/add"))
    assert result.status is RunStatus.SUCCEEDED
    inspection = inspect_workspace(loaded, tmp_path, declared_only=True)
    plan = prepare_planning(loaded, inspection, "hydrate", ("root", "ide")).plan
    assert plan.status is PlanStatus.EXECUTABLE
    output = tmp_path / ".poly/projections/ide/request.xml"
    assert not output.exists()
    result = Executor(runner).execute(
        plan, ExecutionContext(tmp_path, tmp_path / ".poly/runs/first")
    )
    assert result.status is RunStatus.SUCCEEDED
    assert ElementTree.parse(output).getroot().get("name") == "Test & Java"
    before = output.stat().st_mtime_ns
    second = Executor(runner).execute(
        plan, ExecutionContext(tmp_path, tmp_path / ".poly/runs/second")
    )
    assert second.status is RunStatus.SUCCEEDED
    assert output.stat().st_mtime_ns == before
    output.write_text("manual edit", encoding="utf-8")
    third = Executor(runner).execute(
        plan, ExecutionContext(tmp_path, tmp_path / ".poly/runs/third")
    )
    assert third.status is RunStatus.FAILED
    assert output.read_text(encoding="utf-8") == "manual edit"


@pytest.mark.parametrize(
    ("values", "version", "message"),
    [
        ({}, "1.0.0", "missing blueprint parameter"),
        ({"unexpected": "x"}, "1.0.0", "unknown blueprint parameters"),
        ({"project_name": "x"}, "2.0.0", "version mismatch"),
    ],
)
def test_blueprint_rejects_invalid_inputs(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, str],
    version: str,
    message: str,
) -> None:
    with pytest.raises(ExtensionProtocolError, match=message):
        registry(monkeypatch).contributions.resolve_blueprint(
            "eclipse-workspace", values, version=version
        )


def test_blueprint_checks_dependencies_defaults_choices_and_freezes_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = registry(monkeypatch)
    definition = loaded.contributions.blueprint("eclipse-workspace")
    assert isinstance(definition, BlueprintDefinition)
    from poly.driver.blueprint import resolve_definition

    for modified, message in [
        (
            replace(definition, required_contributions=("driver:missing",)),
            "missing blueprint contributions",
        ),
        (replace(definition, resources=("missing.xml",)), "missing blueprint resources"),
    ]:
        with pytest.raises(ExtensionProtocolError, match=message):
            resolve_definition(
                modified,
                {"project_name": "x"},
                version="1.0.0",
                available_contributions=frozenset(("driver:fixture.eclipse",)),
                available_resources=frozenset(("resources/request.xml",)),
            )
    parameter = BlueprintParameter("project_name", "demo", ("demo", "other"))
    defaults = replace(definition, parameters=(parameter,))
    resolved = resolve_definition(
        defaults,
        {},
        version="1.0.0",
        available_contributions=frozenset(("driver:fixture.eclipse",)),
        available_resources=frozenset(("resources/request.xml",)),
    )
    assert resolved.configuration["name"] == "demo"
    with pytest.raises(ExtensionProtocolError, match="invalid blueprint parameter"):
        parameter.validate("invalid")
    values = {"key": "before"}
    frozen = BlueprintDefinition("frozen", "test", "1", configuration=values)
    values["key"] = "after"
    assert frozen.configuration["key"] == "before"


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"version": "bad version"},
        {"parameters": (BlueprintParameter("x"), BlueprintParameter("x"))},
        {"bindings": {"key": "absent"}},
        {"configuration": {"key": "x"}, "bindings": {"key": "name"}},
    ],
)
def test_invalid_definitions_fail_before_registration(changes: dict[str, Any]) -> None:
    definition = BlueprintDefinition("test", "Test", "1", parameters=(BlueprintParameter("name"),))
    with pytest.raises(ExtensionProtocolError):
        replace(definition, **changes)
