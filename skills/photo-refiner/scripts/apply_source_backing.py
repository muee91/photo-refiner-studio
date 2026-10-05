#!/usr/bin/env python3
"""Normalize a detail plan for source-backed original-resolution photography.

Ordinary photographic refinement has a real high-resolution SOURCE MASTER. When
`prepare_hd_working_canvas.py` chooses `source-backed-detail`, regions that cannot
justify a generated patch at the final source-width are not an instruction to
regenerate the entire photograph. They keep SOURCE MASTER micro-detail instead.

This script turns the planner's pre-normalization `needs-tiling` signal into an
auditable `source-backed` plan, and records a trusted geometry raise in job.json so
the delivery gate understands where the final high-frequency information came from.

It must never be used for creative/synthetic canvases or changed framing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from job_contract import atomic_write_json


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_size(path: Path) -> list[int]:
    with Image.open(path) as image:
        return [image.width, image.height]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert an ordinary source-width detail plan from tiling pressure to SOURCE MASTER-backed delivery."
    )
    parser.add_argument("job", type=Path, help="Path to job.json")
    parser.add_argument("plan", type=Path, help="Raw detail-plan.json from plan_detail_tiles.py")
    parser.add_argument("--output", type=Path, required=True, help="Normalized source-backed plan")
    args = parser.parse_args()

    job_path = args.job.expanduser().resolve()
    plan_path = args.plan.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    if not job_path.is_file() or job_path.name != "job.json":
        raise SystemExit(f"Missing job manifest: {job_path}")
    job_dir = job_path.parent
    for candidate, label in ((plan_path, "detail plan"), (output_path, "output")):
        if not candidate.is_relative_to(job_dir):
            raise SystemExit(f"{label} must stay inside the job directory: {candidate}")
    if not plan_path.is_file():
        raise SystemExit(f"Missing detail plan: {plan_path}")

    job = json.loads(job_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    hd = job.get("hd_working_canvas") or {}
    if hd.get("route") != "source-backed-detail" or hd.get("source_backed") is not True:
        raise SystemExit("Source-backed normalization is only valid after the source-backed-detail HD route")
    if job.get("creative_recipe") is not None:
        raise SystemExit("Creative jobs may not use ordinary SOURCE MASTER-backed normalization")
    if str(job.get("resolution") or "").lower() != "source-width":
        raise SystemExit("Source-backed normalization requires source-width delivery")
    if str(job.get("aspect_ratio") or "original") != "original":
        raise SystemExit("Source-backed normalization requires original framing")

    delivery = hd.get("delivery_canvas")
    if not isinstance(delivery, list) or len(delivery) != 2:
        raise SystemExit("HD record is missing delivery_canvas")
    if plan.get("delivery_canvas") != delivery:
        raise SystemExit(
            f"Detail plan delivery_canvas {plan.get('delivery_canvas')} does not match HD delivery {delivery}"
        )

    hd_output = Path(str(hd.get("output") or "")).expanduser().resolve()
    if (
        not hd_output.is_file()
        or not hd_output.is_relative_to(job_dir)
        or image_size(hd_output) != hd.get("output_size")
        or sha256_file(hd_output) != hd.get("output_sha256")
    ):
        raise SystemExit("Prepared source-backed HD working canvas is missing or has changed")

    detail_result = hd.get("source_detail_result") or {}
    source_master = Path(str(detail_result.get("source_master") or "")).expanduser().resolve()
    if (
        not source_master.is_file()
        or sha256_file(source_master) != detail_result.get("source_master_sha256")
        or image_size(source_master) != delivery
    ):
        raise SystemExit("SOURCE MASTER evidence for source-backed delivery is missing or stale")

    dropped = plan.get("regions_dropped_for_budget") or []
    # Source backing only resolves regions that were dropped because their
    # generated patch would underfeed the delivery canvas. Keep every selected
    # face/head/hand/prop region intact so the controller still executes the
    # auditable local recovery patches.
    selected_regions = plan.get("regions")
    if not isinstance(selected_regions, list):
        selected_regions = []
    plan["regions"] = selected_regions
    plan["region_count"] = len(selected_regions)
    original_feasibility = plan.get("delivery_feasibility") or {}
    source_backed_regions = []
    for item in dropped:
        backed = dict(item)
        backed["source_backed"] = True
        backed["action"] = "retain-source-master-detail"
        backed["reason"] = (
            "generated patch would underfeed this delivery footprint; retain SOURCE MASTER high-frequency detail "
            "instead of forcing full-canvas redraw"
        )
        source_backed_regions.append(backed)

    plan["source_backing"] = {
        "enabled": True,
        "mode": "source-master-high-frequency",
        "source_master": str(source_master),
        "source_master_sha256": detail_result.get("source_master_sha256"),
        "look_master": detail_result.get("look_master"),
        "look_master_sha256": detail_result.get("look_master_sha256"),
        "delivery_canvas": delivery,
        "source_backed_region_count": len(source_backed_regions),
        "source_backed_regions": source_backed_regions,
        "original_delivery_feasibility": original_feasibility,
        "policy": (
            "SOURCE MASTER owns factual high-frequency texture at original resolution; LOOK MASTER owns low/mid-frequency "
            "appearance; only selected valuable regions are regenerated. Source backing does not add patch quota."
        ),
    }
    plan["regions_dropped_for_budget"] = []
    plan["delivery_feasibility"] = {
        "verdict": "source-backed",
        "requested_delivery_width": delivery[0],
        "max_honest_delivery_width": delivery[0],
        "binding_regions": [
            {
                "region_type": item.get("region_type"),
                "region_role": item.get("region_role"),
                "crop": item.get("crop"),
            }
            for item in selected_regions
        ],
        "source_backed_regions": [
            {
                "region_type": item.get("region_type"),
                "region_role": item.get("region_role"),
                "crop_box": item.get("crop_box"),
            }
            for item in source_backed_regions
        ],
    }
    plan["tiling_requirement"] = {
        "required": False,
        "reason": "ordinary source-width delivery is backed by the real high-resolution SOURCE MASTER",
        "estimated_generation_calls": 0,
        "user_confirmation_required": False,
    }

    # The delivery gate's geometry chain starts from the approved/generated LOOK
    # MASTER. Record that SOURCE MASTER detail lift legitimately reaches the source
    # dimensions; unlike a generic resize, this pass has real source-resolution
    # information behind it.
    passes = job.setdefault("upscale_passes", [])
    passes[:] = [
        item for item in passes
        if not (isinstance(item, dict) and item.get("engine") == "source-master-detail-lift")
    ]
    passes.append({
        "engine": "source-master-detail-lift",
        "adds_information": True,
        "from": list(hd.get("input_size") or []),
        "to": list(delivery),
        "information_to": list(delivery),
        "native_information_scale": "source-master",
        "source_backed": True,
        "source_master": str(source_master),
        "source_master_sha256": detail_result.get("source_master_sha256"),
        "working_canvas": str(hd_output),
        "working_canvas_sha256": hd.get("output_sha256"),
    })

    policy = job.setdefault("hd_working_canvas_policy", {})
    policy["routes"] = [
        "native-detail",
        "source-backed-detail",
        "ultrasharp-detail",
        "full-canvas-tile-redraw",
    ]
    policy["note"] = (
        "Ordinary original-framing source-width photography prefers source-backed-detail: SOURCE MASTER supplies real "
        "high-frequency source detail, LOOK MASTER supplies approved appearance, and only valuable local regions are regenerated. "
        "Full-canvas tile redraw is reserved for canvases that cannot be backed by SOURCE MASTER."
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    atomic_write_json(job_path, job)
    print(output_path)


if __name__ == "__main__":
    main()
