#!/usr/bin/env python3
"""Record the dimensions actually returned for a generated detail patch.

This is intentionally backend-agnostic. It does not assume an API or client
maximum. The generated image file itself is the source of truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from job_contract import Canvas, atomic_write_json, effective_detail_ratio


REGION_TYPES = {"face", "hand", "head", "costume", "prop", "architecture", "background", "generic"}


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("Size must be WIDTHxHEIGHT") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("Dimensions must be positive")
    return width, height


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record requested versus actual dimensions for one generated Photo Refiner patch."
    )
    parser.add_argument("job", type=Path, help="Path to job.json")
    parser.add_argument("--patch", type=Path, required=True, help="Generated patch image inside the job directory")
    parser.add_argument("--region-type", choices=sorted(REGION_TYPES), required=True)
    parser.add_argument("--region-role", default="", help="Optional planner role such as upper-costume or lower-costume")
    parser.add_argument("--requested-size", type=parse_size, required=True, help="Size requested from the client image-generation path")
    parser.add_argument("--planner-region-index", type=int)
    parser.add_argument("--plan", type=Path, help="detail-plan.json from plan_detail_tiles.py; re-checks this patch against the planned region geometry")
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    if args.attempt <= 0:
        raise SystemExit("--attempt must be positive")
    if args.planner_region_index is not None and args.planner_region_index < 0:
        raise SystemExit("--planner-region-index must be zero or greater")

    job_path = args.job.expanduser().resolve()
    if not job_path.is_file() or job_path.name != "job.json":
        raise SystemExit(f"Missing job manifest: {job_path}")
    job_dir = job_path.parent
    patch_path = args.patch.expanduser().resolve()
    if not patch_path.is_file():
        raise SystemExit(f"Missing patch image: {patch_path}")
    if not patch_path.is_relative_to(job_dir):
        raise SystemExit("Patch observation may only record an image inside the job directory")

    data = json.loads(job_path.read_text(encoding="utf-8"))
    detail_mode = str((data.get("detail") or {}).get("mode") or "")
    if detail_mode == "not-applicable":
        raise SystemExit("This job has local detail recovery disabled; refusing to record a generated patch")

    try:
        with Image.open(patch_path) as image:
            actual_size = [image.width, image.height]
            image_format = image.format
            image_mode = image.mode
    except OSError as exc:
        raise SystemExit(f"Cannot read patch image: {patch_path}: {exc}") from exc

    requested_size = list(args.requested_size)
    requested_pixels = requested_size[0] * requested_size[1]
    actual_pixels = actual_size[0] * actual_size[1]
    same_size = requested_size == actual_size
    width_ratio = actual_size[0] / requested_size[0]
    height_ratio = actual_size[1] / requested_size[1]
    pixel_ratio = actual_pixels / requested_pixels

    budget_recheck = None
    if args.plan is not None:
        plan_path = args.plan.expanduser().resolve()
        if not plan_path.is_file():
            raise SystemExit(f"Missing detail plan: {plan_path}")
        if args.planner_region_index is None:
            raise SystemExit("--plan requires --planner-region-index so the region geometry is unambiguous")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        regions = plan.get("regions") or []
        if not 0 <= args.planner_region_index < len(regions):
            raise SystemExit(
                f"--planner-region-index {args.planner_region_index} is outside the plan ({len(regions)} regions)"
            )
        region = regions[args.planner_region_index]
        crop = region["crop"]
        subject = region.get("subject_box") or crop
        ratio = effective_detail_ratio(
            patch_size=tuple(actual_size),
            region_crop_size=(crop["width"], crop["height"]),
            region_subject_size=(subject["width"], subject["height"]),
            working=Canvas(*plan["working_canvas"]),
            delivery=Canvas(*plan["delivery_canvas"]),
            region_type=args.region_type,
        )
        budget_recheck = {
            "planned_patch_size": region.get("patch_size_planned"),
            "actual_patch_size": actual_size,
            "detail_ratio": round(ratio.minimum, 4),
            "threshold": ratio.threshold,
            "accepted": ratio.accepted,
            "recommended_action": ratio.action,
        }

    observations = data.setdefault("patch_observations", [])
    if not isinstance(observations, list):
        raise SystemExit("job.json patch_observations must be an array")

    observation = {
        "schema_version": 1,
        "sequence": len(observations) + 1,
        "recorded_at": datetime.now().astimezone().isoformat(),
        "execution_mode": data.get("execution_mode"),
        "detail_mode": detail_mode,
        "region_type": args.region_type,
        "region_role": args.region_role.strip() or args.region_type,
        "planner_region_index": args.planner_region_index,
        "attempt": args.attempt,
        "patch_path": str(patch_path),
        "patch_file_size": patch_path.stat().st_size,
        "patch_sha256": sha256_file(patch_path),
        "image_format": image_format,
        "image_mode": image_mode,
        "requested_size": requested_size,
        "actual_size": actual_size,
        "requested_pixels": requested_pixels,
        "actual_pixels": actual_pixels,
        "size_match": same_size,
        "return_scale": {
            "width": round(width_ratio, 6),
            "height": round(height_ratio, 6),
            "pixels": round(pixel_ratio, 6),
        },
        "budget_recheck": budget_recheck,
    }
    if args.note.strip():
        observation["note"] = args.note.strip()

    observations.append(observation)
    data["patch_observation_summary"] = {
        "count": len(observations),
        "size_match_count": sum(1 for item in observations if item.get("size_match") is True),
        "size_mismatch_count": sum(1 for item in observations if item.get("size_match") is False),
        "budget_recheck_count": sum(1 for item in observations if item.get("budget_recheck")),
        "budget_recheck_failed": sum(
            1 for item in observations if (item.get("budget_recheck") or {}).get("accepted") is False
        ),
        "actual_sizes": sorted({
            f"{item['actual_size'][0]}x{item['actual_size'][1]}"
            for item in observations
            if isinstance(item.get("actual_size"), list) and len(item["actual_size"]) == 2
        }),
        "requested_sizes": sorted({
            f"{item['requested_size'][0]}x{item['requested_size'][1]}"
            for item in observations
            if isinstance(item.get("requested_size"), list) and len(item["requested_size"]) == 2
        }),
    }
    data["updated_at"] = observation["recorded_at"]

    atomic_write_json(job_path, data)
    print(json.dumps(observation, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
