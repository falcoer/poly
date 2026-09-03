from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected source block not found in {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# CLI: preparation must branch before any workspace inspection/planning.
replace(
    "src/poly/cli.py",
    "from poly.prepared import PreparedPlanError, prepare_document, require_current",
    "from poly.prepared import (\n"
    "    PreparedPlanError,\n"
    "    deferred_document,\n"
    "    is_deferred_document,\n"
    "    require_current,\n"
    "    resolve_deferred_document,\n"
    ")",
)
replace(
    "src/poly/cli.py",
    "    if not workspace.is_dir():\n"
    "        parser.error(f\"workspace does not exist or is not a directory: {workspace}\")\n"
    "    if options.command == \"report\":",
    "    if not workspace.is_dir():\n"
    "        parser.error(f\"workspace does not exist or is not a directory: {workspace}\")\n"
    "    if getattr(options, \"prepare\", False):\n"
    "        verb = options.verb if options.command == \"run\" else options.command\n"
    "        _validate_verbs(parser, (verb,), _driver_verbs(registry))\n"
    "        try:\n"
    "            parameters = _command_parameters(options, registry)\n"
    "        except ValueError as error:\n"
    "            parser.error(str(error))\n"
    "        document = _append_prepared_command(\n"
    "            parser, workspace, verb, _selection_values(options.select), not options.select,\n"
    "            parameters, command\n"
    "        )\n"
    "        _write_output(document, options, command, 0)\n"
    "        return 0\n"
    "    if options.command == \"report\":",
)
replace(
    "src/poly/cli.py",
    "    if options.command == \"exec\":\n"
    "        store = StateStore(workspace)\n"
    "        try:\n"
    "            prepared = store.load_prepared_plan()\n"
    "            plan = require_current(prepared, workspace)\n"
    "        except (StateError, PreparedPlanError) as error:\n"
    "            parser.error(str(error))",
    "    if options.command == \"exec\":\n"
    "        store = StateStore(workspace)\n"
    "        try:\n"
    "            prepared = store.load_prepared_plan()\n"
    "            if is_deferred_document(prepared):\n"
    "                inspection = inspect_workspace(registry, workspace)\n"
    "                resolved, plan = resolve_deferred_document(registry, inspection, prepared)\n"
    "                if plan.status.value not in {\"executable\", \"empty\"}:\n"
    "                    failed = dict(prepared)\n"
    "                    failed[\"resolution\"] = resolved.get(\"plan\", {})\n"
    "                    store.save_prepared_plan(failed)\n"
    "                    raise PreparedPlanError(\n"
    "                        f\"prepared commands resolve to a {plan.status.value} plan; \"\n"
    "                        \"inspect 'poly plan' diagnostics before retrying\"\n"
    "                    )\n"
    "                store.save_prepared_plan(resolved)\n"
    "                prepared = resolved\n"
    "            else:\n"
    "                plan = require_current(prepared, workspace)\n"
    "        except (StateError, PreparedPlanError, WorkspaceError) as error:\n"
    "            parser.error(str(error))",
)
replace(
    "src/poly/cli.py",
    "            elif getattr(options, \"prepare\", False):\n"
    "                document, exit_code = _append_prepared_plan(parser, workspace, snapshot, command)\n"
    "            else:",
    "            elif getattr(options, \"prepare\", False):\n"
    "                raise AssertionError(\"preparation must be handled before inspection\")\n"
    "            else:",
)
replace(
    "src/poly/cli.py",
    "    try:\n"
    "        inspection = inspect_workspace(registry, workspace)\n"
    "        node_id, natures = _nature_target(\n"
    "            options.values, inspection.inventory.nodes, workspace, start\n"
    "        )\n"
    "    except WorkspaceError as error:\n"
    "        parser.error(str(error))",
    "    if options.prepare:\n"
    "        if not options.values:\n"
    "            parser.error(\"at least one nature is required\")\n"
    "        parameters = {\n"
    "            \"poly.prepare.nature.values\": \"\\x1f\".join(options.values),\n"
    "            \"poly.prepare.nature.cwd\": str(start),\n"
    "        }\n"
    "        document = _append_prepared_command(\n"
    "            parser, workspace, f\"nature-{options.nature_command}\", (), False, parameters, command\n"
    "        )\n"
    "        _write_output(document, options, command, 0)\n"
    "        return 0\n"
    "    try:\n"
    "        inspection = inspect_workspace(registry, workspace)\n"
    "        node_id, natures = _nature_target(\n"
    "            options.values, inspection.inventory.nodes, workspace, start\n"
    "        )\n"
    "    except WorkspaceError as error:\n"
    "        parser.error(str(error))",
)
replace(
    "src/poly/cli.py",
    "    if options.prepare:\n"
    "        document, exit_code = _append_prepared_plan(parser, workspace, snapshot, command)\n"
    "        _write_output(document, options, command, exit_code)\n"
    "        return exit_code\n",
    "",
)
replace(
    "src/poly/cli.py",
    "def _append_prepared_plan(\n"
    "    parser: argparse.ArgumentParser,\n"
    "    workspace: Path,\n"
    "    snapshot: PlanningSnapshot,\n"
    "    command: str,\n"
    ") -> tuple[ReportDocument, int]:\n"
    "    store = StateStore(workspace)\n"
    "    previous = None\n"
    "    if (store.state_directory / \"plan.json\").is_file():\n"
    "        try:\n"
    "            previous = store.load_prepared_plan()\n"
    "        except StateError as error:\n"
    "            parser.error(str(error))\n"
    "    try:\n"
    "        document = prepare_document(snapshot, command, previous)\n"
    "    except PreparedPlanError as error:\n"
    "        parser.error(str(error))\n"
    "    store.save_prepared_plan(document)\n"
    "    plan_value = document.get(\"plan\")\n"
    "    status = plan_value.get(\"status\") if isinstance(plan_value, dict) else \"blocked\"\n"
    "    return document, 0 if status in {\"executable\", \"empty\"} else 1\n",
    "def _append_prepared_command(\n"
    "    parser: argparse.ArgumentParser,\n"
    "    workspace: Path,\n"
    "    verb: str,\n"
    "    selected_node_ids: tuple[str, ...],\n"
    "    select_all: bool,\n"
    "    parameters: dict[str, str],\n"
    "    command: str,\n"
    ") -> ReportDocument:\n"
    "    store = StateStore(workspace)\n"
    "    previous = None\n"
    "    if (store.state_directory / \"plan.json\").is_file():\n"
    "        try:\n"
    "            previous = store.load_prepared_plan()\n"
    "        except StateError as error:\n"
    "            parser.error(str(error))\n"
    "    try:\n"
    "        document = deferred_document(\n"
    "            workspace, verb, selected_node_ids, select_all, parameters, command, previous\n"
    "        )\n"
    "    except PreparedPlanError as error:\n"
    "        parser.error(str(error))\n"
    "    store.save_prepared_plan(document)\n"
    "    return document\n",
)
replace(
    "src/poly/cli.py",
    "def _selection(values: list[str], nodes: tuple[Node, ...]) -> tuple[str, ...]:\n"
    "    if not values:\n"
    "        return tuple(node.id for node in nodes)\n"
    "    selected = {\n"
    "        node_id.strip() for value in values for node_id in value.split(\",\") if node_id.strip()\n"
    "    }\n"
    "    return tuple(sorted(selected))\n",
    "def _selection_values(values: list[str]) -> tuple[str, ...]:\n"
    "    selected = {\n"
    "        node_id.strip() for value in values for node_id in value.split(\",\") if node_id.strip()\n"
    "    }\n"
    "    return tuple(sorted(selected))\n\n\n"
    "def _selection(values: list[str], nodes: tuple[Node, ...]) -> tuple[str, ...]:\n"
    "    if not values:\n"
    "        return tuple(node.id for node in nodes)\n"
    "    return _selection_values(values)\n",
)

# Deferred resolver: planned journals only; resolved graphs are immutable retries.
replace(
    "src/poly/prepared.py",
    "    return isinstance(prepared, dict) and prepared.get(\"journal_version\") == COMMAND_JOURNAL_VERSION",
    "    return (\n"
    "        isinstance(prepared, dict)\n"
    "        and prepared.get(\"journal_version\") == COMMAND_JOURNAL_VERSION\n"
    "        and prepared.get(\"state\") == \"planned\"\n"
    "    )",
)
replace(
    "src/poly/prepared.py",
    "        parameters_value = command.get(\"parameters\", {})\n"
    "        if not isinstance(parameters_value, dict) or not all(\n"
    "            isinstance(key, str) and isinstance(value, str)\n"
    "            for key, value in parameters_value.items()\n"
    "        ):\n"
    "            raise PreparedPlanError(\"prepared command parameters must contain strings\")\n"
    "        snapshot = prepare_planning(registry, inspection, verb, selected, dict(parameters_value))",
    "        parameters_value = command.get(\"parameters\", {})\n"
    "        if not isinstance(parameters_value, dict) or not all(\n"
    "            isinstance(key, str) and isinstance(value, str)\n"
    "            for key, value in parameters_value.items()\n"
    "        ):\n"
    "            raise PreparedPlanError(\"prepared command parameters must contain strings\")\n"
    "        parameters = dict(parameters_value)\n"
    "        if verb in {\"nature-add\", \"nature-remove\"} and \"poly.prepare.nature.values\" in parameters:\n"
    "            values = parameters.pop(\"poly.prepare.nature.values\").split(\"\\x1f\")\n"
    "            current = Path(parameters.pop(\"poly.prepare.nature.cwd\"))\n"
    "            selected, natures = _resolve_nature_target(values, inspection, current)\n"
    "            parameters[\"poly.node.natures\"] = \",\".join(natures)\n"
    "        snapshot = prepare_planning(registry, inspection, verb, selected, parameters)",
)
# Insert nature resolver before legacy prepare_document.
replace(
    "src/poly/prepared.py",
    "\ndef prepare_document(\n",
    "\ndef _resolve_nature_target(\n"
    "    values: list[str], inspection: InspectionSnapshot, current: Path\n"
    ") -> tuple[tuple[str, ...], tuple[str, ...]]:\n"
    "    if not values:\n"
    "        raise PreparedPlanError(\"at least one nature is required\")\n"
    "    nodes = inspection.inventory.nodes\n"
    "    node_ids = {node.id for node in nodes}\n"
    "    if values[0] == \".\":\n"
    "        node_id = _current_node(nodes, inspection.workspace, current)\n"
    "        natures = values[1:]\n"
    "    elif values[0] in node_ids and len(values) > 1:\n"
    "        node_id = values[0]\n"
    "        natures = values[1:]\n"
    "    else:\n"
    "        node_id = _current_node(nodes, inspection.workspace, current)\n"
    "        natures = values\n"
    "    normalized = tuple(sorted({nature.strip() for nature in natures if nature.strip()}))\n"
    "    if not normalized:\n"
    "        raise PreparedPlanError(\"at least one nature is required\")\n"
    "    return (node_id,), normalized\n\n\n"
    "def _current_node(nodes: tuple[object, ...], workspace: Path, current: Path) -> str:\n"
    "    candidates: list[tuple[int, int, str]] = []\n"
    "    typed = [node for node in nodes if hasattr(node, \"id\") and hasattr(node, \"path\")]\n"
    "    parents = {\n"
    "        node.id: node.metadata.get(\"poly.parent\")\n"
    "        for node in typed\n"
    "        if isinstance(node.metadata.get(\"poly.parent\"), str)\n"
    "    }\n"
    "    for node in typed:\n"
    "        path = (workspace / node.path).resolve()\n"
    "        if path != current and path not in current.parents:\n"
    "            continue\n"
    "        depth = 0\n"
    "        parent = parents.get(node.id)\n"
    "        while isinstance(parent, str):\n"
    "            depth += 1\n"
    "            parent = parents.get(parent)\n"
    "        candidates.append((len(path.parts), depth, node.id))\n"
    "    if not candidates:\n"
    "        raise PreparedPlanError(f\"current directory does not belong to a declared node: {current}\")\n"
    "    return max(candidates)[2]\n\n\n"
    "def prepare_document(\n",
)

# Reporting: explicit planned result, no action count/fingerprint/success wording.
replace(
    "src/poly/reporting.py",
    "    if verbosity < -1:\n        raise ValueError(\"verbosity must be -1 or greater\")",
    "    if verbosity < -1:\n        raise ValueError(\"verbosity must be -1 or greater\")\n"
    "    if _is_planned_command(document):\n"
    "        return _render_planned_cli(document, command, verbosity, color, width)",
)
replace(
    "src/poly/reporting.py",
    "def _command_heading(document: ReportDocument) -> str:\n",
    "def _is_planned_command(document: ReportDocument) -> bool:\n"
    "    prepared = document.get(\"prepared\")\n"
    "    request = document.get(\"request\")\n"
    "    return (\n"
    "        isinstance(prepared, dict)\n"
    "        and prepared.get(\"state\") == \"planned\"\n"
    "        and isinstance(request, dict)\n"
    "        and request.get(\"verb\") != \"plan\"\n"
    "    )\n\n\n"
    "def _render_planned_cli(\n"
    "    document: ReportDocument, command: str, verbosity: int, color: bool, width: int\n"
    ") -> str:\n"
    "    prepared = document.get(\"prepared\", {})\n"
    "    request = document.get(\"request\", {})\n"
    "    count = int(prepared.get(\"command_count\", 0)) if isinstance(prepared, dict) else 0\n"
    "    verb = str(request.get(\"verb\", \"command\")) if isinstance(request, dict) else \"command\"\n"
    "    noun = \"command\" if count == 1 else \"commands\"\n"
    "    separator = \"─\" * _usable_width(width)\n"
    "    lines = [separator, _command_heading(document)]\n"
    "    if verbosity >= 1:\n"
    "        lines.append(f\"{_SECTION_INDENT}COMMAND  {command}\")\n"
    "    if verbosity >= 0:\n"
    "        lines.extend([\n"
    "            f\"{_SECTION_INDENT}○ PLANNED  poly {verb}\",\n"
    "            f\"{_DETAIL_INDENT}{count} {noun} in current plan\",\n"
    "            f\"{_DETAIL_INDENT}Run `poly exec` when the plan is ready.\",\n"
    "        ])\n"
    "    lines.append(separator)\n"
    "    return \"\\n\".join(_styled(line, \"magenta\", color) for line in lines) + \"\\n\"\n\n\n"
    "def _command_heading(document: ReportDocument) -> str:\n",
)
replace(
    "src/poly/reporting.py",
    "    codes = {\"green\": \"32\", \"red\": \"31\", \"yellow\": \"33\", \"cyan\": \"36\", \"muted\": \"90\"}",
    "    codes = {\"green\": \"32\", \"red\": \"31\", \"yellow\": \"33\", \"cyan\": \"36\", \"magenta\": \"35\", \"muted\": \"90\"}",
)
# Poly plan lists normalized commands in authoring order.
replace(
    "src/poly/reporting.py",
    "    plan = document.get(\"plan\")\n    if isinstance(plan, dict):",
    "    prepared = document.get(\"prepared\")\n"
    "    if isinstance(prepared, dict) and prepared.get(\"journal_version\") == 2:\n"
    "        commands = prepared.get(\"commands\", [])\n"
    "        if isinstance(commands, list):\n"
    "            noun = \"command\" if len(commands) == 1 else \"commands\"\n"
    "            lines.append(\n"
    "                f\"{_SECTION_INDENT}{_styled(f'{len(commands)} {noun} in current plan', 'magenta', color)}\"\n"
    "            )\n"
    "            for index, item in enumerate(commands, 1):\n"
    "                if isinstance(item, dict):\n"
    "                    authored = item.get(\"command\") or f\"poly {item.get('verb', 'command')}\"\n"
    "                    lines.append(f\"{_DETAIL_INDENT}{index:>3}. {_safe_visible(str(authored))}\")\n"
    "        resolution = document.get(\"resolution\")\n"
    "        if isinstance(resolution, dict):\n"
    "            for diagnostic in resolution.get(\"diagnostics\", []):\n"
    "                if isinstance(diagnostic, dict):\n"
    "                    lines.append(\n"
    "                        f\"{_DETAIL_INDENT}{_styled(f'⚠ WARN     {diagnostic.get(\"message\")}', 'yellow', color)}\"\n"
    "                    )\n\n"
    "    plan = document.get(\"plan\")\n    if isinstance(plan, dict):",
)

print("0.12.3 transformation applied")
