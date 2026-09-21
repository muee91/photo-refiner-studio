#!/usr/bin/env python3
"""Decide whether a delivered file may honestly claim its own dimensions.

Two independent checks, because either one alone can be fooled:

- geometry  - was the canvas actually raised to (near) the delivered size? Only
              information-adding upscalers count; a Lanczos pass inflates pixels
              without adding any, so it cannot license an enlargement.
- budget    - can the generated patches feed the subject regions at the delivered
              size? Detail ratio reduces to patch pixels over the region's
              footprint in the delivered file, so it is independent of canvas size
              and a big subject at a big delivery needs tiles, not fewer big patches.

The gate also renders `preview_vs_final_diff.png`: the approved preview resized into
delivery space against the delivered file, so "what I approved" is comparable to
"what I got" in one shared space instead of across two resolutions.

Exit codes: 0 pass, 3 fail the gate, other non-zero = unusable inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from job_contract import MAX_HONEST_UPSCALE, atomic_write_json

DIFF_FILENAME = "preview_vs_final_diff.png"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def measure(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"Missing image for the delivery gate: {path}")
    try:
        with Image.open(path) as image:
            size = [image.width, image.height]
    except OSError as exc:
        raise SystemExit(f"Cannot read {path}: {exc}") from exc
    return {"path": str(path), "size": size, "sha256": sha256_file(path)}


def information_raise(data: dict, reference_size: list[int]) -> tuple[float, list[dict]]:
    """How much larger the canvas genuinely is, starting from the reference image.

    Passes are chained from the reference size, so an already-upscaled composite
    passed as `--master` is not multiplied a second time. Information-free passes
    (Lanczos) are skipped entirely, and a pass that does not start at the current
    size cannot be assumed to have happened on this chain.
    """
    width = reference_size[0]
    applied = []
    for entry in data.get("upscale_passes") or []:
        if not isinstance(entry, dict) or not entry.get("adds_information"):
            continue
        span, from_span = entry.get("to") or [], entry.get("from") or []
        if len(span) != 2 or len(from_span) != 2 or not from_span[0]:
            continue
        if round(from_span[0]) != width:
            continue
        width = span[0]
        applied.append({"engine": entry.get("engine"), "from": from_span, "to": span})
    return (width / reference_size[0] if reference_size[0] else 1.0), applied


def build_diff(approved: dict, final_path: Path, final_size: list[int], job_dir: Path) -> dict:
    """Compare the approved preview with the delivered file in delivery space."""
    approved_path = Path(approved["path"])
    if not approved_path.is_file():
        return {"available": False, "reason": f"approved preview is gone: {approved_path}"}
    if sha256_file(approved_path) != approved.get("sha256"):
        return {"available": False, "reason": "approved preview no longer matches its recorded hash"}
    with Image.open(final_path) as delivered:
        target = delivered.convert("RGB")
    with Image.open(approved_path) as raw:
        reference = raw.convert("RGB").resize(tuple(final_size), Image.LANCZOS)
    difference = np.abs(np.asarray(reference, dtype=np.int16) - np.asarray(target, dtype=np.int16))
    changed = np.any(difference > 4, axis=2)
    share = float(changed.mean())
    amplification = 4
    visual = np.clip(difference.max(axis=2) * amplification, 0, 255).astype(np.uint8)
    diff_path = job_dir / DIFF_FILENAME
    Image.fromarray(visual).save(diff_path)
    return {
        "available": True,
        "path": str(diff_path.resolve()),
        "compared_at_size": list(target.size),
        "changed_pixel_share": round(share, 6),
        "mean_channel_difference": round(float(difference.mean()), 4),
        "max_channel_difference": int(difference.max()),
        "note": "Difference is measured after resizing the approved preview into delivery space; "
                "amplified 4x in the image so subtle shifts are visible.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refuse a delivery that is neither geometrically nor per-region justified."
    )
    parser.add_argument("job", type=Path, help="Path to job.json")
    parser.add_argument("--master", required=True, type=Path, help="The accepted composite that became the delivered file")
    parser.add_argument("--final", required=True, type=Path, help="The file about to be delivered")
    parser.add_argument("--plan", type=Path, help="detail-plan.json from plan_detail_tiles.py; required for recovery-enabled non-HD-master jobs")
    parser.add_argument("--tile-plan", type=Path, help="tile-plan.json from plan_tile_redraw.py; required for hd-master creative delivery")
    parser.add_argument("--max-upscale", type=float, help=f"Allowed delivery/canvas ratio (default {MAX_HONEST_UPSCALE})")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    job_path = args.job.expanduser().resolve()
    if not job_path.is_file() or job_path.name != "job.json":
        raise SystemExit(f"Missing job manifest: {job_path}")
    job_dir = job_path.parent
    for given in (args.master, args.final):
        resolved = given.expanduser().resolve()
        if not resolved.is_relative_to(job_dir):
            raise SystemExit(f"Delivery gate inputs must live inside the job directory: {resolved}")

    master = measure(args.master.expanduser().resolve())
    final = measure(args.final.expanduser().resolve())
    data = json.loads(job_path.read_text(encoding="utf-8"))
    limit = args.max_upscale if args.max_upscale is not None else MAX_HONEST_UPSCALE
    if limit < 1:
        raise SystemExit("--max-upscale cannot be below 1")

    # Geometry is judged from what the user approved, never from an intermediate the
    # agent may have inflated by interpolation on the way.
    reference = None
    if isinstance(data.get("approved_preview"), dict) and data["approved_preview"].get("size"):
        reference = list(data["approved_preview"]["size"])
    reference = reference or master["size"]
    raise_factor, raise_passes = information_raise(data, reference)
    canvas = [round(reference[0] * raise_factor), round(reference[1] * raise_factor)]
    geometry_scale = max(final["size"][0] / canvas[0], final["size"][1] / canvas[1])
    geometry_ok = geometry_scale <= limit

    reasons = []
    if not geometry_ok:
        reasons.append(
            f"geometry: the delivered file is {geometry_scale:.2f}x larger than the canvas that "
            f"really supports it ({canvas[0]}x{canvas[1]}), so most pixels are interpolated. "
            "Raise the working canvas first with an information-adding upscaler "
            "(scripts/upscale_image.py, installed via `upscale_image.py --install-engine`; a "
            "Lanczos fallback is recorded as adds_information=false and does not count), or "
            "deliver at the canvas' native dimensions."
        )

    detail_mode = str((data.get("detail") or {}).get("mode") or "")
    creative_binding = str((data.get("creative_output") or {}).get("upstream_binding") or "")
    detail_required = detail_mode not in {"", "base-only", "not-applicable"}
    hd_master_delivery = creative_binding == "hd-master"

    budget = {"verdict": "not-applicable", "dropped_regions": [], "failed_observations": []}
    if hd_master_delivery and args.tile_plan is None:
        budget = {
            "verdict": "fail",
            "reason": "missing_tile_plan",
            "dropped_regions": [],
            "failed_observations": [],
        }
        reasons.append(
            "budget: hd-master creative delivery requires --tile-plan from plan_tile_redraw.py; "
            "the final tiled redraw cannot be certified from geometry alone."
        )
    elif detail_required and not hd_master_delivery and args.plan is None:
        budget = {
            "verdict": "fail",
            "reason": "missing_detail_plan",
            "dropped_regions": [],
            "failed_observations": [],
        }
        reasons.append(
            "budget: local detail recovery is enabled but --plan was not supplied. "
            "Run plan_detail_tiles.py and pass its detail-plan.json so Pixel Budget cannot be bypassed."
        )

    if args.plan is not None:
        plan_path = args.plan.expanduser().resolve()
        if not plan_path.is_file():
            raise SystemExit(f"Missing detail plan: {plan_path}")
        if not plan_path.is_relative_to(job_dir):
            raise SystemExit(f"Detail plan must live inside the job directory: {plan_path}")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        dropped = plan.get("regions_dropped_for_budget") or []
        feasibility = plan.get("delivery_feasibility") or {}
        failed_observations = [
            {
                "region_type": item.get("region_type"),
                "region_role": (item.get("region_role") or ""),
                "detail_ratio": (item.get("budget_recheck") or {}).get("detail_ratio"),
                "threshold": (item.get("budget_recheck") or {}).get("threshold"),
            }
            for item in data.get("patch_observations") or []
            if (item.get("budget_recheck") or {}).get("accepted") is False
        ]
        budget = {
            "verdict": "pass",
            "planned_regions": plan.get("region_count"),
            "dropped_regions": dropped,
            "failed_observations": failed_observations,
        }
        if dropped or feasibility.get("verdict") == "needs-tiling" or failed_observations:
            budget["verdict"] = "fail"
            tiling = plan.get("tiling_requirement") or {}
            detail = ", ".join(
                f"{item.get('region_role') or item.get('region_type')} "
                f"{item.get('detail_ratio')}<{item.get('threshold')}"
                for item in (dropped + failed_observations)
            )
            reasons.append(
                f"budget: subject regions cannot be fed at {final['size'][0]}x{final['size'][1]} "
                f"by the patches this runtime returns ({detail or feasibility.get('verdict')}). "
                + (
                    tiling.get("consent_prompt", "")
                    if tiling else
                    "Deliver at or below delivery_feasibility.max_honest_delivery_width, or switch "
                    "to the tile-redraw chain so the subject is covered by many observed-size tiles."
                )
            )

    if args.tile_plan is not None:
        tile_path = args.tile_plan.expanduser().resolve()
        if not tile_path.is_file():
            raise SystemExit(f"Missing tile redraw plan: {tile_path}")
        if not tile_path.is_relative_to(job_dir):
            raise SystemExit(f"Tile redraw plan must live inside the job directory: {tile_path}")
        tile_plan = json.loads(tile_path.read_text(encoding="utf-8"))
        tiles = tile_plan.get("tiles") or []
        coverage = tile_plan.get("coverage") or {}
        weak_tiles = [
            {
                "index": item.get("index"),
                "region_type": item.get("region_type"),
                "budget_ratio": item.get("budget_ratio"),
                "threshold": item.get("threshold"),
            }
            for item in tiles
            if not isinstance(item.get("budget_ratio"), (int, float))
            or not isinstance(item.get("threshold"), (int, float))
            or item["budget_ratio"] < item["threshold"]
        ]
        tile_ok = (
            tile_plan.get("verdict") == "pass"
            and bool(tiles)
            and int(coverage.get("hole_area") or 0) == 0
            and not weak_tiles
        )
        tile_budget = {
            "verdict": "pass" if tile_ok else "fail",
            "tile_count": len(tiles),
            "hole_area": int(coverage.get("hole_area") or 0),
            "sliver_area": int(coverage.get("sliver_area") or 0),
            "weak_tiles": weak_tiles,
            "observed_patch_size": tile_plan.get("observed_patch_size"),
        }
        if budget.get("verdict") == "not-applicable":
            budget = {"verdict": tile_budget["verdict"], "dropped_regions": [], "failed_observations": []}
        budget["tile_redraw"] = tile_budget
        if not tile_ok:
            budget["verdict"] = "fail"
            reasons.append(
                "budget: tile redraw evidence failed; require tile-plan verdict=pass, at least one tile, "
                "hole_area=0, and every tile budget_ratio >= its threshold."
            )

    diff = None
    approved = data.get("approved_preview")
    if isinstance(approved, dict) and approved.get("path"):
        diff = build_diff(approved, args.final.expanduser().resolve(), final["size"], job_dir)

    verdict = "pass" if geometry_ok and budget["verdict"] != "fail" else "fail"
    report = {
        "schema_version": 2,
        "verdict": verdict,
        "checked_at": datetime.now().astimezone().isoformat(),
        "master": master,
        "final": final,
        "delivery_scale": round(geometry_scale, 6),
        "geometry": {
            "verdict": "pass" if geometry_ok else "fail",
            "reference_size": reference,
            "reference_source": "approved_preview" if reference != master["size"] else "master",
            "master_size": master["size"],
            "upscale_raise_factor": round(raise_factor, 6),
            "information_passes": raise_passes,
            "effective_canvas": canvas,
            "final_size": final["size"],
            "effective_scale": round(geometry_scale, 6),
            "max_honest_upscale": limit,
        },
        "budget": budget,
        "diff": diff,
        "required_action": " Delivery may not be marked completed until: " + " ".join(reasons) if reasons else "",
    }
    if args.note.strip():
        report["note"] = args.note.strip()

    data["delivery_gate"] = report
    data.setdefault("history", []).append({
        "status": data.get("status"),
        "event": f"delivery_gate_{report['verdict']}",
        "at": report["checked_at"],
        "delivery_scale": report["delivery_scale"],
        **({"note": report["note"]} if "note" in report else {}),
    })
    atomic_write_json(job_path, data)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if verdict != "pass":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
