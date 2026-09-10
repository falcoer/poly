"""Declarative configuration contracts contributed by drivers."""

from __future__ import annotations

import json
from dataclasses import dataclass

from jsonschema import Draft202012Validator

from poly.driver.api import FacadeArgument, FacadeRequest
from poly.model import Metadata


class ConfigurationError(ValueError):
    """A declaration cannot be interpreted by its versioned contract."""


@dataclass(frozen=True, slots=True)
class ConfigurationSchema:
    """An offline JSON Schema. References must stay inside this document."""

    identity: str
    schema: Metadata

    def __post_init__(self) -> None:
        if not self.identity or any(char.isspace() for char in self.identity):
            raise ConfigurationError("configuration schema identity must contain no whitespace")
        document = json.loads(json.dumps(dict(self.schema), allow_nan=False))
        _local_references(document)
        Draft202012Validator.check_schema(document)
        object.__setattr__(self, "schema", document)

    def validate(self, configuration: Metadata) -> None:
        if set(configuration) != {"schema", "values"}:
            raise ConfigurationError("configuration requires exactly 'schema' and 'values'")
        if configuration["schema"] != self.identity:
            raise ConfigurationError(f"expected configuration schema {self.identity!r}")
        errors = sorted(
            Draft202012Validator(self.schema).iter_errors(configuration["values"]),
            key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
        )
        if errors:
            error = errors[0]
            path = "/".join(str(part) for part in error.absolute_path)
            raise ConfigurationError(f"{self.identity}: values/{path}: {error.message}")


def _local_references(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(child, str) or not child.startswith("#")
            ):
                raise ConfigurationError("configuration schemas require document-local references")
            _local_references(child)
    elif isinstance(value, list):
        for child in value:
            _local_references(child)


@dataclass(frozen=True, slots=True)
class ConfigurationAddFacade:
    """Reusable add syntax; the technology supplies its schema and initial values."""

    name: str
    nature: str
    contract: ConfigurationSchema
    defaults: Metadata
    description: str = "declare a versioned configuration node"
    verb: str = "add"
    arguments: tuple[FacadeArgument, ...] = (
        FacadeArgument("node_id", ("node_id",), required=True),
        FacadeArgument("parent", ("--parent",)),
        FacadeArgument("configuration_file", ("--file",), help="YAML configuration values"),
    )

    def translate(self, request: FacadeRequest) -> dict[str, str]:
        from ruamel.yaml import YAML
        from ruamel.yaml.error import YAMLError

        node_id = request.values.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise ConfigurationError("configuration node id is required")
        values = dict(self.defaults)
        filename = request.values.get("configuration_file")
        if isinstance(filename, str):
            try:
                values = YAML(typ="safe").load(
                    (request.workspace / filename).read_text(encoding="utf-8")
                )
            except (OSError, YAMLError) as error:
                raise ConfigurationError(f"cannot read configuration: {error}") from error
        configuration: Metadata = {"schema": self.contract.identity, "values": values}
        self.contract.validate(configuration)
        parameters = dict(request.parameters)
        parameters.update(
            {
                "poly.node.id": node_id,
                "poly.node.kind": "configuration",
                "poly.node.natures": self.nature,
                "poly.node.configuration": json.dumps(
                    configuration, sort_keys=True, allow_nan=False
                ),
            }
        )
        parent = request.values.get("parent")
        if isinstance(parent, str) and parent:
            parameters["poly.node.parent"] = parent
        return parameters
