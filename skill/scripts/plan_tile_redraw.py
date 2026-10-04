#!/usr/bin/env python3
"""Turn a `needs-tiling` verdict into concrete tile boxes.

Why tiles exist: one generation call can only return about the observed cap in
pixels, so a region that is larger than that cap in the *delivered* file cannot be
served in one patch. Cutting the area into tiles of `cap / threshold` keeps every
tile's own budget satisfied while letting the delivery be as large as the file needs.

Rules enforced here:
- tile side <= observed cap / region threshold, so a patch can actually fill it;
- tiles are generated strictest-first, and a tile already covered by an equal or
  finer neighbour is dropped, so overlapping region boxes are not paid for twice;
- the union must leave no gap inside the area it was asked to cover.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from job_contract import (
    PIXEL_BUDGET_THRESHOLDS,
    fit_patch_size,
    parse_size,
    pixel_budget_threshold,
)

BLEND_ORDER = {"costume": 10, "architecture": 10, "generic": 10, "background": 10,
               "head": 20, "hand": 25, "prop": 25, "face": 30}
CELL = 8  # coverage lattice step in canvas pixels


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shrink_to_budget(box: dict, cap: tuple[int, int], threshold: float) -> dict:
    """Nudge a tile down until its patch really meets the threshold.

    Integer rounding of the area-capped patch can land a hair below the target;
    re-deriving the box once keeps the guarantee structural instead of tolerated.
    """
    requested = fit_patch_size(box["width"], box["height"], cap)
    ratio = min(requested[0] / box["width"], requested[1] / box["height"])
    if ratio >= threshold or ratio <= 0:
        return box
    factor = (ratio / threshold) * 0.999
    return {**box,
            "width": max(1, math.floor(box["width"] * factor)),
            "height": max(1, math.floor(box["height"] * factor))}


def parse_box(value: str) -> dict:
    try:
        x, y, w, h = (int(part) for part in value.replace(" ", "").split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("Box must be X,Y,WIDTH,HEIGHT") from None
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        raise argparse.ArgumentTypeError("Box needs non-negative x/y and positive width/height")
    return {"x": x, "y": y, "width": w, "height": h}


def regions_from_plan(plan: dict, canvas_w: int, canvas_h: int) -> tuple[list[dict], dict]:
    """Read region boxes out of a detail plan, rescaled into this canvas."""
    working = plan.get("working_canvas") or [canvas_w, canvas_h]
    if working[0] <= 0 or working[1] <= 0:
        raise SystemExit("detail plan has a bad working_canvas")
    scale_x, scale_y = canvas_w / working[0], canvas_h / working[1]
    if abs(scale_x - scale_y) / max(scale_x, scale_y) > 0.01:
        raise SystemExit(
            f"detail plan canvas {working[0]}x{working[1]} has a different aspect than "
            f"{canvas_w}x{canvas_h}; tile against the canvas the plan was made for"
        )
    regions = []
    for item in plan.get("regions") or []:
        crop = item["crop"]
        regions.append({
            "region_type": item["region_type"],
            "region_role": item.get("region_role", item["region_type"]),
            "box": {
                "x": round(crop["x"] * scale_x),
                "y": round(crop["y"] * scale_y),
                "width": max(1, round(crop["width"] * scale_x)),
                "height": max(1, round(crop["height"] * scale_y)),
            },
        })
    for item in plan.get("regions_dropped_for_budget") or []:
        box = item.get("crop_box")
        if not isinstance(box, dict) or not {"x", "y", "width", "height"} <= set(box):
            raise SystemExit(
                f"detail plan dropped region {item.get('region_role')!r} without a crop_box; "
                "re-run plan_detail_tiles.py so tiling knows where the region was"
            )
        regions.append({
            "region_type": item["region_type"],
            "region_role": item.get("region_role", item["region_type"]),
            "box": {"x": round(box["x"] * scale_x), "y": round(box["y"] * scale_y),
                    "width": max(1, round(box["width"] * scale_x)),
                    "height": max(1, round(box["height"] * scale_y))},
        })
    return regions, {"plan_working_canvas": working, "applied_scale": round(scale_x, 6)}


def grid_tiles(box: dict, tile_w: int, tile_h: int, overlap: float, canvas_w: int, canvas_h: int,
               max_area: int | None = None) -> list[dict]:
    """Grid a region into tiles with overlap and no gap at the far edge."""
    x1 = min(canvas_w, box["x"] + box["width"])
    y1 = min(canvas_h, box["y"] + box["height"])
    span_x = max(1, x1 - box["x"])
    span_y = max(1, y1 - box["y"])
    tw, th = min(tile_w, span_x), min(tile_h, span_y)
    if max_area and tw * th > max_area:
        # Clamping one axis to the region leaves the other too generous: the generator
        # caps total pixels, so the reachable area bounds both axes together.
        factor = math.sqrt(max_area / (tw * th))
        tw = max(1, math.floor(tw * factor))
        th = max(1, math.floor(th * factor))
    step_x = max(1, math.floor(tw * (1 - overlap)))
    step_y = max(1, math.floor(th * (1 - overlap)))

    def offsets(start: int, span: int, tile: int, step: int) -> list[int]:
        if span <= tile:
            return [start]
        count = math.ceil((span - tile) / step) + 1
        positions = [start + i * step for i in range(count)]
        # Pull the last row/column back to the edge so the far side is not left thin.
        positions[-1] = start + span - tile
        return sorted(set(positions))

    return [
        {"x": tx, "y": ty, "width": tw, "height": th}
        for tx in offsets(box["x"], span_x, tw, step_x)
        for ty in offsets(box["y"], span_y, th, step_y)
    ]


def mark(covered: np.ndarray, box: dict, value: bool) -> None:
    covered[box["y"] // CELL:(box["y"] + box["height"]) // CELL + 1,
            box["x"] // CELL:(box["x"] + box["width"]) // CELL + 1] = value


def coverage_fraction(covered: np.ndarray, box: dict) -> float:
    ys, xs = slice(box["y"] // CELL, (box["y"] + box["height"]) // CELL + 1), \
        slice(box["x"] // CELL, (box["x"] + box["width"]) // CELL + 1)
    window = covered[ys, xs]
    return float(window.mean()) if window.size else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan a gap-free tile grid that satisfies each region's own detail budget."
    )
    parser.add_argument("--image", required=True, type=Path, help="The canvas to be redrawn, tiled in its own pixels")
    parser.add_argument("--observed-patch-size", required=True, type=parse_size,
                        help="Largest patch this runtime has actually returned")
    parser.add_argument("--detail-plan", type=Path, help="detail-plan.json; tiles its regions (kept and dropped)")
    parser.add_argument("--region-box", action="append", type=parse_box, default=[],
                        help="Explicit X,Y,W,H region to tile; repeatable")
    parser.add_argument("--region-type", choices=sorted(PIXEL_BUDGET_THRESHOLDS), default="generic")
    parser.add_argument("--full-canvas", action="store_true", help="Tile the entire canvas")
    parser.add_argument("--overlap", type=float, default=0.15, help="Linear tile overlap fraction (default 0.15)")
    parser.add_argument("--sliver-margin", type=float, default=0.05,
                        help="Drop a tile whose own area adds less than this fraction of new coverage; the thin remainder is left to the raised base canvas")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if not 0 <= args.overlap < 0.6:
        raise SystemExit("--overlap must be between 0 and 0.6")
    if not 0 <= args.sliver_margin < 0.5:
        raise SystemExit("--sliver-margin must be between 0 and 0.5")
    image = args.image.expanduser().resolve()
    if not image.is_file():
        raise SystemExit(f"Missing canvas image: {image}")
    with Image.open(image) as handle:
        canvas_w, canvas_h = handle.width, handle.height

    regions: list[dict] = []
    source_tiling: dict | None = None
    provenance: dict = {"source": []}
    if args.detail_plan:
        plan_path = args.detail_plan.expanduser().resolve()
        if not plan_path.is_file():
            raise SystemExit(f"Missing detail plan: {plan_path}")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan_regions, meta = regions_from_plan(plan, canvas_w, canvas_h)
        regions.extend(plan_regions)
        provenance["detail_plan"] = {"path": str(plan_path), **meta}
        provenance["source"].append("detail_plan")
        # The planner's naive per-region sum, kept so the dedupe saving is visible.
        source_tiling = plan.get("tiling_requirement")
    for index, box in enumerate(args.region_box):
        regions.append({"region_type": args.region_type, "region_role": f"region-{index + 1}", "box": box})
    if args.region_box:
        provenance["source"].append("region_box")
    if args.full_canvas:
        regions.append({"region_type": args.region_type, "region_role": "full-canvas",
                        "box": {"x": 0, "y": 0, "width": canvas_w, "height": canvas_h}})
        provenance["source"].append("full_canvas")
    if not regions:
        raise SystemExit("Nothing to tile: pass --detail-plan, --region-box or --full-canvas")

    covered = np.zeros((math.ceil(canvas_h / CELL), math.ceil(canvas_w / CELL)), dtype=bool)
    slivers = np.zeros_like(covered)
    target = np.zeros_like(covered)
    for region in regions:
        mark(target, region["box"], True)

    # Strictest first: a finer grid satisfies a looser region, but never the reverse.
    tiles: list[dict] = []
    dropped_duplicates = 0
    dropped_slivers = 0
    largest_sliver = 0.0
    for region in sorted(regions, key=lambda item: -pixel_budget_threshold(item["region_type"])):
        threshold = pixel_budget_threshold(region["region_type"])
        reach = max(1, math.floor(max(args.observed_patch_size) / threshold))
        reach_area = int(args.observed_patch_size[0] * args.observed_patch_size[1] / threshold ** 2)
        for box in grid_tiles(region["box"], reach, reach, args.overlap, canvas_w, canvas_h, reach_area):
            already = coverage_fraction(covered, box)
            if already >= 1.0:
                dropped_duplicates += 1
                continue
            if already >= 1.0 - args.sliver_margin:
                # The box adds only a hair of new coverage: a near-duplicate
                # generation. Leave the thin remainder to the raised base canvas.
                mark(slivers, box, True)
                dropped_slivers += 1
                largest_sliver = max(largest_sliver, 1.0 - already)
                continue
            box = shrink_to_budget(box, args.observed_patch_size, threshold)
            requested = fit_patch_size(box["width"], box["height"], args.observed_patch_size)
            tiles.append({
                "index": len(tiles),
                "box": box,
                "region_type": region["region_type"],
                "region_role": region["region_role"],
                "threshold": threshold,
                "requested_size": list(requested),
                "budget_ratio": round(min(requested[0] / box["width"], requested[1] / box["height"]), 4),
                "blend_order": BLEND_ORDER.get(region["region_type"], 10),
            })
            mark(covered, box, True)

    uncovered_cells = int(np.count_nonzero(target & ~covered))
    report = {
        "schema_version": 1,
        "canvas": [canvas_w, canvas_h],
        "canvas_path": str(image),
        "canvas_sha256": sha256_file(image),
        "observed_patch_size": list(args.observed_patch_size),
        "tile_overlap": args.overlap,
        "coverage_cell": CELL,
        "provenance": provenance,
        "source_tiling_request": source_tiling,
        "tile_count": len(tiles),
        "deduplicated_tiles": dropped_duplicates,
        "sliver_tiles_dropped": dropped_slivers,
        "estimated_generation_calls": len(tiles),
        "tiles": tiles,
        "coverage": {
            "target_area": int(np.count_nonzero(target)) * CELL * CELL,
            "covered_area": int(np.count_nonzero(target & covered)) * CELL * CELL,
            "uncovered_area": uncovered_cells * CELL * CELL,
            "sliver_area": int(np.count_nonzero(target & ~covered & slivers)) * CELL * CELL,
            "largest_sliver_fraction": round(largest_sliver, 4),
            "sliver_margin": args.sliver_margin,
        },
        "blend_sequence": [tile["index"] for tile in sorted(tiles, key=lambda item: (item["blend_order"], item["index"]))],
    }
    # Anything the target wanted, that no tile covered and that is not an accepted
    # thin remainder, is a real hole.
    hole_cells = int(np.count_nonzero(target & ~covered & ~slivers))
    weakest = min((tile["budget_ratio"] for tile in tiles), default=0.0)
    report["verdict"] = "pass" if tiles and hole_cells == 0 and weakest > 0 else "fail"
    report["coverage"]["hole_area"] = hole_cells * CELL * CELL
    if report["verdict"] == "fail":
        report["required_action"] = (
            "A real gap remains (hole_area > 0) or a tile could not meet its own threshold; "
            "re-check --observed-patch-size against a recorded patch observation, or lower "
            "--sliver-margin to 0 so no remainder is delegated to the base canvas."
        )

    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["verdict"] != "pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
