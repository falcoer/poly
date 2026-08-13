"""Command-line interface for Poly's initial local runtime."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from poly.application import inspect_workspace, prepare_planning
from poly.construction import WORKSPACE_MANIFEST, constructor_driver
from poly.control_plane import (
    ControllerDescriptor,
    ControlPlane,
    ControlPlaneActionRunner,
    LocalController,
)
from poly.driver import DriverRegistry, ExecutionContext
from poly.driver.scaffold import DriverScaffoldError, scaffold_driver
from poly.drivers import git_driver, maven_driver
from poly.model import Node
from poly.persistence import StateError, StateStore
from poly.reporting import (
    ReportDocument,
    action_catalog_document,
    controllers_document,
    drivers_document,
    inspection_document,
    planning_document,
    render,
    run_document,
)
from poly.runtime import Executor, LocalActionRunner, RunStatus
from poly.workspace import WorkspaceError

REPORT_FORMATS = ("text", "json", "yaml", "xml")
RESERVED_COMMANDS = frozenset(
    ("actions", "controllers", "driver", "drivers", "inspect", "plan", "report", "run")
)


def build_registry() -> DriverRegistry:
    registry = DriverRegistry()
    registry.register(constructor_driver())
    registry.register(git_driver())
    registry.register(maven_driver())
    return registry


def main(arguments: list[str] | None = None) -> int:
    registry = build_registry()
    parser = _parser(registry)
    options = parser.parse_args(arguments)
    if options.command == "driver":
        try:
            scaffolded = scaffold_driver(
                options.name,
                options.path,
                poly_source=options.poly_source,
            )
        except DriverScaffoldError as error:
            parser.error(str(error))
        print(f"Created {scaffolded.distribution_name} in {scaffolded.target}")
        return 0
    workspace = options.workspace.resolve()
    if not workspace.is_dir():
        parser.error(f"workspace does not exist or is not a directory: {workspace}")
    if options.command == "report":
        try:
            document = StateStore(workspace).load_report(options.run_id)
        except StateError as error:
            parser.error(str(error))
        sys.stdout.write(render(document, options.format))
        return 0
    if options.command == "controllers":
        plane = _control_plane(registry)
        sys.stdout.write(
            render(controllers_document(workspace, plane.descriptors()), options.format)
        )
        return 0
    if options.command == "drivers":
        sys.stdout.write(render(drivers_document(workspace, registry.manifests()), options.format))
        return 0

    try:
        inspection = inspect_workspace(registry, workspace)
    except WorkspaceError as error:
        parser.error(str(error))

    if options.command == "inspect":
        document = inspection_document(inspection)
        _save_inventory_if_initialized(workspace, document)
        exit_code = 0
    else:
        selected = _selection(options.select, inspection.inventory.nodes)
        _validate_selection(parser, selected, tuple(node.id for node in inspection.inventory.nodes))
        try:
            parameters = _command_parameters(options)
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
            verb = options.verb if options.command in {"plan", "run"} else options.command
            _validate_verbs(parser, (verb,), inspection.available_verbs)
            snapshot = prepare_planning(registry, inspection, verb, selected, parameters)
            plan_only = options.command == "plan" or getattr(options, "plan_only", False)
            if plan_only:
                document = planning_document(snapshot)
                _save_plan_if_initialized(workspace, snapshot.plan.id, document)
                exit_code = 0 if snapshot.plan.status.value in {"executable", "empty"} else 1
            else:
                run_directory = workspace / ".poly" / "runs" / snapshot.plan.id
                run_directory.mkdir(parents=True, exist_ok=True)
                context = ExecutionContext(workspace, run_directory)
                runner = _controller_runner(registry, options.controller)
                result = Executor(runner).execute(snapshot.plan, context)
                document = run_document(snapshot, result)
                _save_run_if_initialized(workspace, snapshot.plan.id, document)
                exit_code = 0 if result.status in {RunStatus.SUCCEEDED, RunStatus.EMPTY} else 1

    sys.stdout.write(render(document, options.format))
    return exit_code


def _parser(registry: DriverRegistry) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poly", description="Deterministic polyrepo engine")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="inspect the current workspace")
    _report_options(inspect)

    init = commands.add_parser("init", help="initialize an existing directory as a Poly workspace")
    init.add_argument("--name", help="workspace name (default: directory name)")
    _direct_verb_options(init)

    add = commands.add_parser("add", help="add a declared node to an initialized workspace")
    add.add_argument("node_id")
    add.add_argument("--path", required=True, dest="node_path")
    add.add_argument("--parent", help="parent node (default: workspace root)")
    add.add_argument(
        "--kind",
        choices=("repository", "module"),
        default="module",
        help="declared node kind (default: module)",
    )
    add.add_argument("--nature", action="append", default=[])
    _direct_verb_options(add)

    remove = commands.add_parser("remove", help="remove a leaf node from the composition")
    remove.add_argument("node_id")
    _direct_verb_options(remove)

    actions = commands.add_parser("actions", help="list currently applicable actions")
    actions.add_argument("verb", nargs="?", help="limit the catalog to one verb")
    _planning_options(actions)

    plan = commands.add_parser("plan", help="negotiate a finite plan without executing it")
    plan.add_argument("verb")
    _planning_options(plan)

    run = commands.add_parser("run", help="negotiate and execute a finite plan")
    run.add_argument("verb")
    run.add_argument("--controller", default="local")
    _planning_options(run)

    report = commands.add_parser("report", help="render a persisted plan or run")
    report.add_argument("run_id")
    _report_options(report)

    controllers = commands.add_parser("controllers", help="list controller capabilities")
    _report_options(controllers)

    drivers = commands.add_parser("drivers", help="list registered technology drivers")
    _report_options(drivers)

    driver = commands.add_parser("driver", help="develop external drivers")
    driver_commands = driver.add_subparsers(dest="driver_command", required=True)
    new_driver = driver_commands.add_parser("new", help="create a driver repository")
    new_driver.add_argument("name", help="lowercase kebab-case technology name")
    new_driver.add_argument("--path", type=Path, required=True)
    new_driver.add_argument(
        "--poly-source",
        type=Path,
        help="use a local Poly checkout instead of the validated Git tag",
    )
    structural = {"init", "add", "remove"}
    dynamic = sorted(set(_driver_verbs(registry)) - RESERVED_COMMANDS - structural)
    for verb in dynamic:
        direct = commands.add_parser(verb, help=f"plan and execute the {verb!r} driver verb")
        _direct_verb_options(direct)
    return parser


def _controller_runner(
    registry: DriverRegistry, requested_controller: str | None
) -> ControlPlaneActionRunner:
    return ControlPlaneActionRunner(_control_plane(registry), requested_controller)


def _control_plane(registry: DriverRegistry) -> ControlPlane:
    descriptor = ControllerDescriptor(
        "local",
        sys.platform,
        frozenset(("driver.execute", "process.execute", "workspace.construct")),
    )
    local = LocalController(descriptor, LocalActionRunner(registry))
    return ControlPlane((local,))


def _save_inventory_if_initialized(workspace: Path, document: ReportDocument) -> None:
    if (workspace / WORKSPACE_MANIFEST).is_file():
        StateStore(workspace).save_inventory(document)


def _save_plan_if_initialized(workspace: Path, plan_id: str, document: ReportDocument) -> None:
    if (workspace / WORKSPACE_MANIFEST).is_file():
        StateStore(workspace).save_plan(plan_id, document)


def _save_run_if_initialized(workspace: Path, run_id: str, document: ReportDocument) -> None:
    if (workspace / WORKSPACE_MANIFEST).is_file():
        StateStore(workspace).save_run(run_id, document)


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


def _direct_verb_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan", action="store_true", dest="plan_only")
    parser.add_argument("--controller", default="local")
    _planning_options(parser)


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


def _command_parameters(options: argparse.Namespace) -> dict[str, str]:
    parameters = _parameters(options.parameter)
    if options.command == "init":
        parameters["poly.name"] = options.name or options.workspace.resolve().name
    elif options.command == "add":
        parameters.update(
            {
                "poly.node.id": options.node_id,
                "poly.node.path": options.node_path,
                "poly.node.kind": options.kind,
                "poly.node.natures": ",".join(options.nature),
            }
        )
        if options.parent:
            parameters["poly.node.parent"] = options.parent
    elif options.command == "remove":
        parameters["poly.node.id"] = options.node_id
    return parameters


def _driver_verbs(registry: DriverRegistry) -> tuple[str, ...]:
    verbs = tuple(
        sorted({verb for provider in registry.planning_providers() for verb in provider.verbs})
    )
    collisions = sorted(set(verbs) & RESERVED_COMMANDS)
    if collisions:
        raise ValueError(f"driver verbs collide with reserved commands: {', '.join(collisions)}")
    return verbs


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
