#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from graph_common import node_by_type, read_json
from validate_graph import validate_graph

def compile_plan(graph: dict[str, Any], catalog_path: Path | None = None) -> dict[str, Any]:
    validation = validate_graph(graph, catalog_path)
    look = node_by_type(graph, "look", required=True)
    creative = node_by_type(graph, "creative-effect")
    approval = node_by_type(graph, "approval", required=True)
    recovery = node_by_type(graph, "recovery")
    delivery = node_by_type(graph, "delivery", required=True)

    steps: list[dict[str, Any]] = [{"id":"prepare_source","nodeId":"source","kind":"prepare-source","requiresApproval":False}]
    look_mode = look["config"].get("renderMode", "look-master")
    if look_mode == "look-master":
        steps.append({"id":"render_look_a","nodeId":look["id"],"kind":"render-look","output":"LOOK_A","requiresApproval":bool(creative and approval["config"].get("deliveryMode") == "preview-first")})
    else:
        steps.append({"id":"resolve_look_direction","nodeId":look["id"],"kind":"resolve-look-direction","output":"LOOK_DIRECTION_A","requiresApproval":False})

    if creative:
        cfg = creative["config"]
        steps.append({
            "id":"render_effect_b","nodeId":creative["id"],"kind":"render-creative-effect",
            "mode":cfg.get("mode","direct-effect"),"recipeId":cfg.get("recipeId"),
            "input":"LOOK_A" if look_mode == "look-master" else "SOURCE_MASTER+LOOK_DIRECTION_A",
            "output":"LOOK_AB" if cfg.get("mode") == "direct-effect" else "CREATIVE_ASSEMBLY",
            "requiresApproval":approval["config"].get("deliveryMode") == "preview-first"
        })
    elif approval["config"].get("deliveryMode") == "preview-first":
        for step in reversed(steps):
            if step["kind"] == "render-look":
                step["requiresApproval"] = True
                break

    steps.append({"id":"approve_base","nodeId":approval["id"],"kind":"approval-gate","mode":approval["config"].get("deliveryMode","preview-first")})

    if recovery and recovery.get("enabled", True) and recovery["config"].get("mode") != "disabled":
        steps.append({"id":"recover_detail","nodeId":recovery["id"],"kind":"detail-recovery","mode":recovery["config"].get("mode","normal"),"generationBudget":recovery["config"].get("generationBudget","balanced"),"output":"RECOVERED_MASTER"})

    steps.append({"id":"deliver","nodeId":delivery["id"],"kind":"delivery","resolution":delivery["config"].get("resolution","source-width"),"outputFormat":delivery["config"].get("outputFormat","jpg")})

    plan = {
        "planVersion":1,"graphId":graph["graphId"],"flow":validation["flow"],"steps":steps,
        "approvalCount":sum(1 for step in steps if step.get("requiresApproval")),
        "creativeRecipe":validation["creativeRecipe"],
        "recoveryMode":recovery["config"].get("mode") if recovery and recovery.get("enabled", True) else "disabled"
    }
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",",":"))
    plan["planHash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return plan

def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a validated Photo Refiner node graph into an execution plan")
    parser.add_argument("graph", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    graph = read_json(args.graph.expanduser().resolve())
    try:
        plan = compile_plan(graph, args.catalog.expanduser().resolve() if args.catalog else None)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    rendered = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.expanduser().resolve().write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

if __name__ == "__main__":
    main()
