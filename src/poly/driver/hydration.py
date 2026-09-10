"""Public facts and run-local inventory exchange for hydration contributions."""

from __future__ import annotations

import json
from pathlib import Path

from poly.driver.api import ExecutionContext
from poly.model import Constraint, Inventory, Node, NodeRelation

WORKSPACE_COHERENT = Constraint("poly/workspace-coherent")


def source_available(node_id: str) -> Constraint:
    return Constraint(f"poly/source-available:{node_id}")


def inventory_value(inventory: Inventory) -> dict[str, object]:
    return {
        "schema": "poly.hydration-inventory/v1",
        "nodes": [
            {
                "id": node.id,
                "path": node.path,
                "natures": list(node.natures),
                "metadata": dict(node.metadata),
                "configuration": dict(node.configuration),
                "nature_origins": {key: list(value) for key, value in node.nature_origins.items()},
                "relations": [
                    {"kind": item.kind, "target": item.target} for item in node.relations
                ],
            }
            for node in inventory.nodes
        ],
    }


def read_inventory(path: Path) -> Inventory:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != "poly.hydration-inventory/v1":
        raise ValueError("incompatible hydration inventory")
    return Inventory(
        tuple(
            Node(
                id=item["id"],
                path=item["path"],
                natures=tuple(item["natures"]),
                metadata=item["metadata"],
                configuration=item["configuration"],
                nature_origins={
                    key: tuple(origins) for key, origins in item["nature_origins"].items()
                },
                relations=tuple(
                    NodeRelation(relation["kind"], relation["target"])
                    for relation in item["relations"]
                ),
            )
            for item in value["nodes"]
        )
    )


def hydration_inventory(context: ExecutionContext) -> Inventory:
    """Consume the consolidated inventory after WORKSPACE_COHERENT is satisfied."""
    return read_inventory(context.run_directory / "hydration" / "inventory.json")
