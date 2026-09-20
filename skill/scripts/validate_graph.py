#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from graph_common import FLOW_TYPES, OPTIONAL_TYPES, REQUIRED_TYPES, load_catalog, node_by_type, node_map, read_json, topological_order

def _as_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value

def validate_graph(graph: dict[str, Any], catalog_path: Path | None = None) -> dict[str, Any]:
    if graph.get("version") != 1:
        raise ValueError("Graph version must be 1")
    if not isinstance(graph.get("graphId"), str) or not graph["graphId"].strip():
        raise ValueError("graphId is required")
    if not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        raise ValueError("nodes and edges must be arrays")

    all_nodes = node_map(graph)
    enabled = node_map(graph, enabled_only=True)
    for node in all_nodes.values():
        node_type = node.get("type")
        if node_type not in FLOW_TYPES:
            raise ValueError(f"Unknown node type: {node_type}")
        if not isinstance(node.get("enabled"), bool):
            raise ValueError(f"Node {node['id']} enabled must be boolean")
        _as_object(node.get("config"), f"{node['id']}.config")

    type_counts = {node_type: 0 for node_type in FLOW_TYPES}
    for node in enabled.values():
        type_counts[node["type"]] += 1
    for node_type in REQUIRED_TYPES:
        if type_counts[node_type] != 1:
            raise ValueError(f"Exactly one enabled {node_type} node is required")
    for node_type in OPTIONAL_TYPES:
        if type_counts[node_type] > 1:
            raise ValueError(f"At most one enabled {node_type} node is allowed")

    flow_pairs: list[tuple[str, str]] = []
    for edge in graph["edges"]:
        if not isinstance(edge, dict):
            raise ValueError("Every edge must be an object")
        source, target = edge.get("from"), edge.get("to")
        if source not in all_nodes or target not in all_nodes:
            raise ValueError(f"Edge references unknown node: {source} -> {target}")
        if source == target:
            raise ValueError("Self edges are not allowed")
        if edge.get("kind", "flow") == "flow" and source in enabled and target in enabled:
            flow_pairs.append((source, target))

    order_ids = topological_order(graph)
    order_types = [enabled[node_id]["type"] for node_id in order_ids]
    expected = [node_type for node_type in FLOW_TYPES if type_counts[node_type]]
    if order_types != expected:
        raise ValueError(f"Enabled flow must follow {' -> '.join(expected)}; got {' -> '.join(order_types)}")
    if sorted(flow_pairs) != sorted(zip(order_ids, order_ids[1:])):
        raise ValueError("Enabled flow must be one continuous chain with no bypass or branch edges")

    source = node_by_type(graph, "source", required=True)
    source_count = _as_object(source["config"], "source.config").get("sourceCount")
    if not isinstance(source_count, int) or source_count < 1:
        raise ValueError("source.sourceCount must be a positive integer")

    look = node_by_type(graph, "look", required=True)
    render_mode = _as_object(look["config"], "look.config").get("renderMode", "look-master")
    if render_mode not in {"direction-only", "look-master"}:
        raise ValueError("look.renderMode must be direction-only or look-master")

    approval = node_by_type(graph, "approval", required=True)
    delivery_mode = approval["config"].get("deliveryMode", "preview-first")
    if delivery_mode not in {"preview-first", "one-click"}:
        raise ValueError("approval.deliveryMode must be preview-first or one-click")

    creative = node_by_type(graph, "creative-effect")
    recovery = node_by_type(graph, "recovery")
    recipe_id = None
    if creative:
        cfg = creative["config"]
        recipe_id = cfg.get("recipeId")
        mode = cfg.get("mode", "direct-effect")
        if mode not in {"direct-effect", "original-assembly"}:
            raise ValueError("creative-effect.mode must be direct-effect or original-assembly")
        catalog = load_catalog(catalog_path) if catalog_path else load_catalog()
        recipe = catalog.get(recipe_id)
        if not recipe:
            raise ValueError(f"Unknown creative recipe: {recipe_id}")
        bounds = recipe.get("sourceCount") or {}
        if source_count < bounds.get("min", 1) or source_count > bounds.get("max", source_count):
            raise ValueError(f"Creative recipe {recipe_id} does not accept {source_count} source photographs")
        frozen = cfg.get("sourceCommit")
        if frozen and frozen != recipe.get("sourceCommit"):
            raise ValueError("Creative recipe sourceCommit does not match installed catalog")
        if mode == "original-assembly" and render_mode == "look-master":
            raise ValueError("original-assembly cannot consume a rendered LOOK_A; use look.renderMode=direction-only")

    if recovery:
        mode = recovery["config"].get("mode", "normal")
        if mode not in {"normal", "creative-safe", "disabled"}:
            raise ValueError("recovery.mode must be normal, creative-safe, or disabled")
        if creative:
            creative_mode = creative["config"].get("mode", "direct-effect")
            if creative_mode == "original-assembly" and mode != "disabled":
                raise ValueError("Recovery must be disabled for original-assembly")
            if source_count > 1 and mode == "creative-safe":
                raise ValueError("creative-safe recovery is currently single-source only")
        elif mode == "creative-safe":
            raise ValueError("creative-safe recovery requires an enabled creative-effect node")

    delivery = node_by_type(graph, "delivery", required=True)
    if delivery["config"].get("outputFormat", "jpg") not in {"jpg", "png", "both"}:
        raise ValueError("delivery.outputFormat must be jpg, png, or both")

    return {"ok": True, "graphId": graph["graphId"], "enabledNodeCount": len(enabled), "flow": order_types, "creativeRecipe": recipe_id}

def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a Photo Refiner node graph")
    parser.add_argument("graph", type=Path)
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args()
    graph = read_json(args.graph.expanduser().resolve())
    try:
        result = validate_graph(graph, args.catalog.expanduser().resolve() if args.catalog else None)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
