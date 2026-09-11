#!/usr/bin/env python3
"""Quantify whether a generated detail patch adds enough effective local resolution."""

import argparse
import json


DEFAULT_THRESHOLDS = {
    "face": 0.85,
    "hand": 0.75,
    "head": 0.65,
    "costume": 0.50,
    "prop": 0.50,
    "architecture": 0.50,
    "background": 0.30,
    "generic": 0.50,
}


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("Size must be WIDTHxHEIGHT")
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("Dimensions must be positive")
    return width, height


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate effective subject pixels in a planned/generated detail patch. "
            "Use source-crop and source-subject sizes to project expected subject occupancy into the patch."
        )
    )
    parser.add_argument("--patch-size", required=True, type=parse_size, help="Generated patch output WIDTHxHEIGHT")
    parser.add_argument("--source-crop-size", required=True, type=parse_size, help="Source crop WIDTHxHEIGHT used as patch geometry")
    parser.add_argument("--source-subject-size", required=True, type=parse_size, help="Subject bbox WIDTHxHEIGHT inside the source crop")
    parser.add_argument("--final-subject-size", required=True, type=parse_size, help="Subject WIDTHxHEIGHT in the final working canvas")
    parser.add_argument("--region-type", choices=sorted(DEFAULT_THRESHOLDS), default="generic")
    parser.add_argument("--threshold", type=float, help="Override the region default minimum detail ratio")
    args = parser.parse_args()

    patch_w, patch_h = args.patch_size
    crop_w, crop_h = args.source_crop_size
    subject_w, subject_h = args.source_subject_size
    final_w, final_h = args.final_subject_size
    if subject_w > crop_w or subject_h > crop_h:
        raise SystemExit("Source subject size cannot exceed source crop size")

    occupancy_w = subject_w / crop_w
    occupancy_h = subject_h / crop_h
    effective_w = patch_w * occupancy_w
    effective_h = patch_h * occupancy_h
    ratio_w = effective_w / final_w
    ratio_h = effective_h / final_h
    detail_ratio = min(ratio_w, ratio_h)
    threshold = args.threshold if args.threshold is not None else DEFAULT_THRESHOLDS[args.region_type]
    if not 0 < threshold <= 2:
        raise SystemExit("Threshold must be > 0 and <= 2")

    accepted = detail_ratio >= threshold
    if accepted:
        action = "accept"
    elif max(occupancy_w, occupancy_h) < 0.55:
        action = "tighten_crop"
    else:
        action = "request_larger_patch_or_reduce_final_scale"

    report = {
        "region_type": args.region_type,
        "patch_size": [patch_w, patch_h],
        "source_crop_size": [crop_w, crop_h],
        "source_subject_size": [subject_w, subject_h],
        "final_subject_size": [final_w, final_h],
        "subject_occupancy": {"width": occupancy_w, "height": occupancy_h},
        "effective_generated_subject_pixels": {"width": effective_w, "height": effective_h},
        "detail_ratio": {"width": ratio_w, "height": ratio_h, "minimum": detail_ratio},
        "threshold": threshold,
        "accepted": accepted,
        "recommended_action": action,
    }
    print(json.dumps(report, indent=2))
    if not accepted:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
