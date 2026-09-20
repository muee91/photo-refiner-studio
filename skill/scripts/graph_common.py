#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = SKILL_ROOT / "references" / "starryear" / "catalog.json"

FLOW_TYPES = ["source", "look", "creative-effect", "approval", "recovery", "delivery"]
REQUIRED_TYPES = {"source", "look", "approval", "delivery"}
OPTIONAL_TYPES = {"creative-effect", "recovery"}

def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value

def load_catalog(path: Path = CATALOG_PATH) -> dict[str, dict[str, Any]]:
    catalog = read_json(path)
    recipes = catalog.get("recipes")
    if not isinstance(recipes, list):
        raise ValueError("Starryear catalog is missing recipes")
    result: dict[str, dict[str, Any]] = {}
    for recipe in recipes:
        if not isinstance(recipe, dict) or not isinstance(recipe.get("id"), str):
            raise ValueError("Starryear catalog contains a malformed recipe")
        result[recipe["id"]] = recipe
    return result

def enabled_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in graph.get("nodes", []) if node.get("enabled", True)]

def node_map(graph: dict[str, Any], *, enabled_only: bool = False) -> dict[str, dict[str, Any]]:
    nodes = enabled_nodes(graph) if enabled_only else graph.get("nodes", [])
    result: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("Every node requires a non-empty id")
        if node_id in result:
            raise ValueError(f"Duplicate node id: {node_id}")
        result[node_id] = node
    return result

def node_by_type(graph: dict[str, Any], node_type: str, *, required: bool = False) -> dict[str, Any] | None:
    matches = [node for node in enabled_nodes(graph) if node.get("type") == node_type]
    if len(matches) > 1:
        raise ValueError(f"Only one enabled {node_type} node is allowed")
    if required and not matches:
        raise ValueError(f"Missing required enabled node: {node_type}")
    return matches[0] if matches else None

def flow_edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [edge for edge in graph.get("edges", []) if edge.get("kind", "flow") == "flow"]

def topological_order(graph: dict[str, Any]) -> list[str]:
    nodes = node_map(graph, enabled_only=True)
    incoming = {node_id: 0 for node_id in nodes}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in flow_edges(graph):
        source, target = edge.get("from"), edge.get("to")
        if source not in nodes or target not in nodes:
            continue
        outgoing[source].append(target)
        incoming[target] += 1
    queue = [node_id for node_id, count in incoming.items() if count == 0]
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for target in outgoing[current]:
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    if len(order) != len(nodes):
        raise ValueError("Flow graph contains a cycle")
    return order
