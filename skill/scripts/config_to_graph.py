#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from graph_common import load_catalog, read_json
from validate_graph import validate_graph

def convert_config(config: dict[str, Any], *, source_count: int | None = None, graph_id: str | None = None, catalog_path: Path | None = None) -> dict[str, Any]:
    count = source_count if source_count is not None else config.get("sourceCount", 1)
    if not isinstance(count, int) or count < 1:
        raise ValueError("sourceCount must be a positive integer")
    catalog = load_catalog(catalog_path) if catalog_path else load_catalog()

    recipe_id = str(config.get("creativeRecipe", "none") or "none")
    creative_enabled = recipe_id != "none"
    assembly_mode = str(config.get("creativeAssemblyMode", "direct-effect"))
    from_base = bool(config.get("creativeFromBase", False))
    if assembly_mode == "original-assembly":
        from_base = False

    look_render_mode = "look-master" if not creative_enabled or from_base else "direction-only"
    detail = config.get("detail") if isinstance(config.get("detail"), dict) else {}
    detail_mode = detail.get("mode", "adaptive")

    if not creative_enabled:
        recovery_mode = "disabled" if detail_mode == "base-only" else "normal"
    elif assembly_mode == "original-assembly" or count > 1 or detail_mode == "base-only":
        recovery_mode = "disabled"
    else:
        recovery_mode = "creative-safe"

    nodes = [
        {"id":"source","type":"source","enabled":True,"config":{"sourceCount":count},"position":{"x":40,"y":160}},
        {"id":"look_a","type":"look","enabled":True,"config":{
            "preset":config.get("preset","natural-cinematic"),
            "styleStrength":config.get("styleStrength",45),
            "customPrompt":config.get("customPrompt",""),
            "customAvoid":config.get("customAvoid",""),
            "aspectRatio":config.get("aspectRatio","original"),
            "framing":config.get("framing","preserve"),
            "renderMode":look_render_mode
        },"position":{"x":240,"y":160}}
    ]

    if creative_enabled:
        recipe = catalog.get(recipe_id)
        if not recipe:
            raise ValueError(f"Unknown creative recipe: {recipe_id}")
        nodes.append({"id":"effect_b","type":"creative-effect","enabled":True,"config":{
            "provider":"starryear","recipeId":recipe_id,"mode":assembly_mode,
            "sourceCommit":recipe.get("sourceCommit",""),
            "upstreamBinding":"look-master" if look_render_mode == "look-master" else "direction-only"
        },"position":{"x":440,"y":160}})

    nodes.append({"id":"approval","type":"approval","enabled":True,"config":{"deliveryMode":config.get("deliveryMode","preview-first")},"position":{"x":640 if creative_enabled else 440,"y":160}})

    if recovery_mode != "disabled" or detail_mode != "base-only":
        nodes.append({"id":"recovery","type":"recovery","enabled":recovery_mode != "disabled","config":{
            "mode":recovery_mode,"detailMode":detail_mode,
            "generationBudget":detail.get("generationBudget","balanced"),
            "patchScope":detail.get("patchScope","head-and-face"),
            "strength":detail.get("strength",60)
        },"position":{"x":840 if creative_enabled else 640,"y":160}})

    nodes.append({"id":"delivery","type":"delivery","enabled":True,"config":{
        "resolution":config.get("resolution","source-width"),
        "outputFormat":config.get("outputFormat","jpg"),
        "keepIntermediates":bool(config.get("keepIntermediates",False))
    },"position":{"x":1040 if creative_enabled else 840,"y":160}})

    enabled_ids = [node["id"] for node in nodes if node["enabled"]]
    edges = [{"from":left,"to":right,"kind":"flow"} for left,right in zip(enabled_ids,enabled_ids[1:])]
    graph = {"version":1,"graphId":graph_id or f"photo-refiner-flow-{uuid.uuid4()}","createdFrom":"legacy-config","nodes":nodes,"edges":edges,"metadata":{"legacyConfigVersion":config.get("schemaVersion",2)}}
    validate_graph(graph, catalog_path)
    return graph

def main() -> None:
    parser = argparse.ArgumentParser(description="Convert current Photo Refiner settings JSON into node graph v1")
    parser.add_argument("config", type=Path)
    parser.add_argument("--source-count", type=int)
    parser.add_argument("--graph-id")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = read_json(args.config.expanduser().resolve())
    try:
        graph = convert_config(config, source_count=args.source_count, graph_id=args.graph_id, catalog_path=args.catalog.expanduser().resolve() if args.catalog else None)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    rendered = json.dumps(graph, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.expanduser().resolve().write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

if __name__ == "__main__":
    main()
