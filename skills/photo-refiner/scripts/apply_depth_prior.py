#!/usr/bin/env python3
"""Annotate a Photo Refiner detail plan with an optional relative-depth prior.

This stage is intentionally advisory. It never adds regions, changes Pixel Budget,
or increases the generation ceiling. It only attaches spatial guard metadata to
already-planned regions so prompts/review can preserve front/back relationships.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


DEPTH_SOURCES = {"vision-relative", "dense-map", "external"}
OCCLUSION_RISKS = {"low", "medium", "high"}
BACKGROUND_SEPARATION = {"weak", "medium", "strong", "unknown"}
DEPTH_INTENTS = {"occlusion", "depth-of-field", "atmospheric-perspective", "creative-spatial"}
RELATIONS = {"foreground-over-subject", "self-occlusion", "subject-over-background", "unknown"}
MIN_CONFIDENCE = 0.55
BROAD_MERGE_UNIFORMITY = 0.82
MIN_DISCONTINUITY_OVERLAP = 0.05


def finite_unit(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not 0 <= result <= 1:
        raise ValueError(f"{field} must be between 0 and 1")
    return result


def convert_box(value: Any, coordinate_space: str, canvas: tuple[int, int], field: str) -> dict:
    if not isinstance(value, dict) or not all(key in value for key in ("x", "y", "width", "height")):
        raise ValueError(f"{field} must contain x, y, width, height")
    x = finite_number(value["x"], f"{field}.x")
    y = finite_number(value["y"], f"{field}.y")
    width = finite_number(value["width"], f"{field}.width")
    height = finite_number(value["height"], f"{field}.height")
    if coordinate_space == "normalized":
        if min(x, y, width, height) < 0 or max(x, y, width, height) > 1:
            raise ValueError(f"{field} normalized coordinates must stay between 0 and 1")
        x *= canvas[0]
        width *= canvas[0]
        y *= canvas[1]
        height *= canvas[1]
    elif coordinate_space != "pixel":
        raise ValueError("coordinate_space must be pixel or normalized")
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"{field} must use a non-negative origin and positive size")
    left = max(0, min(round(x), canvas[0] - 1))
    top = max(0, min(round(y), canvas[1] - 1))
    right = max(left + 1, min(round(x + width), canvas[0]))
    bottom = max(top + 1, min(round(y + height), canvas[1]))
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def intersection_fraction(a: dict, b: dict) -> float:
    x1 = max(a["x"], b["x"])
    y1 = max(a["y"], b["y"])
    x2 = min(a["x"] + a["width"], b["x"] + b["width"])
    y2 = min(a["y"] + a["height"], b["y"] + b["height"])
    area = max(0, x2 - x1) * max(0, y2 - y1)
    if not area:
        return 0.0
    return area / float(max(1, min(a["width"] * a["height"], b["width"] * b["height"])))


def parse_depth_prior(vision: dict, canvas: tuple[int, int]) -> dict | None:
    raw = vision.get("depth_prior")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("depth_prior must be an object")
    source = raw.get("source", "vision-relative")
    if source not in DEPTH_SOURCES:
        raise ValueError(f"depth_prior.source must be one of: {', '.join(sorted(DEPTH_SOURCES))}")
    confidence = finite_unit(raw.get("confidence", 0.0), "depth_prior.confidence")
    uniformity = raw.get("subject_depth_uniformity")
    if uniformity is not None:
        uniformity = finite_unit(uniformity, "depth_prior.subject_depth_uniformity")
    risk = raw.get("occlusion_risk", "low")
    if risk not in OCCLUSION_RISKS:
        raise ValueError(f"depth_prior.occlusion_risk must be one of: {', '.join(sorted(OCCLUSION_RISKS))}")
    separation = raw.get("background_separation", "unknown")
    if separation not in BACKGROUND_SEPARATION:
        raise ValueError(
            f"depth_prior.background_separation must be one of: {', '.join(sorted(BACKGROUND_SEPARATION))}"
        )
    intents = raw.get("intents", [])
    if not isinstance(intents, list) or any(item not in DEPTH_INTENTS for item in intents):
        raise ValueError(f"depth_prior.intents must contain only: {', '.join(sorted(DEPTH_INTENTS))}")

    coordinate_space = vision.get("coordinate_space", "pixel")
    discontinuities = []
    raw_discontinuities = raw.get("discontinuities", [])
    if not isinstance(raw_discontinuities, list):
        raise ValueError("depth_prior.discontinuities must be an array")
    for index, item in enumerate(raw_discontinuities):
        if not isinstance(item, dict):
            raise ValueError(f"depth_prior.discontinuities[{index}] must be an object")
        relation = item.get("relation", "unknown")
        if relation not in RELATIONS:
            raise ValueError(
                f"depth_prior.discontinuities[{index}].relation must be one of: {', '.join(sorted(RELATIONS))}"
            )
        strength = finite_unit(item.get("strength", 0.5), f"depth_prior.discontinuities[{index}].strength")
        label = str(item.get("label") or f"depth-boundary-{index + 1}").strip()
        if not label:
            label = f"depth-boundary-{index + 1}"
        discontinuities.append({
            "label": label,
            "relation": relation,
            "strength": strength,
            "box": convert_box(item.get("box"), coordinate_space, canvas, f"depth_prior.discontinuities[{index}].box"),
        })

    return {
        "source": source,
        "confidence": confidence,
        "subject_depth_uniformity": uniformity,
        "occlusion_risk": risk,
        "background_separation": separation,
        "intents": list(dict.fromkeys(intents)),
        "discontinuities": discontinuities,
    }


def annotate_plan(plan: dict, vision: dict, *, min_confidence: float = MIN_CONFIDENCE) -> dict:
    if not isinstance(plan, dict):
        raise ValueError("detail plan must be an object")
    working = plan.get("working_canvas")
    regions = plan.get("regions")
    if not isinstance(working, list) or len(working) != 2 or not all(isinstance(v, int) and v > 0 for v in working):
        raise ValueError("detail plan working_canvas must be [width, height]")
    if not isinstance(regions, list):
        raise ValueError("detail plan regions must be an array")

    depth = parse_depth_prior(vision, (working[0], working[1]))
    result = json.loads(json.dumps(plan))
    if depth is None:
        result["depth_prior"] = {
            "present": False,
            "active": False,
            "policy": "optional-advisory-not-truth",
            "generation_count_delta": 0,
        }
        return result

    active = depth["confidence"] >= min_confidence
    summary = {
        "present": True,
        "active": active,
        "policy": "optional-advisory-not-truth",
        "source": depth["source"],
        "confidence": depth["confidence"],
        "subject_depth_uniformity": depth["subject_depth_uniformity"],
        "occlusion_risk": depth["occlusion_risk"],
        "background_separation": depth["background_separation"],
        "intents": depth["intents"],
        "discontinuity_count": len(depth["discontinuities"]),
        "generation_count_delta": 0,
        "ignored_reason": None if active else f"confidence_below_{min_confidence:.2f}",
    }
    result["depth_prior"] = summary

    if not active:
        return result

    for region in result["regions"]:
        crop = region.get("crop")
        if not isinstance(crop, dict) or not all(key in crop for key in ("x", "y", "width", "height")):
            continue
        hits = []
        for boundary in depth["discontinuities"]:
            overlap = intersection_fraction(crop, boundary["box"])
            if overlap >= MIN_DISCONTINUITY_OVERLAP:
                hits.append({
                    "label": boundary["label"],
                    "relation": boundary["relation"],
                    "strength": boundary["strength"],
                    "overlap": round(overlap, 4),
                })

        region_type = region.get("region_type")
        inherently_sensitive = depth["occlusion_risk"] == "high" and region_type in {"face", "head", "hand", "prop"}
        occlusion_sensitive = bool(hits) or inherently_sensitive
        uniformity = depth["subject_depth_uniformity"]
        if occlusion_sensitive:
            merge_policy = "do-not-merge-across-depth-boundary"
        elif depth["occlusion_risk"] == "low" and uniformity is not None and uniformity >= BROAD_MERGE_UNIFORMITY:
            merge_policy = "broad-merge-safe"
        else:
            merge_policy = "neutral"

        constraints = []
        if occlusion_sensitive:
            constraints.append("preserve visible foreground/background ordering from SOURCE MASTER")
            constraints.append("do not reveal or erase surfaces that are genuinely occluded")
        if "depth-of-field" in depth["intents"]:
            constraints.append("preserve the requested focus-plane transition; avoid a hard cutout blur edge")
        if "atmospheric-perspective" in depth["intents"]:
            constraints.append("preserve gradual depth-dependent contrast/haze rather than a binary subject mask")
        if "creative-spatial" in depth["intents"]:
            constraints.append("retain foreground/midground/background ordering through creative translation")

        region["depth_guard"] = {
            "active": occlusion_sensitive or bool(constraints),
            "occlusion_sensitive": occlusion_sensitive,
            "merge_policy": merge_policy,
            "discontinuities": hits,
            "prompt_constraints": list(dict.fromkeys(constraints)),
        }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply optional relative-depth guards to an existing Photo Refiner detail plan.")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--vision-analysis", type=Path, required=True)
    parser.add_argument("--min-confidence", type=float, default=MIN_CONFIDENCE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if not 0 <= args.min_confidence <= 1:
        raise SystemExit("--min-confidence must be between 0 and 1")
    plan_path = args.plan.expanduser().resolve()
    vision_path = args.vision_analysis.expanduser().resolve()
    if not plan_path.is_file():
        raise SystemExit(f"Missing detail plan: {plan_path}")
    if not vision_path.is_file():
        raise SystemExit(f"Missing Vision analysis: {vision_path}")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        vision = json.loads(vision_path.read_text(encoding="utf-8"))
        result = annotate_plan(plan, vision, min_confidence=args.min_confidence)
    except (json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
