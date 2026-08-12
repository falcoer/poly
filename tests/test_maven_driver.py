from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from poly.driver import InspectionContext
from poly.driver.testkit import (
    assert_inspection_side_effect_free,
    assert_manifest_compatible,
    assert_planning_deterministic,
)
from poly.drivers.maven import (
    RUN_REPOSITORY,
    MavenInspectionProvider,
    MavenPlanningProvider,
    maven_driver,
)
from poly.model import Inventory, Node, PlanningRequest, PlanStatus
from poly.planning import Planner


def _pom(
    directory: Path,
    artifact: str,
    *,
    packaging: str = "jar",
    parent: tuple[str, str, str, str] | None = None,
    modules: tuple[str, ...] = (),
    dependencies: tuple[tuple[str, str, str], ...] = (),
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    parent_xml = ""
    group = "<groupId>com.example</groupId>"
    version = "<version>1.0.0</version>"
    if parent:
        parent_group, parent_artifact, parent_version, relative = parent
        parent_xml = f"""
          <parent>
            <groupId>{parent_group}</groupId>
            <artifactId>{parent_artifact}</artifactId>
            <version>{parent_version}</version>
            <relativePath>{relative}</relativePath>
          </parent>
        """
        group = ""
        version = ""
    modules_xml = ""
    if modules:
        modules_xml = (
            "<modules>" + "".join(f"<module>{module}</module>" for module in modules) + "</modules>"
        ).lstrip()
    dependencies_xml = ""
    if dependencies:
        dependencies_xml = (
            "<dependencies>"
            + "".join(
                f"<dependency><groupId>{group_id}</groupId><artifactId>{artifact_id}</artifactId><version>{dependency_version}</version></dependency>"
                for group_id, artifact_id, dependency_version in dependencies
            )
            + "</dependencies>"
        )
    (directory / "pom.xml").write_text(
        dedent(
            f"""\
            <project xmlns="http://maven.apache.org/POM/4.0.0">
              <modelVersion>4.0.0</modelVersion>
              {parent_xml}
              {group}
              <artifactId>{artifact}</artifactId>
              {version}
              <packaging>{packaging}</packaging>
              {modules_xml}
              {dependencies_xml}
            </project>
            """
        )
    )


def _workspace(path: Path) -> None:
    platform = path / "platform"
    _pom(platform, "platform-parent", packaging="pom", modules=("common", "service-a"))
    parent = ("com.example", "platform-parent", "1.0.0", "../pom.xml")
    _pom(platform / "common", "common", parent=parent)
    _pom(
        platform / "service-a",
        "service-a",
        parent=parent,
        dependencies=(("com.example", "common", "1.0.0"),),
    )

    apps = path / "apps"
    _pom(apps, "apps-parent", packaging="pom", modules=("service-b",))
    _pom(
        apps / "service-b",
        "service-b",
        parent=("com.example", "apps-parent", "1.0.0", "../pom.xml"),
        dependencies=(("com.example", "service-a", "1.0.0"),),
    )


def _inventory(path: Path) -> Inventory:
    result = MavenInspectionProvider().inspect(InspectionContext(path))
    assert result.diagnostics == ()
    return Inventory(result.nodes)


def test_maven_driver_uses_public_sdk() -> None:
    registration = maven_driver()
    registration.validate()
    assert_manifest_compatible(registration.manifest)


def test_inspection_distinguishes_aggregation_inheritance_and_dependencies(
    tmp_path: Path,
) -> None:
    _workspace(tmp_path)

    result = MavenInspectionProvider().inspect(InspectionContext(tmp_path))
    nodes = {node.id: node for node in result.nodes}

    assert result.diagnostics == ()
    assert "maven/aggregator" in nodes["maven:platform"].natures
    assert "maven/module" in nodes["maven:platform/service-a"].natures
    service_a_relations = {
        (relation.kind, relation.target) for relation in nodes["maven:platform/service-a"].relations
    }
    assert ("maven/member-of", "maven:platform") in service_a_relations
    assert ("maven/parent", "maven:platform") in service_a_relations
    assert ("maven/dependency", "maven:platform/common") in service_a_relations
    assert nodes["maven:apps/service-b"].metadata["maven.groupId"] == "com.example"


def test_parent_inheritance_does_not_imply_aggregation(tmp_path: Path) -> None:
    _pom(tmp_path, "parent", packaging="pom")
    child = tmp_path / "detached-child"
    _pom(
        child,
        "child",
        parent=("com.example", "parent", "1.0.0", "../pom.xml"),
    )

    nodes = {
        node.id: node
        for node in MavenInspectionProvider().inspect(InspectionContext(tmp_path)).nodes
    }

    relations = {relation.kind for relation in nodes["maven:detached-child"].relations}
    assert "maven/parent" in relations
    assert "maven/member-of" not in relations
    request = PlanningRequest("verify", Inventory(tuple(nodes.values())), ("maven:detached-child",))
    action = MavenPlanningProvider().propose(request).actions[0]
    assert action.id == "maven.verify:maven:detached-child"


def test_workspace_policy_orders_reactors_and_materializes_upstream(tmp_path: Path) -> None:
    _workspace(tmp_path)
    inventory = _inventory(tmp_path)
    request = PlanningRequest("verify", inventory, ("maven:apps/service-b",))
    provider = MavenPlanningProvider()

    proposal = assert_planning_deterministic(provider, request, tmp_path)
    plan = Planner((provider,)).negotiate(request)
    actions = {action.id: action for action in proposal.actions}
    upstream = actions["maven.verify:maven:platform"]
    downstream = actions["maven.verify:maven:apps"]

    assert plan.status is PlanStatus.EXECUTABLE
    assert plan.ready_action_ids == (upstream.id,)
    assert upstream.requested_node_ids == ()
    assert upstream.node_ids == (
        "maven:platform",
        "maven:platform/common",
        "maven:platform/service-a",
    )
    assert upstream.command is not None
    assert upstream.command[-1] == "install"
    assert "com.example:service-a" in upstream.command
    assert f"-Dmaven.repo.local={RUN_REPOSITORY}" in upstream.command
    assert downstream.requested_node_ids == ("maven:apps/service-b",)
    assert downstream.command is not None
    assert downstream.command[-1] == "verify"
    assert downstream.requires == upstream.produces


def test_repository_exact_and_clean_policies_are_explicit(tmp_path: Path) -> None:
    _workspace(tmp_path)
    inventory = _inventory(tmp_path)
    provider = MavenPlanningProvider()

    repository_request = PlanningRequest(
        "verify",
        inventory,
        ("maven:apps/service-b",),
        {"maven.dependency-policy": "repository"},
    )
    repository_plan = Planner((provider,)).negotiate(repository_request)
    assert len(repository_plan.actions) == 1
    assert not any(
        RUN_REPOSITORY in argument for argument in repository_plan.actions[0].command or ()
    )

    exact_request = PlanningRequest(
        "verify",
        inventory,
        ("maven:apps/service-b",),
        {"maven.dependency-policy": "exact"},
    )
    exact_plan = Planner((provider,)).negotiate(exact_request)
    assert exact_plan.status is PlanStatus.BLOCKED
    assert exact_plan.diagnostics[0].code == "constraint.missing"

    clean_request = PlanningRequest("clean", inventory, ("maven:apps/service-b",))
    clean_action = Planner((provider,)).negotiate(clean_request).actions[0]
    assert clean_action.node_ids == ("maven:apps/service-b",)
    assert "-am" not in (clean_action.command or ())
    assert clean_action.command and clean_action.command[-1] == "clean"


def test_planning_groups_selected_modules_and_rejects_non_maven_nodes(tmp_path: Path) -> None:
    _workspace(tmp_path)
    inventory = _inventory(tmp_path)
    docs = Node("docs", "docs", ("documentation",))
    request = PlanningRequest(
        "test",
        Inventory((*inventory.nodes, docs)),
        ("maven:platform/common", "maven:platform/service-a", "docs"),
    )

    proposal = MavenPlanningProvider().propose(request)

    assert len(proposal.actions) == 1
    assert proposal.actions[0].requested_node_ids == (
        "maven:platform/common",
        "maven:platform/service-a",
    )
    assert proposal.actions[0].command and proposal.actions[0].command[-1] == "test"
    assert proposal.rejected[0].missing == ("nature:maven/project",)


def test_inspection_and_planning_are_read_only(tmp_path: Path) -> None:
    _workspace(tmp_path)
    inspector = MavenInspectionProvider()
    assert_inspection_side_effect_free(inspector, InspectionContext(tmp_path))
    inventory = _inventory(tmp_path)
    request = PlanningRequest("verify", inventory, ("maven:apps/service-b",))
    assert_planning_deterministic(MavenPlanningProvider(), request, tmp_path)
