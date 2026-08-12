"""Maven structure inspection and reactor-aware finite planning."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from poly.driver import (
    DRIVER_API_VERSION,
    DriverCapability,
    DriverManifest,
    DriverRegistration,
    InspectionContext,
    InspectionDiagnostic,
    InspectionResult,
)
from poly.model import (
    ActionClaim,
    ActionSpec,
    Constraint,
    DriverProposal,
    Metadata,
    Node,
    NodeRelation,
    PlanningRequest,
    RejectedCandidate,
)

MAVEN_DRIVER_NAME = "poly.driver.maven"
RUN_REPOSITORY = "${POLY_RUN_DIRECTORY}/maven-repository"
_SKIPPED_DIRECTORIES = {".git", ".poly", ".venv", "target", "node_modules"}
_PROPERTY = re.compile(r"\$\{([^}]+)}")
_ORDERING_RELATIONS = {
    "maven/dependency",
    "maven/parent",
    "maven/plugin",
    "maven/extension",
}
_PHASES = {
    "build": "package",
    "test": "test",
    "package": "package",
    "verify": "verify",
    "install": "install",
    "clean": "clean",
}


@dataclass(frozen=True, slots=True)
class _Reference:
    kind: str
    group_id: str | None
    artifact_id: str
    version: str | None


@dataclass(frozen=True, slots=True)
class _RawPom:
    path: Path
    group_id: str | None
    artifact_id: str
    version: str | None
    packaging: str
    parent_group_id: str | None
    parent_artifact_id: str | None
    parent_version: str | None
    parent_relative_path: str | None
    modules: tuple[str, ...]
    properties: dict[str, str]
    references: tuple[_Reference, ...]


@dataclass(frozen=True, slots=True)
class _EffectivePom:
    raw: _RawPom
    group_id: str | None
    artifact_id: str
    version: str | None
    packaging: str
    properties: dict[str, str]
    parent_path: Path | None


@dataclass(frozen=True, slots=True)
class MavenInspectionProvider:
    name: str = MAVEN_DRIVER_NAME

    def inspect(self, context: InspectionContext) -> InspectionResult:
        diagnostics: list[InspectionDiagnostic] = []
        raw_by_path: dict[Path, _RawPom] = {}
        for path in _discover_poms(context.workspace):
            try:
                raw_by_path[path] = _parse_pom(path)
            except (OSError, ET.ParseError, MavenModelError) as error:
                diagnostics.append(
                    InspectionDiagnostic(
                        "maven.pom.invalid",
                        str(error),
                        _relative(context.workspace, path),
                    )
                )

        effective: dict[Path, _EffectivePom] = {}
        for path in sorted(raw_by_path):
            try:
                _effective_pom(path, raw_by_path, effective, ())
            except MavenModelError as error:
                diagnostics.append(
                    InspectionDiagnostic(
                        "maven.model.unresolved",
                        str(error),
                        _relative(context.workspace, path),
                    )
                )

        id_by_path = {path: _node_id(context.workspace, path.parent) for path in effective}
        coordinate_index: defaultdict[tuple[str, str], list[Path]] = defaultdict(list)
        for path, model in effective.items():
            if model.group_id is not None:
                coordinate_index[(model.group_id, model.artifact_id)].append(path)

        relations: defaultdict[Path, set[NodeRelation]] = defaultdict(set)
        aggregators: set[Path] = set()
        for path, model in effective.items():
            if model.parent_path in effective:
                relations[path].add(NodeRelation("maven/parent", id_by_path[model.parent_path]))
            for module in model.raw.modules:
                module_pom = _module_pom(path.parent, module)
                if module_pom not in effective:
                    diagnostics.append(
                        InspectionDiagnostic(
                            "maven.module.missing",
                            f"declared module {module!r} has no inspected pom.xml",
                            _relative(context.workspace, path),
                        )
                    )
                    continue
                aggregators.add(path)
                relations[module_pom].add(NodeRelation("maven/member-of", id_by_path[path]))
            for reference in model.raw.references:
                group_id = _resolve(reference.group_id, model.properties)
                artifact_id = _resolve(reference.artifact_id, model.properties)
                if group_id is None or artifact_id is None:
                    continue
                matches = coordinate_index.get((group_id, artifact_id), [])
                if len(matches) == 1 and matches[0] != path:
                    relations[path].add(NodeRelation(reference.kind, id_by_path[matches[0]]))
                elif len(matches) > 1:
                    diagnostics.append(
                        InspectionDiagnostic(
                            "maven.coordinate.ambiguous",
                            f"multiple local projects use {group_id}:{artifact_id}",
                            _relative(context.workspace, path),
                        )
                    )

        nodes = tuple(
            _node(context.workspace, path, model, relations[path], path in aggregators)
            for path, model in sorted(effective.items())
        )
        return InspectionResult(self.name, nodes, tuple(diagnostics))


class MavenModelError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MavenPlanningProvider:
    name: str = MAVEN_DRIVER_NAME
    verbs: frozenset[str] = frozenset(_PHASES)

    def propose(self, request: PlanningRequest) -> DriverProposal:
        selected: list[Node] = []
        rejected: list[RejectedCandidate] = []
        for node in request.inventory.select(request.selected_node_ids):
            if "maven/project" not in node.natures:
                rejected.append(
                    RejectedCandidate(
                        self.name,
                        "maven/reactor",
                        "node is not a Maven project",
                        (node.id,),
                        ("nature:maven/project",),
                    )
                )
            else:
                selected.append(node)
        if not selected:
            return DriverProposal(self.name, rejected=tuple(rejected))

        policy = request.parameters.get("maven.dependency-policy", "workspace")
        if policy not in {"workspace", "repository", "exact"}:
            rejected.append(
                RejectedCandidate(
                    self.name,
                    "maven/reactor",
                    f"unsupported maven.dependency-policy: {policy}",
                    tuple(node.id for node in selected),
                )
            )
            return DriverProposal(self.name, rejected=tuple(rejected))

        nodes = {node.id: node for node in request.inventory.nodes}
        try:
            reactors = {node.id: _reactor_for(node.id, nodes) for node in selected}
        except MavenPlanningError as error:
            rejected.append(
                RejectedCandidate(
                    self.name,
                    "maven/reactor",
                    str(error),
                    tuple(node.id for node in selected),
                )
            )
            return DriverProposal(self.name, rejected=tuple(rejected))

        requested_by_reactor: defaultdict[str, set[str]] = defaultdict(set)
        seeds_by_reactor: defaultdict[str, set[str]] = defaultdict(set)
        coverage_by_reactor: defaultdict[str, set[str]] = defaultdict(set)
        action_dependencies: defaultdict[str, set[str]] = defaultdict(set)
        exact_requirements: defaultdict[str, set[Constraint]] = defaultdict(set)
        for node in selected:
            reactor = reactors[node.id]
            requested_by_reactor[reactor].add(node.id)
            seeds_by_reactor[reactor].add(node.id)

        dependency_graph = {
            node.id: tuple(
                relation.target
                for relation in node.relations
                if relation.kind in _ORDERING_RELATIONS
                and (
                    relation.kind != "maven/parent"
                    or _reactor_for(relation.target, nodes) == _reactor_for(node.id, nodes)
                )
            )
            for node in nodes.values()
        }
        if request.verb != "clean":
            _close_dependencies(
                nodes,
                dependency_graph,
                seeds_by_reactor,
                coverage_by_reactor,
                action_dependencies,
                exact_requirements,
                policy,
            )
        else:
            for clean_reactor_id, seeds in seeds_by_reactor.items():
                coverage_by_reactor[clean_reactor_id].update(seeds)

        upstream_reactors = {
            dependency
            for dependencies in action_dependencies.values()
            for dependency in dependencies
        }
        use_run_repository = policy == "workspace" and bool(action_dependencies)
        actions: list[ActionSpec] = []
        for reactor_id in sorted(seeds_by_reactor):
            reactor_node = nodes[reactor_id]
            phase = _PHASES[request.verb]
            if reactor_id in upstream_reactors and phase != "clean":
                phase = "install"
            command = _command(
                reactor_node,
                tuple(nodes[node_id] for node_id in sorted(seeds_by_reactor[reactor_id])),
                phase,
                use_run_repository,
                request.verb != "clean",
            )
            requires = {
                _installed_constraint(dependency) for dependency in action_dependencies[reactor_id]
            }
            requires.update(exact_requirements[reactor_id])
            produces = (
                frozenset((_installed_constraint(reactor_id),))
                if reactor_id in upstream_reactors
                else frozenset()
            )
            actions.append(
                ActionSpec(
                    id=f"maven.{request.verb}:{reactor_id}",
                    driver=self.name,
                    verb=request.verb,
                    operation="maven/reactor",
                    node_ids=tuple(sorted(coverage_by_reactor[reactor_id])),
                    requested_node_ids=tuple(sorted(requested_by_reactor[reactor_id])),
                    requires=frozenset(requires),
                    produces=produces,
                    claims=frozenset(
                        (ActionClaim(f"maven/{request.verb}", f"reactor:{reactor_id}"),)
                    ),
                    command=command,
                )
            )
        return DriverProposal(self.name, tuple(actions), tuple(rejected))


class MavenPlanningError(ValueError):
    pass


def maven_driver() -> DriverRegistration:
    manifest = DriverManifest(
        MAVEN_DRIVER_NAME,
        "0.1.0",
        DRIVER_API_VERSION,
        frozenset((DriverCapability.INSPECT, DriverCapability.PLAN)),
        "Maven model inspection and reactor-aware action planning",
    )
    return DriverRegistration(
        manifest,
        inspectors=(MavenInspectionProvider(),),
        planners=(MavenPlanningProvider(),),
    )


def _discover_poms(workspace: Path) -> tuple[Path, ...]:
    poms: list[Path] = []
    for current, directory_names, file_names in os.walk(workspace):
        directory_names[:] = sorted(
            name for name in directory_names if name not in _SKIPPED_DIRECTORIES
        )
        if "pom.xml" in file_names:
            poms.append((Path(current) / "pom.xml").resolve())
    return tuple(sorted(poms))


def _parse_pom(path: Path) -> _RawPom:
    root = ET.parse(path).getroot()
    artifact_id = _text(root, "artifactId")
    if artifact_id is None:
        raise MavenModelError(f"{path} has no artifactId")
    parent = _child(root, "parent")
    relative_element = _child(parent, "relativePath") if parent is not None else None
    if parent is None:
        parent_relative_path = None
    elif relative_element is None:
        parent_relative_path = "../pom.xml"
    else:
        parent_relative_path = (relative_element.text or "").strip() or None
    properties_element = _child(root, "properties")
    properties = {
        _local_name(element.tag): (element.text or "").strip()
        for element in (list(properties_element) if properties_element is not None else ())
    }
    modules_element = _child(root, "modules")
    modules = tuple(
        text
        for element in (list(modules_element) if modules_element is not None else ())
        if (text := (element.text or "").strip())
    )
    references: list[_Reference] = []
    dependencies = _child(root, "dependencies")
    references.extend(_references(dependencies, "dependency", "maven/dependency"))
    dependency_management = _child(root, "dependencyManagement")
    managed_dependencies = (
        _child(dependency_management, "dependencies") if dependency_management is not None else None
    )
    for reference in _references(managed_dependencies, "dependency", "maven/bom"):
        references.append(reference)
    build = _child(root, "build")
    plugins = _child(build, "plugins") if build is not None else None
    references.extend(_references(plugins, "plugin", "maven/plugin", "org.apache.maven.plugins"))
    extensions = _child(build, "extensions") if build is not None else None
    references.extend(_references(extensions, "extension", "maven/extension"))
    return _RawPom(
        path=path,
        group_id=_text(root, "groupId"),
        artifact_id=artifact_id,
        version=_text(root, "version"),
        packaging=_text(root, "packaging") or "jar",
        parent_group_id=_text(parent, "groupId") if parent is not None else None,
        parent_artifact_id=_text(parent, "artifactId") if parent is not None else None,
        parent_version=_text(parent, "version") if parent is not None else None,
        parent_relative_path=parent_relative_path,
        modules=modules,
        properties=properties,
        references=tuple(references),
    )


def _references(
    container: ET.Element | None,
    element_name: str,
    kind: str,
    default_group: str | None = None,
) -> tuple[_Reference, ...]:
    if container is None:
        return ()
    result: list[_Reference] = []
    for element in list(container):
        if _local_name(element.tag) != element_name:
            continue
        artifact_id = _text(element, "artifactId")
        if artifact_id is None:
            continue
        result.append(
            _Reference(
                kind,
                _text(element, "groupId") or default_group,
                artifact_id,
                _text(element, "version"),
            )
        )
    return tuple(result)


def _effective_pom(
    path: Path,
    raw_by_path: dict[Path, _RawPom],
    cache: dict[Path, _EffectivePom],
    stack: tuple[Path, ...],
) -> _EffectivePom:
    if path in cache:
        return cache[path]
    if path in stack:
        raise MavenModelError(f"local parent cycle: {path}")
    raw = raw_by_path[path]
    parent_path = _parent_path(raw)
    parent = (
        _effective_pom(parent_path, raw_by_path, cache, (*stack, path))
        if parent_path in raw_by_path
        else None
    )
    properties = dict(parent.properties if parent else {})
    properties.update(raw.properties)
    group_id = raw.group_id or (parent.group_id if parent else raw.parent_group_id)
    version = raw.version or (parent.version if parent else raw.parent_version)
    builtins = {
        "project.artifactId": raw.artifact_id,
        "pom.artifactId": raw.artifact_id,
    }
    if group_id is not None:
        builtins.update({"project.groupId": group_id, "pom.groupId": group_id})
    if version is not None:
        builtins.update({"project.version": version, "pom.version": version})
    properties.update(builtins)
    group_id = _resolve(group_id, properties)
    artifact_id = _resolve(raw.artifact_id, properties)
    version = _resolve(version, properties)
    packaging = _resolve(raw.packaging, properties) or "jar"
    if artifact_id is None:
        raise MavenModelError(f"unable to resolve artifactId for {path}")
    properties.update(
        {
            "project.artifactId": artifact_id,
            "pom.artifactId": artifact_id,
            **({"project.groupId": group_id, "pom.groupId": group_id} if group_id else {}),
            **({"project.version": version, "pom.version": version} if version else {}),
        }
    )
    model = _EffectivePom(raw, group_id, artifact_id, version, packaging, properties, parent_path)
    cache[path] = model
    return model


def _parent_path(raw: _RawPom) -> Path | None:
    if raw.parent_relative_path is None:
        return None
    candidate = (raw.path.parent / raw.parent_relative_path).resolve()
    return candidate / "pom.xml" if candidate.is_dir() else candidate


def _resolve(value: str | None, properties: dict[str, str]) -> str | None:
    if value is None:
        return None
    resolved = value
    for _ in range(10):
        changed = _PROPERTY.sub(
            lambda match: properties.get(match.group(1), match.group(0)), resolved
        )
        if changed == resolved:
            break
        resolved = changed
    return resolved


def _node(
    workspace: Path,
    path: Path,
    model: _EffectivePom,
    relations: set[NodeRelation],
    aggregator: bool,
) -> Node:
    directory = path.parent
    natures = {"maven/project", f"maven/packaging/{model.packaging}"}
    if aggregator:
        natures.add("maven/aggregator")
    if any(relation.kind == "maven/member-of" for relation in relations):
        natures.add("maven/module")
    metadata: Metadata = {
        "maven.groupId": model.group_id,
        "maven.artifactId": model.artifact_id,
        "maven.version": model.version,
        "maven.packaging": model.packaging,
        "maven.pom": _relative(workspace, path),
        "maven.coordinates": ":".join(
            part for part in (model.group_id, model.artifact_id, model.version) if part
        ),
        "maven.wrapper": (directory / "mvnw").is_file(),
    }
    return Node(
        _node_id(workspace, directory),
        _relative(workspace, directory),
        tuple(natures),
        metadata,
        tuple(relations),
    )


def _reactor_for(node_id: str, nodes: dict[str, Node]) -> str:
    frontier = [node_id]
    roots: set[str] = set()
    visited: set[str] = set()
    while frontier:
        current = frontier.pop()
        if current in visited:
            continue
        visited.add(current)
        parents = [
            relation.target
            for relation in nodes[current].relations
            if relation.kind == "maven/member-of"
        ]
        if not parents:
            roots.add(current)
        else:
            frontier.extend(parents)
    if len(roots) != 1:
        raise MavenPlanningError(
            f"node {node_id!r} belongs to multiple top-level reactors: {sorted(roots)!r}"
        )
    return next(iter(roots))


def _close_dependencies(
    nodes: dict[str, Node],
    dependency_graph: dict[str, tuple[str, ...]],
    seeds_by_reactor: defaultdict[str, set[str]],
    coverage_by_reactor: defaultdict[str, set[str]],
    action_dependencies: defaultdict[str, set[str]],
    exact_requirements: defaultdict[str, set[Constraint]],
    policy: str,
) -> None:
    pending = [(seed, reactor) for reactor, seeds in seeds_by_reactor.items() for seed in seeds]
    visited: set[tuple[str, str]] = set()
    while pending:
        node_id, action_reactor = pending.pop()
        if (node_id, action_reactor) in visited:
            continue
        visited.add((node_id, action_reactor))
        coverage_by_reactor[action_reactor].add(node_id)
        for dependency_id in dependency_graph[node_id]:
            dependency_reactor = _reactor_for(dependency_id, nodes)
            if dependency_reactor == action_reactor:
                pending.append((dependency_id, action_reactor))
            elif policy == "workspace":
                action_dependencies[action_reactor].add(dependency_reactor)
                seeds_by_reactor[dependency_reactor].add(dependency_id)
                pending.append((dependency_id, dependency_reactor))
            elif policy == "exact":
                exact_requirements[action_reactor].add(
                    Constraint(f"maven/repository/{_coordinate(nodes[dependency_id])}/available")
                )


def _command(
    reactor: Node,
    seeds: tuple[Node, ...],
    phase: str,
    use_run_repository: bool,
    also_make: bool,
) -> tuple[str, ...]:
    wrapper = reactor.metadata.get("maven.wrapper") is True
    executable = (
        f"{reactor.path}/mvnw"
        if wrapper and reactor.path != "."
        else "./mvnw"
        if wrapper
        else "mvn"
    )
    pom = str(reactor.metadata["maven.pom"])
    selectors = ",".join(sorted(_selector(node) for node in seeds))
    arguments = [executable, "-f", pom, "-pl", selectors]
    if also_make:
        arguments.append("-am")
    if use_run_repository:
        arguments.append(f"-Dmaven.repo.local={RUN_REPOSITORY}")
    arguments.append(phase)
    return tuple(arguments)


def _selector(node: Node) -> str:
    group_id = node.metadata.get("maven.groupId")
    artifact_id = node.metadata["maven.artifactId"]
    return f"{group_id}:{artifact_id}" if group_id else f":{artifact_id}"


def _coordinate(node: Node) -> str:
    return str(node.metadata["maven.coordinates"])


def _installed_constraint(reactor_id: str) -> Constraint:
    return Constraint(f"maven/reactor/{reactor_id}/installed")


def _module_pom(base: Path, module: str) -> Path:
    candidate = (base / module).resolve()
    return candidate if candidate.name.endswith(".xml") else candidate / "pom.xml"


def _child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    return next((child for child in list(element) if _local_name(child.tag) == name), None)


def _text(element: ET.Element | None, name: str) -> str | None:
    child = _child(element, name)
    text = (child.text or "").strip() if child is not None else ""
    return text or None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _relative(workspace: Path, path: Path) -> str:
    relative = path.relative_to(workspace)
    return relative.as_posix() if relative.parts else "."


def _node_id(workspace: Path, directory: Path) -> str:
    return f"maven:{_relative(workspace, directory)}"
