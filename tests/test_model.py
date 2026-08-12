from __future__ import annotations

import pytest

from poly.model import ActionSpec, Inventory, Node, NodeRelation, PlanningRequest


def test_node_normalizes_structural_values() -> None:
    node = Node(
        id="service-a",
        path="services/service-a",
        natures=("maven/module", "java/project", "maven/module"),
        metadata={"maven.artifactId": "service-a"},
    )

    assert node.path == "services/service-a"
    assert node.natures == ("java/project", "maven/module")
    assert node.metadata["maven.artifactId"] == "service-a"
    with pytest.raises(TypeError):
        node.metadata["changed"] = True


@pytest.mark.parametrize("path", ("/absolute", "../outside", "a/../../outside"))
def test_node_rejects_path_outside_workspace(path: str) -> None:
    with pytest.raises(ValueError, match="workspace-relative"):
        Node(id="invalid", path=path)


def test_inventory_is_ordered_and_validates_relations() -> None:
    child = Node(
        id="child",
        path="child",
        relations=(NodeRelation("member-of", "parent"),),
    )
    parent = Node(id="parent", path=".")
    inventory = Inventory((parent, child))

    assert [node.id for node in inventory.nodes] == ["child", "parent"]
    assert inventory.select(("parent", "child", "parent")) == (child, parent)

    with pytest.raises(ValueError, match="dangling"):
        Inventory((child,))


def test_inventory_rejects_duplicate_nodes_and_unknown_selection() -> None:
    node = Node(id="same", path=".")
    with pytest.raises(ValueError, match="duplicate"):
        Inventory((node, node))

    inventory = Inventory((node,))
    with pytest.raises(KeyError):
        PlanningRequest("verify", inventory, ("missing",))


def test_required_identifiers_reject_empty_or_whitespace() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        Node(id=" ", path=".")
    with pytest.raises(ValueError, match="whitespace"):
        Node(id="not valid", path=".")


def test_action_requested_nodes_must_be_covered() -> None:
    with pytest.raises(ValueError, match="must be covered"):
        ActionSpec(
            id="invalid",
            driver="driver",
            verb="verify",
            operation="verify",
            node_ids=("dependency",),
            requested_node_ids=("service",),
        )
