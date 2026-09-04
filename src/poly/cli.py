"""Command-line interface for Poly's initial local runtime."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any

from poly._version import __version__
from poly.application import inspect_workspace, prepare_planning
from poly.construction import WORKSPACE_MANIFEST, constructor_driver
from poly.control_plane import (
    ControllerDescriptor,
    ControlPlane,
    ControlPlaneActionRunner,
    LocalController,
)
from poly.driver import (
    DriverOrigin,
    DriverRegistry,
    ExecutionContext,
    FacadeRequest,
    OutputReference,
    discover_external_drivers,
)
from poly.driver.scaffold import DriverScaffoldError, scaffold_driver
from poly.drivers import git_driver, maven_driver
from poly.drivers.git import _positive_depth
from poly.model import Node
from poly.persistence import StateError, StateStore
from poly.prepared import (
    PreparedPlanError,
    deferred_document,
    is_deferred_document,
    require_current,
    resolve_deferred_document,
)
from poly.reporting import (
    ReportDocument,
    action_catalog_document,
    controllers_document,
    document_with_outputs,
    drivers_document,
    inspection_document,
    natures_document,
    planning_document,
    prepared_run_document,
    render,
    render_cli,
    run_document,
)
from poly.runtime import Executor, LocalActionRunner, RunStatus
from poly.terminal import SerializedRunRenderer, TerminalCapabilities
from poly.workspace import WorkspaceError, validate_workspace

REPORT_FORMATS = ("text", "json", "yaml", "xml")
RESERVED_COMMANDS = frozenset(
    (
        "actions",
        "controllers",
        "driver",
        "drivers",
        "exec",
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
    registry.register(constructor_driver(), origin=DriverOrigin.SYSTEM)
    registry.register(git_driver(), origin=DriverOrigin.BUILTIN)
    registry.register(maven_driver(), origin=DriverOrigin.BUILTIN)
    discover_external_drivers(registry)
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
    if getattr(options, "prepare", False):
        verb = options.verb if options.command == "run" else options.command
        _validate_verbs(parser, (verb,), _driver_verbs(registry))
        try:
            parameters = _command_parameters(options, registry)
        except ValueError as error:
            parser.error(str(error))
        document = _append_prepared_command(
            parser,
            workspace,
            verb,
            _selection_values(options.select),
            not options.select,
            parameters,
            command,
        )
        _write_output(document, options, command, 0)
        return 0
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
        document = drivers_document(workspace, registry.inventory())
        _write_output(document, options, command, 0)
        return 0
    if options.command == "plan":
        store = StateStore(workspace)
        if options.plan_command == "clean":
            removed = store.clear_prepared_plan()
            document = _empty_prepared_document(workspace, "cleared" if removed else "empty")
        elif not (store.state_directory / "plan.json").is_file():
            document = _empty_prepared_document(workspace, "empty")
        else:
            try:
                document = store.load_prepared_plan()
            except StateError as error:
                parser.error(str(error))
        _write_output(_document_for_verb(document, "plan"), options, command, 0)
        return 0
    if options.command == "exec":
        store = StateStore(workspace)
        try:
            prepared = store.load_prepared_plan()
            if is_deferred_document(prepared):
                inspection = inspect_workspace(registry, workspace)
                resolved, plan = resolve_deferred_document(registry, inspection, prepared)
                if plan.status.value not in {"executable", "empty"}:
                    failed = dict(prepared)
                    failed["resolution"] = resolved.get("plan", {})
                    store.save_prepared_plan(failed)
                    raise PreparedPlanError(
                        f"prepared commands resolve to a {plan.status.value} plan; "
                        "inspect 'poly plan' diagnostics before retrying"
                    )
                store.save_prepared_plan(resolved)
                prepared = resolved
            else:
                plan = require_current(prepared, workspace)
        except (StateError, PreparedPlanError, WorkspaceError) as error:
            parser.error(str(error))
        run_directory = workspace / ".poly" / "runs" / plan.id
        run_directory.mkdir(parents=True, exist_ok=True)
        streamed = options.format == "text"
        renderer = (
            SerializedRunRenderer(
                sys.stdout,
                plan.actions,
                options.verbosity,
                _color_enabled(options),
                force_flow=options.flow,
            )
            if streamed
            else None
        )
        execution_document = _document_for_verb(prepared, "exec")
        if renderer is not None:
            renderer.start(execution_document, command)
        try:
            result = Executor(
                _controller_runner(registry, options.controller),
                renderer.handle if renderer else None,
            ).execute(plan, ExecutionContext(workspace, run_directory))
        except BaseException:
            if renderer is not None:
                renderer.abort()
            raise
        document = prepared_run_document(execution_document, result)
        store.save_run(plan.id, document)
        exit_code = 0 if result.status in {RunStatus.SUCCEEDED, RunStatus.EMPTY} else 1
        if exit_code == 0:
            store.clear_prepared_plan()
        if renderer is not None:
            renderer.finish(document, exit_code)
        else:
            _write_output(document, options, command, exit_code)
        return exit_code

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
        if options.output is not None:
            output = options.output.resolve()
            document = document_with_outputs(
                document,
                (
                    OutputReference(
                        "file",
                        str(output),
                        "Inspection report",
                        _report_media_type(options.format),
                    ),
                ),
            )
            try:
                _write_report_file(output, render(document, options.format))
            except OSError as error:
                parser.error(f"cannot write inspection report {output}: {error}")
            options.format = "text"
        exit_code = 0
    else:
        selected = _selection(options.select, inspection.inventory.nodes)
        _validate_selection(parser, selected, tuple(node.id for node in inspection.inventory.nodes))
        try:
            parameters = _command_parameters(options, registry)
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
            verb = options.verb if options.command == "run" else options.command
            _validate_verbs(parser, (verb,), inspection.available_verbs)
            snapshot = prepare_planning(registry, inspection, verb, selected, parameters)
            plan_only = getattr(options, "plan_only", False)
            if plan_only:
                document = planning_document(snapshot)
                _save_plan_if_initialized(workspace, snapshot.plan.id, document)
                exit_code = 0 if snapshot.plan.status.value in {"executable", "empty"} else 1
            elif getattr(options, "prepare", False):
                raise AssertionError("preparation must be handled before inspection")
            else:
                if (workspace / ".poly" / "state" / "plan.json").is_file():
                    parser.error("a prepared plan is active; use 'poly exec' or 'poly plan clean'")
                run_directory = workspace / ".poly" / "runs" / snapshot.plan.id
                run_directory.mkdir(parents=True, exist_ok=True)
                context = ExecutionContext(workspace, run_directory)
                runner = _controller_runner(registry, options.controller)
                streamed = options.format == "text"
                renderer = (
                    SerializedRunRenderer(
                        sys.stdout,
                        snapshot.plan.actions,
                        options.verbosity,
                        _color_enabled(options),
                        force_flow=options.flow,
                    )
                    if streamed
                    else None
                )
                if streamed:
                    assert renderer is not None
                    renderer.start(planning_document(snapshot), command)
                try:
                    result = Executor(runner, renderer.handle if renderer else None).execute(
                        snapshot.plan, context
                    )
                except BaseException:
                    if renderer is not None:
                        renderer.abort()
                    raise
                document = run_document(snapshot, result)
                _save_run_if_initialized(workspace, snapshot.plan.id, document)
                exit_code = 0 if result.status in {RunStatus.SUCCEEDED, RunStatus.EMPTY} else 1
                if streamed:
                    assert renderer is not None
                    renderer.finish(document, exit_code)

    if not streamed:
        _write_output(document, options, command, exit_code)
    return exit_code


def _parser(registry: DriverRegistry) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poly", description="Deterministic polyrepo engine")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="inspect the current workspace")
    inspect.add_argument(
        "--remote",
        action="store_true",
        help="compare locked Git sources with their requested remote references",
    )
    inspect.add_argument(
        "--output",
        type=Path,
        help="write the inspection report to this file and expose it as an output",
    )
    _report_options(inspect)

    init = commands.add_parser("init", help="initialize an existing directory as a Poly workspace")
    init.add_argument("root_repository", nargs="?", help="root control repository to clone")
    init.add_argument("target", nargs="?", type=Path, help="bootstrap target directory")
    init.add_argument("--ref", help="root repository branch, tag, or commit")
    init.add_argument("--name", help="workspace name (default: directory name)")
    _direct_verb_options(init)

    add = commands.add_parser("add", help="add through a driver-contributed facade")
    add_facades = add.add_subparsers(dest="facade", required=True)
    for facade in registry.command_facades("add"):
        facade_parser = add_facades.add_parser(facade.name, help=facade.description)
        for argument in facade.arguments:
            keywords: dict[str, Any] = {"help": argument.help}
            if not argument.positional:
                keywords["dest"] = argument.name
                keywords["required"] = argument.required
            if argument.repeatable:
                keywords.update(action="append", default=[])
            if argument.choices:
                keywords["choices"] = argument.choices
            facade_parser.add_argument(*argument.flags, **keywords)
        _direct_verb_options(facade_parser)

    remove = commands.add_parser("remove", help="remove a leaf node from the composition")
    remove.add_argument("node_id")
    _direct_verb_options(remove)

    actions = commands.add_parser("actions", help="list currently applicable actions")
    actions.add_argument("verb", nargs="?", help="limit the catalog to one verb")
    _planning_options(actions)

    plan = commands.add_parser("plan", help="display or clear the current prepared plan")
    plan.add_argument("plan_command", nargs="?", choices=("clean",))
    _report_options(plan)

    execute = commands.add_parser("exec", help="execute the exact current prepared plan")
    execute.add_argument("--controller", default="local")
    _report_options(execute)

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
        if verb == "hydrate":
            direct.add_argument(
                "--depth",
                help="override shallow clone depth for this hydration only",
            )
            direct.add_argument(
                "--unshallow",
                action="store_true",
                help="convert shallow repositories to complete history",
            )
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
    if options.prepare:
        parameters = {
            "poly.prepare.nature.values": "\x1f".join(options.values),
            "poly.prepare.nature.cwd": str(start),
        }
        document = _append_prepared_command(
            parser, workspace, f"nature-{options.nature_command}", (), False, parameters, command
        )
        _write_output(document, options, command, 0)
        return 0
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
    _reject_active_prepared_plan(parser, workspace)
    run_directory = workspace / ".poly" / "runs" / snapshot.plan.id
    run_directory.mkdir(parents=True, exist_ok=True)
    streamed = options.format == "text"
    renderer = (
        SerializedRunRenderer(
            sys.stdout,
            snapshot.plan.actions,
            options.verbosity,
            _color_enabled(options),
            force_flow=options.flow,
        )
        if streamed
        else None
    )
    if streamed:
        assert renderer is not None
        renderer.start(planning_document(snapshot), command)
    try:
        result = Executor(
            _controller_runner(registry, options.controller),
            renderer.handle if renderer else None,
        ).execute(snapshot.plan, ExecutionContext(workspace, run_directory))
    except BaseException:
        if renderer is not None:
            renderer.abort()
        raise
    document = run_document(snapshot, result)
    _save_run_if_initialized(workspace, snapshot.plan.id, document)
    exit_code = 0 if result.status in {RunStatus.SUCCEEDED, RunStatus.EMPTY} else 1
    if streamed:
        assert renderer is not None
        renderer.finish(document, exit_code)
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
    if options.prepare:
        parser.error(
            "root repository bootstrap cannot be prepared because its recursive hydration "
            "cannot be frozen before the root repository is cloned"
        )
    containing_plan = _nearest_prepared_plan_root(target)
    _reject_active_prepared_plan(parser, containing_plan or _nearest_workspace(target) or parent)
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


def _append_prepared_command(
    parser: argparse.ArgumentParser,
    workspace: Path,
    verb: str,
    selected_node_ids: tuple[str, ...],
    select_all: bool,
    parameters: dict[str, str],
    command: str,
) -> ReportDocument:
    store = StateStore(workspace)
    previous = None
    if (store.state_directory / "plan.json").is_file():
        try:
            previous = store.load_prepared_plan()
        except StateError as error:
            parser.error(str(error))
    try:
        document = deferred_document(
            workspace, verb, selected_node_ids, select_all, parameters, command, previous
        )
    except PreparedPlanError as error:
        parser.error(str(error))
    store.save_prepared_plan(document)
    return document


def _reject_active_prepared_plan(parser: argparse.ArgumentParser, workspace: Path) -> None:
    if (workspace / ".poly" / "state" / "plan.json").is_file():
        parser.error("a prepared plan is active; use 'poly exec' or 'poly plan clean'")


def _nearest_prepared_plan_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".poly" / "state" / "plan.json").is_file():
            return candidate
    return None


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
    parser.add_argument(
        "--flow",
        action="store_true",
        help="use append-only execution output instead of live terminal rendering",
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
    capabilities = TerminalCapabilities.detect(sys.stdout)
    sys.stdout.write(
        render_cli(
            document,
            command,
            verbosity=options.verbosity,
            color=_color_enabled(options),
            exit_code=exit_code,
            width=capabilities.width,
            hyperlinks=capabilities.hyperlinks,
        )
    )


def _write_report_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _report_media_type(format_name: str) -> str:
    return {
        "json": "application/json",
        "yaml": "application/yaml",
        "xml": "application/xml",
        "text": "text/plain",
    }[format_name]


def _color_enabled(options: argparse.Namespace) -> bool:
    return options.color == "always" or (
        options.color == "auto" and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    )


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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", dest="plan_only")
    mode.add_argument("--prepare", action="store_true")
    parser.add_argument("--controller", default="local")
    _planning_options(parser)


def _selection_values(values: list[str]) -> tuple[str, ...]:
    selected = {
        node_id.strip() for value in values for node_id in value.split(",") if node_id.strip()
    }
    return tuple(sorted(selected))


def _selection(values: list[str], nodes: tuple[Node, ...]) -> tuple[str, ...]:
    if not values:
        return tuple(node.id for node in nodes)
    return _selection_values(values)


def _parameters(values: list[str]) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for value in values:
        key, separator, parameter = value.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid --parameter {value!r}; expected KEY=VALUE")
        parameters[key.strip()] = parameter
    return parameters


def _command_parameters(options: argparse.Namespace, registry: DriverRegistry) -> dict[str, str]:
    parameters = _parameters(options.parameter)
    if options.command == "init":
        parameters["poly.name"] = options.name or options.workspace.resolve().name
    elif options.command == "add":
        facade = next(
            item for item in registry.command_facades("add") if item.name == options.facade
        )
        values = {
            argument.name: (
                tuple(getattr(options, argument.name))
                if argument.repeatable
                else getattr(options, argument.name, None)
            )
            for argument in facade.arguments
        }
        parameters = facade.translate(
            FacadeRequest(options.workspace.resolve(), values, parameters)
        )
    elif options.command == "remove":
        parameters["poly.node.id"] = options.node_id
    elif options.command == "lock" and options.from_workspace:
        parameters["poly.lock.from-workspace"] = "true"
    elif options.command == "hydrate":
        depth = getattr(options, "depth", None)
        if depth:
            try:
                parameters["poly.source.depth"] = str(_positive_depth(depth))
            except ValueError as error:
                raise ValueError(str(error)) from error
        if getattr(options, "unshallow", False):
            parameters["poly.source.unshallow"] = "true"
    return parameters


def _empty_prepared_document(workspace: Path, state: str) -> ReportDocument:
    return {
        "schema": "poly.report/v1",
        "kind": "prepared-plan",
        "workspace": str(workspace),
        "available_verbs": [],
        "inventory": {"nodes": []},
        "diagnostics": [],
        "request": {"verb": "prepared", "selected_node_ids": [], "parameters": {}},
        "plan": {
            "id": "none",
            "verb": "prepared",
            "status": "empty",
            "selected_node_ids": [],
            "initial_constraints": [],
            "planned_actions": [],
            "ready_action_ids": [],
            "diagnostics": [],
        },
        "prepared": {"state": state, "commands": []},
    }


def _document_for_verb(document: ReportDocument, verb: str) -> ReportDocument:
    view = dict(document)
    view["request"] = {"verb": verb, "selected_node_ids": [], "parameters": {}}
    return view


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
