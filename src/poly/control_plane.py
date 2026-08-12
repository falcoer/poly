"""Capability-negotiated local and remote action controllers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from poly.driver import ExecutionContext
from poly.model import ActionSpec, JsonValue
from poly.runtime import ActionAttempt, ActionRunner


class ControlPlaneError(ValueError):
    pass


@dataclass(frozen=True, slots=True, order=True)
class ControllerDescriptor:
    name: str
    platform: str
    capabilities: frozenset[str]
    endpoint: str | None = None

    def __post_init__(self) -> None:
        if not self.name or any(character.isspace() for character in self.name):
            raise ControlPlaneError("controller name must be non-empty and contain no whitespace")
        if not self.platform:
            raise ControlPlaneError("controller platform must not be empty")
        if not self.capabilities or any(not capability for capability in self.capabilities):
            raise ControlPlaneError("controller must declare non-empty capabilities")

    def to_dict(self) -> dict[str, JsonValue]:
        capability_values: list[JsonValue] = [
            capability for capability in sorted(self.capabilities)
        ]
        return {
            "name": self.name,
            "platform": self.platform,
            "capabilities": capability_values,
            "endpoint": self.endpoint,
        }

    @classmethod
    def from_dict(cls, value: dict[str, JsonValue]) -> ControllerDescriptor:
        try:
            capabilities_value = value["capabilities"]
            if not isinstance(capabilities_value, list) or not all(
                isinstance(item, str) for item in capabilities_value
            ):
                raise TypeError("capabilities must be a string list")
            endpoint_value = value.get("endpoint")
            if endpoint_value is not None and not isinstance(endpoint_value, str):
                raise TypeError("endpoint must be a string or null")
            return cls(
                str(value["name"]),
                str(value["platform"]),
                frozenset(str(item) for item in capabilities_value),
                endpoint_value,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ControlPlaneError(f"invalid controller descriptor: {error}") from error


@runtime_checkable
class Controller(Protocol):
    @property
    def descriptor(self) -> ControllerDescriptor: ...

    def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt: ...


@dataclass(frozen=True, slots=True)
class LocalController:
    descriptor: ControllerDescriptor
    runner: ActionRunner

    def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
        return self.runner.run(action, context)


@runtime_checkable
class ControllerTransport(Protocol):
    def invoke(self, request: dict[str, JsonValue]) -> dict[str, JsonValue]: ...


@dataclass(frozen=True, slots=True)
class RemoteController:
    descriptor: ControllerDescriptor
    transport: ControllerTransport

    def __post_init__(self) -> None:
        if self.descriptor.endpoint is None:
            raise ControlPlaneError("a remote controller requires an endpoint")

    def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
        request_id = uuid.uuid4().hex
        response = self.transport.invoke(
            {
                "schema": "poly.controller.request/v1",
                "id": request_id,
                "capability": action.required_capability,
                "controller": self.descriptor.name,
                "workspace": str(context.workspace),
                "run_directory": str(context.run_directory),
                "action": _action_request(action),
            }
        )
        if response.get("schema") != "poly.controller.response/v1":
            raise ControlPlaneError("remote controller returned an incompatible response")
        if response.get("id") != request_id:
            raise ControlPlaneError("remote controller response id does not match the request")
        return _attempt_response(response)


class ControlPlane:
    def __init__(self, controllers: tuple[Controller, ...]) -> None:
        ordered = tuple(sorted(controllers, key=lambda controller: controller.descriptor.name))
        names = [controller.descriptor.name for controller in ordered]
        if len(names) != len(set(names)):
            raise ControlPlaneError("controller names must be unique")
        self._controllers = ordered

    def descriptors(self) -> tuple[ControllerDescriptor, ...]:
        return tuple(controller.descriptor for controller in self._controllers)

    def select(self, capability: str, requested_name: str | None = None) -> Controller:
        candidates = tuple(
            controller
            for controller in self._controllers
            if capability in controller.descriptor.capabilities
            and (requested_name is None or controller.descriptor.name == requested_name)
        )
        if not candidates:
            qualifier = f" on controller {requested_name!r}" if requested_name else ""
            raise ControlPlaneError(f"no controller provides {capability!r}{qualifier}")
        return candidates[0]

    def run(
        self,
        action: ActionSpec,
        context: ExecutionContext,
        requested_name: str | None = None,
    ) -> ActionAttempt:
        controller = self.select(action.required_capability, requested_name)
        return controller.run(action, context)


@dataclass(frozen=True, slots=True)
class ControlPlaneActionRunner:
    control_plane: ControlPlane
    requested_controller: str | None = None

    def run(self, action: ActionSpec, context: ExecutionContext) -> ActionAttempt:
        try:
            return self.control_plane.run(action, context, self.requested_controller)
        except ControlPlaneError as error:
            return ActionAttempt(False, str(error))


def _action_request(action: ActionSpec) -> dict[str, JsonValue]:
    return {
        "id": action.id,
        "driver": action.driver,
        "verb": action.verb,
        "operation": action.operation,
        "node_ids": list(action.node_ids),
        "command": list(action.command) if action.command is not None else None,
        "environment": dict(action.environment),
        "changes_structure": action.changes_structure,
        "required_capability": action.required_capability,
    }


def _attempt_response(value: dict[str, JsonValue]) -> ActionAttempt:
    success = value.get("success")
    if not isinstance(success, bool):
        raise ControlPlaneError("remote controller response has no boolean success")
    exit_code = value.get("exit_code")
    if exit_code is not None and not isinstance(exit_code, int):
        raise ControlPlaneError("remote controller exit_code must be an integer or null")
    details = value.get("details", {})
    if not isinstance(details, dict):
        raise ControlPlaneError("remote controller details must be an object")
    return ActionAttempt(
        success,
        str(value.get("summary", "")),
        exit_code,
        str(value.get("stdout", "")),
        str(value.get("stderr", "")),
        details,
    )
