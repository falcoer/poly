"""Black-box conformance commands for packaged external Poly drivers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from poly.driver.api import InspectionContext
from poly.driver.discovery import ExternalDriverSpec, load_entrypoint, load_external_driver
from poly.driver.testkit import (
    assert_inspection_side_effect_free,
    assert_manifest_compatible,
    assert_planning_deterministic,
)
from poly.model import Inventory, Node, PlanningRequest


def main(arguments: list[str] | None = None) -> int:
    parser = _parser()
    options = parser.parse_args(arguments)
    target_path = Path(options.target)
    registration = (
        load_external_driver(ExternalDriverSpec.from_file(target_path.resolve()))
        if target_path.suffix.casefold() == ".toml" or target_path.is_file()
        else load_entrypoint(options.target)
    )
    assert_manifest_compatible(registration.manifest)

    if options.command == "validate":
        value: object = registration.manifest.to_dict()
    else:
        workspace = options.workspace.resolve()
        if not workspace.is_dir():
            parser.error(f"workspace does not exist: {workspace}")
        nodes: list[Node] = []
        for inspector in registration.inspectors:
            context = InspectionContext(workspace)
            assert_inspection_side_effect_free(inspector, context)
            nodes.extend(inspector.inspect(context).nodes)
        inventory = Inventory(tuple(nodes))
        if options.command == "inspect":
            value = {
                "driver": registration.manifest.name,
                "nodes": [
                    {
                        "id": node.id,
                        "path": node.path,
                        "natures": list(node.natures),
                    }
                    for node in inventory.nodes
                ],
            }
        else:
            selected = tuple(options.select) or tuple(node.id for node in inventory.nodes)
            request = PlanningRequest(options.verb, inventory, selected)
            planners = tuple(
                planner for planner in registration.planners if options.verb in planner.verbs
            )
            if not planners:
                parser.error(
                    f"driver {registration.manifest.name!r} does not provide verb {options.verb!r}"
                )
            value = {
                "driver": registration.manifest.name,
                "verb": options.verb,
                "actions": [
                    action.id
                    for planner in planners
                    for action in assert_planning_deterministic(planner, request, workspace).actions
                ],
            }
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poly-driver-test")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate manifest and registration")
    _spec_option(validate)

    inspect = commands.add_parser("inspect", help="check deterministic, read-only inspection")
    _spec_option(inspect)
    inspect.add_argument("--workspace", type=Path, required=True)

    determinism = commands.add_parser("determinism", help="check deterministic, read-only planning")
    _spec_option(determinism)
    determinism.add_argument("--workspace", type=Path, required=True)
    determinism.add_argument("--verb", required=True)
    determinism.add_argument("--select", action="append", default=[])
    return parser


def _spec_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target", nargs="?", default="poly-driver.toml")


if __name__ == "__main__":
    raise SystemExit(main())
