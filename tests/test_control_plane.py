from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from poly.control_plane import (
    Controller,
    ControllerDescriptor,
    ControlPlane,
    ControlPlaneActionRunner,
    ControlPlaneError,
    LocalController,
    RemoteController,
)
from poly.driver import ExecutionContext
from poly.model import ActionSpec, JsonValue
from poly.runtime import ActionAttempt


@dataclass
class StubRunner:
    calls: list[str]

    def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
        self.calls.append(action.id)
        return ActionAttempt(True, "local")


def _action(capability: str = "process.execute") -> ActionSpec:
    return ActionSpec(
        "action",
        "fixture",
        "verify",
        "fixture/verify",
        (),
        required_capability=capability,
    )


def test_controller_descriptors_round_trip_and_validate() -> None:
    descriptor = ControllerDescriptor(
        "linux-local", "linux", frozenset(("process.execute",)), "http://controller"
    )

    assert ControllerDescriptor.from_dict(descriptor.to_dict()) == descriptor

    with pytest.raises(ControlPlaneError, match="capabilities"):
        ControllerDescriptor("empty", "linux", frozenset())
    with pytest.raises(ControlPlaneError, match="invalid controller descriptor"):
        ControllerDescriptor.from_dict(
            {"name": "bad", "platform": "linux", "capabilities": "process.execute"}
        )


def test_control_plane_negotiates_capabilities_and_requested_controller(tmp_path: Path) -> None:
    first_runner = StubRunner([])
    second_runner = StubRunner([])
    first = LocalController(
        ControllerDescriptor("a-controller", "linux", frozenset(("process.execute",))),
        first_runner,
    )
    second = LocalController(
        ControllerDescriptor("b-controller", "windows", frozenset(("process.execute",))),
        second_runner,
    )
    plane = ControlPlane((second, first))
    context = ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / "run")

    assert isinstance(first, Controller)
    assert plane.descriptors() == (first.descriptor, second.descriptor)
    assert plane.run(_action(), context).success
    assert first_runner.calls == ["action"]
    assert plane.run(_action(), context, "b-controller").success
    assert second_runner.calls == ["action"]
    with pytest.raises(ControlPlaneError, match="no controller provides"):
        plane.select("workspace.construct")
    with pytest.raises(ControlPlaneError, match="no controller provides"):
        plane.select("process.execute", "missing")


def test_control_plane_action_runner_converts_negotiation_errors(tmp_path: Path) -> None:
    plane = ControlPlane(
        (
            LocalController(
                ControllerDescriptor("local", "linux", frozenset(("process.execute",))),
                StubRunner([]),
            ),
        )
    )
    context = ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / "run")

    result = ControlPlaneActionRunner(plane).run(_action("workspace.construct"), context)

    assert not result.success
    assert "no controller" in result.summary


def test_remote_controller_uses_versioned_request_and_response_contract(
    tmp_path: Path,
) -> None:
    @dataclass
    class Transport:
        request: dict[str, JsonValue] | None = None

        def invoke(self, request: dict[str, JsonValue]) -> dict[str, JsonValue]:
            self.request = request
            return {
                "schema": "poly.controller.response/v1",
                "id": request["id"],
                "success": True,
                "summary": "remote",
                "exit_code": 0,
                "stdout": "done",
                "stderr": "",
                "details": {"host": "remote"},
                "value": {"value": 82.4, "label": "coverage"},
                "outputs": [
                    {
                        "kind": "url",
                        "target": "https://example.test/report",
                        "label": "report",
                        "media_type": "text/html",
                    }
                ],
            }

    transport = Transport()
    descriptor = ControllerDescriptor(
        "remote", "windows", frozenset(("process.execute",)), "https://controller"
    )
    controller = RemoteController(descriptor, transport)
    context = ExecutionContext(tmp_path, tmp_path / ".poly" / "runs" / "run")

    result = controller.run(_action(), context)

    assert result.success
    assert result.stdout == "done"
    assert result.details["host"] == "remote"
    assert result.value is not None and result.value.label == "coverage"
    assert result.outputs[0].target == "https://example.test/report"
    assert transport.request is not None
    assert transport.request["schema"] == "poly.controller.request/v1"
    assert transport.request["capability"] == "process.execute"
    action_value = transport.request["action"]
    assert isinstance(action_value, dict)
    assert action_value["required_capability"] == "process.execute"


def test_remote_controller_rejects_invalid_responses() -> None:
    @dataclass
    class InvalidTransport:
        def invoke(self, request: dict[str, JsonValue]) -> dict[str, JsonValue]:
            return {"schema": "wrong", "id": request["id"]}

    descriptor = ControllerDescriptor(
        "remote", "linux", frozenset(("process.execute",)), "https://controller"
    )
    with pytest.raises(ControlPlaneError, match="incompatible"):
        RemoteController(descriptor, InvalidTransport()).run(
            _action(),
            ExecutionContext(Path.cwd(), Path.cwd() / ".poly" / "runs" / "run"),
        )

    with pytest.raises(ControlPlaneError, match="requires an endpoint"):
        RemoteController(
            ControllerDescriptor("remote", "linux", frozenset(("process.execute",))),
            InvalidTransport(),
        )
