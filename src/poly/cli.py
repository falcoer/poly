"""Command-line interface for Poly's initial local runtime."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable
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
from poly.model import ActionSpec, Node
from poly.persistence import StateError, StateStore
from poly.reporting import (
    ReportDocument,
    action_catalog_document,
    controllers_document,
    drivers_document,
    inspection_document,
    natures_document,
    planning_document,
    render,
    render_cli,
    render_cli_completion,
    render_cli_event,
    render_cli_start,
    run_document,
)
from poly.runtime import Executor, LocalActionRunner, RunEvent, RunStatus
from poly.workspace import WorkspaceError, validate_workspace

REPORT_FORMATS = ("text", "json", "yaml", "xml")
RESERVED_COMMANDS = frozenset(
    (
        "actions",
        "controllers",
        "driver",
        "drivers",
        "inspect",
        "nature",
        "plan",
        "report",
        "run",
    )
)
INTERNAL_VERBS = frozenset(("bootstrap", "nature-add", "nature-remove"))


def build_registry() -> DriverRegistry:
    registry = DriverRegistry()
    registry.register(constructor_driver())
    registry.register(git_driver())
    registry.register(maven_driver())
    return registry


def main(arguments: list[str] | None = None) -> int:
    registry = build_registry()
    parser = _parser(registry)
    raw_arguments = list(sys.argv[1:] if arguments is None else arguments)
    options = parser.parse_args(raw_arguments)
    command = shlex.join(["poly", *raw_arguments])
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
    if options.command == "init" and options.root_repository:
        return _bootstrap_root(parser, options, registry, command)
    if options.command == "nature":
        return _nature_command(parser, options, registry, command)
    workspace = options.workspace.resolve()
    if not workspace.is_dir():
        parser.error(f"workspace does not exist or is not a directory: {workspace}")
    if options.command == "report":
        try:
            document = StateStore(workspace).load_report(options.run_id)
        except StateError as error:
            parser.error(str(error))
        _write_output(document, options, command, 0)
        return 0
    if options.command == "controllers":
        plane = _control_plane(registry)
        document = controllers_document(workspace, plane.descriptors())
        _write_output(document, options, command, 0)
        return 0
    if options.command == "drivers":
        document = drivers_document(workspace, registry.manifests())
        _write_output(document, options, command, 0)
        return 0

    streamed = False
    try:
        inspection = inspect_workspace(
            registry, workspace, remote=getattr(options, "remote", False)
        )
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
                streamed = options.format == "text"
                listener = _event_listener(snapshot.plan.actions, options) if streamed else None
                if streamed:
                    _write_stream(
                        render_cli_start(
                            planning_document(snapshot),
                            command,
                            verbosity=options.verbosity,
                            color=_color_enabled(options),
                        )
                    )
                result = Executor(runner, listener).execute(snapshot.plan, context)
                document = run_document(snapshot, result)
                _save_run_if_initialized(workspace, snapshot.plan.id, document)
                exit_code = 0 if result.status in {RunStatus.SUCCEEDED, RunStatus.EMPTY} else 1
                if streamed:
                    _write_stream(
                        render_cli_completion(
                            document,
                            verbosity=options.verbosity,
                            color=_color_enabled(options),
                            exit_code=exit_code,
                        )
                    )

    if not streamed:
        _write_output(document, options, command, exit_code)
    return exit_code


def _parser(registry: DriverRegistry) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poly", description="Deterministic polyrepo engine")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="inspect the current workspace")
    inspect.add_argument(
        "--remote",
        action="store_true",
        help="compare locked Git sources with their requested remote references",
    )
    _report_options(inspect)

    init = commands.add_parser("init", help="initialize an existing directory as a Poly workspace")
    init.add_argument("root_repository", nargs="?", help="root control repository to clone")
    init.add_argument("target", nargs="?", type=Path, help="bootstrap target directory")
    init.add_argument("--ref", help="root repository branch, tag, or commit")
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
    add.add_argument("--repo", help="Git repository URL")
    add.add_argument("--ref", help="requested Git branch, tag, or commit")
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

    nature = commands.add_parser("nature", help="list or edit contextual node natures")
    nature_commands = nature.add_subparsers(dest="nature_command", required=True)
    nature_list = nature_commands.add_parser("list", help="list natures contributed by drivers")
    _report_options(nature_list)
    for operation in ("add", "remove"):
        change = nature_commands.add_parser(operation, help=f"{operation} node natures")
        change.add_argument(
            "values",
            nargs="+",
            metavar="[NODE|.] NATURE",
            help="optional node (or '.') followed by one or more natures",
        )
        _direct_verb_options(change)

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
    dynamic = sorted(set(_driver_verbs(registry)) - RESERVED_COMMANDS - INTERNAL_VERBS - structural)
    for verb in dynamic:
        direct = commands.add_parser(verb, help=f"plan and execute the {verb!r} driver verb")
        if verb == "lock":
            direct.add_argument(
                "--from-workspace",
                action="store_true",
                help="adopt clean local HEAD commits into poly.lock.yaml",
            )
        _direct_verb_options(direct)
    return parser


def _nature_command(
    parser: argparse.ArgumentParser,
    options: argparse.Namespace,
    registry: DriverRegistry,
    command: str,
) -> int:
    start = options.workspace.resolve()
    if not start.is_dir():
        parser.error(f"workspace does not exist or is not a directory: {start}")
    workspace = _nearest_workspace(start)
    if options.nature_command == "list":
        document = natures_document(workspace or start, registry.manifests())
        _write_output(document, options, command, 0)
        return 0
    if workspace is None:
        parser.error(f"no Poly workspace found from {start}")
    try:
        inspection = inspect_workspace(registry, workspace)
        node_id, natures = _nature_target(
            options.values, inspection.inventory.nodes, workspace, start
        )
    except WorkspaceError as error:
        parser.error(str(error))
    snapshot = prepare_planning(
        registry,
        inspection,
        f"nature-{options.nature_command}",
        (node_id,),
        {"poly.node.natures": ",".join(natures)},
    )
    if options.plan_only:
        document = planning_document(snapshot)
        exit_code = 0 if snapshot.plan.status.value in {"executable", "empty"} else 1
        _write_output(document, options, command, exit_code)
        return exit_code
    run_directory = workspace / ".poly" / "runs" / snapshot.plan.id
    run_directory.mkdir(parents=True, exist_ok=True)
    streamed = options.format == "text"
    if streamed:
        _write_stream(
            render_cli_start(
                planning_document(snapshot),
                command,
                verbosity=options.verbosity,
                color=_color_enabled(options),
            )
        )
    result = Executor(
        _controller_runner(registry, options.controller),
        _event_listener(snapshot.plan.actions, options) if streamed else None,
    ).execute(snapshot.plan, ExecutionContext(workspace, run_directory))
    document = run_document(snapshot, result)
    _save_run_if_initialized(workspace, snapshot.plan.id, document)
    exit_code = 0 if result.status in {RunStatus.SUCCEEDED, RunStatus.EMPTY} else 1
    if streamed:
        _write_stream(
            render_cli_completion(
                document,
                verbosity=options.verbosity,
                color=_color_enabled(options),
                exit_code=exit_code,
            )
        )
    else:
        _write_output(document, options, command, exit_code)
    return exit_code


def _nearest_workspace(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / WORKSPACE_MANIFEST).is_file():
            return candidate
    return None


def _nature_target(
    values: list[str], nodes: tuple[Node, ...], workspace: Path, current: Path
) -> tuple[str, tuple[str, ...]]:
    node_ids = {node.id for node in nodes}
    if values[0] == ".":
        node_id = _current_node(nodes, workspace, current)
        natures = values[1:]
    elif values[0] in node_ids and len(values) > 1:
        node_id = values[0]
        natures = values[1:]
    else:
        node_id = _current_node(nodes, workspace, current)
        natures = values
    normalized = tuple(sorted({nature.strip() for nature in natures if nature.strip()}))
    if not normalized:
        raise WorkspaceError("at least one nature is required")
    return node_id, normalized


def _current_node(nodes: tuple[Node, ...], workspace: Path, current: Path) -> str:
    candidates: list[tuple[int, int, str]] = []
    parents = {
        node.id: node.metadata.get("poly.parent")
        for node in nodes
        if isinstance(node.metadata.get("poly.parent"), str)
    }
    for node in nodes:
        path = (workspace / node.path).resolve()
        if path != current and path not in current.parents:
            continue
        depth = 0
        parent = parents.get(node.id)
        while isinstance(parent, str):
            depth += 1
            parent = parents.get(parent)
        candidates.append((len(path.parts), depth, node.id))
    if not candidates:
        raise WorkspaceError(f"current directory does not belong to a declared node: {current}")
    return max(candidates)[2]


def _bootstrap_root(
    parser: argparse.ArgumentParser,
    options: argparse.Namespace,
    registry: DriverRegistry,
    command: str,
) -> int:
    if options.target is None:
        parser.error("root repository bootstrap requires a target directory")
    target = options.target.resolve()
    parent = target.parent
    if not parent.is_dir():
        parser.error(f"bootstrap target parent does not exist: {parent}")
    if target.exists() and not target.is_dir():
        parser.error(f"bootstrap target is not a directory: {target}")
    inspection = inspect_workspace(registry, parent)
    parameters = {
        "poly.source.url": options.root_repository,
        "poly.node.path": target.name,
    }
    if options.ref:
        parameters["poly.source.ref"] = options.ref
    snapshot = prepare_planning(registry, inspection, "bootstrap", (), parameters)
    if options.plan_only:
        exit_code = 0 if snapshot.plan.status.value == "executable" else 1
        _write_output(planning_document(snapshot), options, command, exit_code)
        return exit_code
    with tempfile.TemporaryDirectory(prefix="poly-bootstrap-", dir=parent) as run_path:
        result = Executor(_controller_runner(registry, options.controller)).execute(
            snapshot.plan, ExecutionContext(parent, Path(run_path))
        )
        root_document = run_document(snapshot, result)
        if result.status is not RunStatus.SUCCEEDED:
            _write_output(root_document, options, command, 1)
            return 1
    try:
        validate_workspace(target)
        hydration_inspection = inspect_workspace(registry, target)
    except WorkspaceError as error:
        parser.error(f"root repository has no valid committed workspace: {error}")
    source_ids = tuple(
        node.id
        for node in hydration_inspection.inventory.nodes
        if isinstance(node.metadata.get("poly.source.url"), str)
    )
    hydration = prepare_planning(registry, hydration_inspection, "hydrate", source_ids)
    run_directory = target / ".poly" / "runs" / hydration.plan.id
    run_directory.mkdir(parents=True, exist_ok=True)
    hydrated = Executor(_controller_runner(registry, options.controller)).execute(
        hydration.plan, ExecutionContext(target, run_directory)
    )
    document = run_document(hydration, hydrated)
    document["kind"] = "bootstrap"
    document["phases"] = [
        {
            "name": "root-bootstrap",
            "plan-id": snapshot.plan.id,
            "status": result.status.value,
        },
        {
            "name": "recursive-hydration",
            "plan-id": hydration.plan.id,
            "status": hydrated.status.value,
        },
    ]
    StateStore(target).save_run(hydration.plan.id, document)
    exit_code = 0 if hydrated.status in {RunStatus.SUCCEEDED, RunStatus.EMPTY} else 1
    _write_output(document, options, command, exit_code)
    return exit_code


def _controller_runner(
    registry: DriverRegistry, requested_controller: str | None
) -> ControlPlaneActionRunner:
    return ControlPlaneActionRunner(_control_plane(registry), requested_controller)


def _control_plane(registry: DriverRegistry) -> ControlPlane:
    descriptor = ControllerDescriptor(
        "local",
        sys.platform,
        frozenset(("driver.execute", "git.materialize", "process.execute", "workspace.construct")),
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
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-q",
        "--quiet",
        action="store_const",
        const=-1,
        default=0,
        dest="verbosity",
        help="print only the final command result",
    )
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="count",
        dest="verbosity",
        help="increase detail; use -vv for the complete canonical report",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colorize interactive text output (default: auto)",
    )


def _write_output(
    document: ReportDocument,
    options: argparse.Namespace,
    command: str,
    exit_code: int,
) -> None:
    if options.format != "text":
        sys.stdout.write(render(document, options.format))
        return
    sys.stdout.write(
        render_cli(
            document,
            command,
            verbosity=options.verbosity,
            color=_color_enabled(options),
            exit_code=exit_code,
        )
    )


def _color_enabled(options: argparse.Namespace) -> bool:
    return options.color == "always" or (
        options.color == "auto" and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    )


def _event_listener(
    actions: tuple[ActionSpec, ...], options: argparse.Namespace
) -> Callable[[RunEvent], None]:
    by_id = {action.id: action for action in actions}

    def listener(event: RunEvent) -> None:
        _write_stream(
            render_cli_event(
                event,
                by_id.get(event.action_id),
                verbosity=options.verbosity,
                color=_color_enabled(options),
            )
        )

    return listener


def _write_stream(value: str) -> None:
    if value:
        sys.stdout.write(value)
        sys.stdout.flush()


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
        kind = "repository" if options.repo else options.kind
        parameters.update(
            {
                "poly.node.id": options.node_id,
                "poly.node.path": options.node_path,
                "poly.node.kind": kind,
                "poly.node.natures": ",".join(options.nature),
            }
        )
        if options.parent:
            parameters["poly.node.parent"] = options.parent
        repository = options.repo
        requested_ref = options.ref
        existing = options.workspace.resolve() / options.node_path
        if repository is None and options.parent is None and (existing / ".git").exists():
            repository = _git_value(existing, "remote", "get-url", "origin")
            requested_ref = requested_ref or _git_value(
                existing, "symbolic-ref", "--quiet", "--short", "HEAD"
            )
            parameters["poly.node.kind"] = "repository"
        if repository:
            parameters["poly.source.url"] = _repository_url(repository)
        if requested_ref:
            parameters["poly.source.ref"] = requested_ref
    elif options.command == "remove":
        parameters["poly.node.id"] = options.node_id
    elif options.command == "lock" and options.from_workspace:
        parameters["poly.lock.from-workspace"] = "true"
    return parameters


def _git_value(directory: Path, *arguments: str) -> str | None:
    process = subprocess.run(
        ("git", "-C", str(directory), *arguments),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    value = process.stdout.strip()
    return value if process.returncode == 0 and value else None


def _repository_url(value: str) -> str:
    if "://" in value or value.startswith("git@"):
        return value
    candidate = Path(value)
    if candidate.is_absolute() or candidate.exists():
        return candidate.resolve().as_uri()
    return value


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
