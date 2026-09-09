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
from poly.model import Inventory, Node, PlanningRequest, PlanStatus
from poly.planning import Planner
from poly.runtime import Executor, LocalActionRunner, RunStatus


def registry(monkeypatch: pytest.MonkeyPatch) -> DriverRegistry:
    fixture = Path(__file__).resolve().parents[1] / "examples" / "eclipse-contract"
    monkeypatch.syspath_prepend(str(fixture))
    registration = load_plugin_entrypoint("eclipse_contract:plugin")
    result = DriverRegistry()
    result.register_plugin(registration)
    return result


def test_external_facade_blueprint_plan_and_process_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = registry(monkeypatch)
    facade = loaded.contributions.facade("configure", "eclipse-fixture")
    values = facade.translate(FacadeRequest(tmp_path, {"name": "  Test & Java  "}))
    resolved = loaded.contributions.resolve_blueprint("eclipse-java", values, version="1.0.0")
    assert json.loads(json.dumps(resolved.to_dict()))["parameters"] == {
        "project_name": "Test & Java"
    }
    assert not (tmp_path / ".project").exists()
    inventory = Inventory((Node("java", ".", ("java/project",)), Node("other", "other")))
    request = PlanningRequest(
        "configure", inventory, ("java", "other"), dict(resolved.configuration)
    )
    plan = Planner(loaded.planning_providers()).negotiate(request)
    assert plan.status is PlanStatus.EXECUTABLE
    assert len(plan.actions) == 1
    assert plan.rejected[0].missing == ("nature:java/project",)
    assert not (tmp_path / ".project").exists()
    result = Executor(LocalActionRunner()).execute(
        plan,
        ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / plan.id),
    )
    assert result.status is RunStatus.SUCCEEDED
    assert ElementTree.parse(tmp_path / ".project").findtext("name") == "Test & Java"
    # The fixture fails safely instead of overwriting an existing user file.
    before = (tmp_path / ".project").read_bytes()
    second = Executor(LocalActionRunner()).execute(
        plan,
        ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / "second"),
    )
    assert second.status is RunStatus.FAILED
    assert (tmp_path / ".project").read_bytes() == before
    unrelated = replace(request, parameters={"tool": "other"})
    empty = Planner(loaded.planning_providers()).negotiate(unrelated)
    assert empty.status is PlanStatus.EMPTY
    assert empty.rejected == ()


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
            "eclipse-java", values, version=version
        )


def test_blueprint_checks_dependencies_defaults_choices_and_freezes_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = registry(monkeypatch)
    definition = loaded.contributions.blueprint("eclipse-java")
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
                available_resources=frozenset(("resources/project.xml",)),
            )
    parameter = BlueprintParameter("project_name", "demo", ("demo", "other"))
    defaults = replace(definition, parameters=(parameter,))
    resolved = resolve_definition(
        defaults,
        {},
        version="1.0.0",
        available_contributions=frozenset(("driver:fixture.eclipse",)),
        available_resources=frozenset(("resources/project.xml",)),
    )
    assert resolved.configuration["project.name"] == "demo"
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
