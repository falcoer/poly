"""Command-line interface for Poly's initial local runtime."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from poly.application import inspect_workspace, prepare_planning
from poly.driver import DriverRegistry, ExecutionContext
from poly.drivers import git_driver, maven_driver
from poly.model import Node
from poly.reporting import (
    action_catalog_document,
    inspection_document,
    planning_document,
    render,
    run_document,
)
from poly.runtime import Executor, LocalActionRunner, RunStatus

REPORT_FORMATS = ("text", "json", "yaml", "xml")


def build_registry() -> DriverRegistry:
    registry = DriverRegistry()
    registry.register(git_driver())
    registry.register(maven_driver())
    return registry


def main(arguments: list[str] | None = None) -> int:
    parser = _parser()
    options = parser.parse_args(arguments)
    workspace = options.workspace.resolve()
    if not workspace.is_dir():
        parser.error(f"workspace does not exist or is not a directory: {workspace}")
    registry = build_registry()
    inspection = inspect_workspace(registry, workspace)

    if options.command == "inspect":
        document = inspection_document(inspection)
        exit_code = 0
    else:
        selected = _selection(options.select, inspection.inventory.nodes)
        _validate_selection(parser, selected, tuple(node.id for node in inspection.inventory.nodes))
        try:
            parameters = _parameters(options.parameter)
        except ValueError as error:
            parser.error(str(error))
        if options.command == "actions":
            verbs = (options.verb,) if options.verb else inspection.available_verbs
            _validate_verbs(parser, verbs, inspection.available_verbs)
            snapshots = tuple(
                prepare_planning(registry, inspection, verb, selected, parameters) for verb in verbs
            )
            document = action_catalog_document(snapshots)
            exit_code = 0
        else:
            _validate_verbs(parser, (options.verb,), inspection.available_verbs)
            snapshot = prepare_planning(registry, inspection, options.verb, selected, parameters)
            if options.command == "plan":
                document = planning_document(snapshot)
                exit_code = 0 if snapshot.plan.status.value in {"executable", "empty"} else 1
            else:
                run_directory = workspace / ".poly" / "runs" / snapshot.plan.id
                run_directory.mkdir(parents=True, exist_ok=True)
                context = ExecutionContext(workspace, run_directory)
                result = Executor(LocalActionRunner(registry)).execute(snapshot.plan, context)
                document = run_document(snapshot, result)
                exit_code = 0 if result.status in {RunStatus.SUCCEEDED, RunStatus.EMPTY} else 1

    sys.stdout.write(render(document, options.format))
    return exit_code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poly", description="Deterministic polyrepo engine")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="inspect the current workspace")
    _report_options(inspect)

    actions = commands.add_parser("actions", help="list currently applicable actions")
    actions.add_argument("verb", nargs="?", help="limit the catalog to one verb")
    _planning_options(actions)

    plan = commands.add_parser("plan", help="negotiate a finite plan without executing it")
    plan.add_argument("verb")
    _planning_options(plan)

    run = commands.add_parser("run", help="negotiate and execute a finite plan")
    run.add_argument("verb")
    _planning_options(run)
    return parser


def _report_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="workspace root (default: current directory)",
    )
    parser.add_argument("--format", choices=REPORT_FORMATS, default="text")


def _planning_options(parser: argparse.ArgumentParser) -> None:
    _report_options(parser)
    parser.add_argument(
        "--select",
        action="append",
        default=[],
        metavar="NODE[,NODE...]",
        help="select node IDs; repeat or use commas (default: all inspected nodes)",
    )
    parser.add_argument(
        "--parameter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="driver planning parameter",
    )


def _selection(values: list[str], nodes: tuple[Node, ...]) -> tuple[str, ...]:
    if not values:
        return tuple(node.id for node in nodes)
    selected = {
        node_id.strip() for value in values for node_id in value.split(",") if node_id.strip()
    }
    return tuple(sorted(selected))


def _parameters(values: list[str]) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for value in values:
        key, separator, parameter = value.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid --parameter {value!r}; expected KEY=VALUE")
        parameters[key.strip()] = parameter
    return parameters


def _validate_verbs(
    parser: argparse.ArgumentParser, requested: tuple[str, ...], available: tuple[str, ...]
) -> None:
    unknown = sorted(set(requested) - set(available))
    if unknown:
        parser.error(f"unknown verb(s): {', '.join(unknown)}; available: {', '.join(available)}")


def _validate_selection(
    parser: argparse.ArgumentParser, requested: tuple[str, ...], available: tuple[str, ...]
) -> None:
    unknown = sorted(set(requested) - set(available))
    if unknown:
        parser.error(f"unknown node(s): {', '.join(unknown)}")


if __name__ == "__main__":
    raise SystemExit(main())
