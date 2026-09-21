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
        planned_delivery_canvas = plan.get("delivery_canvas")
        plan_canvas_matches = (
            hd_master_delivery
            or planned_delivery_canvas == final["size"]
        )
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
            "planned_delivery_canvas": planned_delivery_canvas,
            "final_canvas": final["size"],
            "plan_canvas_matches": plan_canvas_matches,
            "dropped_regions": dropped,
            "failed_observations": failed_observations,
        }
        if not plan_canvas_matches:
            budget["verdict"] = "fail"
            reasons.append(
                f"budget: detail-plan delivery_canvas {planned_delivery_canvas} does not match "
                f"the delivered file {final['size']}; re-plan against the exact final canvas."
            )
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
        tile_plan_sha256 = sha256_file(tile_path)
        tiles = tile_plan.get("tiles") or []
        coverage = tile_plan.get("coverage") or {}
        tile_canvas = tile_plan.get("canvas")
        tile_canvas_matches = tile_canvas == final["size"]
        expected_indices = [item.get("index") for item in tiles]
        index_contract_ok = (
            all(isinstance(index, int) and index >= 0 for index in expected_indices)
            and len(set(expected_indices)) == len(expected_indices)
            and tile_plan.get("tile_count") == len(tiles)
            and set(tile_plan.get("blend_sequence") or []) == set(expected_indices)
            and len(tile_plan.get("blend_sequence") or []) == len(expected_indices)
        )
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
        observations = [
            item for item in (data.get("patch_observations") or [])
            if isinstance(item, dict)
            and item.get("evidence_kind") == "tile-redraw"
            and item.get("evidence_plan_sha256") == tile_plan_sha256
        ]
        evidence_by_index: dict[int, list[dict]] = {}
        for item in observations:
            index = item.get("tile_index")
            if isinstance(index, int):
                evidence_by_index.setdefault(index, []).append(item)

        missing_tile_evidence = []
        failed_tile_evidence = []
        stale_tile_evidence = []
        accepted_tile_evidence = []
        for tile in tiles:
            index = tile.get("index")
            candidates = evidence_by_index.get(index, [])
            accepted_candidates = [
                item for item in candidates
                if (item.get("budget_recheck") or {}).get("accepted") is True
            ]
            valid = None
            for item in sorted(accepted_candidates, key=lambda value: value.get("sequence") or 0, reverse=True):
                patch_path = Path(str(item.get("patch_path") or "")).expanduser().resolve()
                if not patch_path.is_file() or not patch_path.is_relative_to(job_dir):
                    continue
                measured = measure(patch_path)
                if measured["sha256"] != item.get("patch_sha256") or measured["size"] != item.get("actual_size"):
                    continue
                valid = item
                break
            if valid is not None:
                accepted_tile_evidence.append({
                    "tile_index": index,
                    "patch_path": valid.get("patch_path"),
                    "patch_sha256": valid.get("patch_sha256"),
                    "actual_size": valid.get("actual_size"),
                    "detail_ratio": (valid.get("budget_recheck") or {}).get("detail_ratio"),
                })
            elif not candidates:
                missing_tile_evidence.append(index)
            elif not accepted_candidates:
                failed_tile_evidence.append(index)
            else:
                stale_tile_evidence.append(index)

        tile_evidence_ok = (
            len(accepted_tile_evidence) == len(tiles)
            and not missing_tile_evidence
            and not failed_tile_evidence
            and not stale_tile_evidence
        )

        accepted_patch_sha = {
            item["tile_index"]: item.get("patch_sha256")
            for item in accepted_tile_evidence
        }
        plan_receipts = sorted(
            [
                item for item in (data.get("tile_blend_receipts") or [])
                if isinstance(item, dict)
                and item.get("kind") == "tile-redraw"
                and item.get("tile_plan_sha256") == tile_plan_sha256
            ],
            key=lambda item: item.get("sequence") or 0,
        )

        def receipt_is_live(receipt: dict) -> bool:
            if (receipt.get("registration") or {}).get("accepted") is not True:
                return False
            index = receipt.get("tile_index")
            if accepted_patch_sha.get(index) != receipt.get("patch_sha256"):
                return False
            output_path = Path(str(receipt.get("output_path") or "")).expanduser().resolve()
            if not output_path.is_file() or not output_path.is_relative_to(job_dir):
                return False
            if sha256_file(output_path) != receipt.get("output_sha256"):
                return False
            return True

        live_receipts = [item for item in plan_receipts if receipt_is_live(item)]
        blend_sequence = tile_plan.get("blend_sequence") or []

        def find_receipt_chain(position: int, after_sequence: int, previous_output_sha: str | None):
            if position >= len(blend_sequence):
                return []
            wanted = blend_sequence[position]
            for receipt in live_receipts:
                sequence = receipt.get("sequence") or 0
                if sequence <= after_sequence or receipt.get("tile_index") != wanted:
                    continue
                if previous_output_sha is not None and receipt.get("input_base_sha256") != previous_output_sha:
                    continue
                tail = find_receipt_chain(position + 1, sequence, receipt.get("output_sha256"))
                if tail is not None:
                    return [receipt] + tail
            return None

        blend_chain = find_receipt_chain(0, 0, None) if blend_sequence else None
        blend_chain_ok = (
            blend_chain is not None
            and len(blend_chain) == len(blend_sequence)
            and bool(blend_chain)
            and blend_chain[-1].get("output_sha256") == master["sha256"]
        )
        blend_evidence = {
            "receipt_count": len(plan_receipts),
            "live_receipt_count": len(live_receipts),
            "chain_length": len(blend_chain or []),
            "expected_chain_length": len(blend_sequence),
            "chain_tile_indices": [item.get("tile_index") for item in (blend_chain or [])],
            "final_output_matches_master": bool(blend_chain) and blend_chain[-1].get("output_sha256") == master["sha256"],
            "accepted": blend_chain_ok,
        }

        tile_ok = (
            tile_plan.get("verdict") == "pass"
            and tile_canvas_matches
            and index_contract_ok
            and bool(tiles)
            and int(coverage.get("hole_area") or 0) == 0
            and not weak_tiles
            and tile_evidence_ok
            and blend_chain_ok
        )
        tile_budget = {
            "verdict": "pass" if tile_ok else "fail",
            "plan_sha256": tile_plan_sha256,
            "canvas": tile_canvas,
            "final_canvas": final["size"],
            "canvas_matches": tile_canvas_matches,
            "index_contract_ok": index_contract_ok,
            "tile_count": len(tiles),
            "hole_area": int(coverage.get("hole_area") or 0),
            "sliver_area": int(coverage.get("sliver_area") or 0),
            "weak_tiles": weak_tiles,
            "observed_patch_size": tile_plan.get("observed_patch_size"),
            "accepted_tile_evidence": accepted_tile_evidence,
            "missing_tile_evidence": missing_tile_evidence,
            "failed_tile_evidence": failed_tile_evidence,
            "stale_tile_evidence": stale_tile_evidence,
            "blend_evidence": blend_evidence,
        }
        if budget.get("verdict") == "not-applicable":
            budget = {"verdict": tile_budget["verdict"], "dropped_regions": [], "failed_observations": []}
        budget["tile_redraw"] = tile_budget
        if not tile_ok:
            budget["verdict"] = "fail"
            reasons.append(
                "budget: tile redraw evidence failed; require tile-plan verdict=pass, tile-plan canvas "
                "equal to the delivered file, a consistent tile index/blend sequence, hole_area=0, "
                "every planned tile budget_ratio >= its threshold, one still-present accepted "
                "record_patch_observation.py result per tile, and an ordered register_blend.py hash-chain "
                "whose final output hash equals the delivery master."
            )

    # Mandatory evidence remains mandatory even when another optional plan was
    # also supplied; a passing detail-plan may not overwrite a missing hd-master
    # tile-plan failure.
    if hd_master_delivery and args.tile_plan is None:
        budget["verdict"] = "fail"
        budget["reason"] = "missing_tile_plan"
    elif detail_required and not hd_master_delivery and args.plan is None:
        budget["verdict"] = "fail"
        budget["reason"] = "missing_detail_plan"

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
