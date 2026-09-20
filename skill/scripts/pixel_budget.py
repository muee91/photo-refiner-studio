#!/usr/bin/env python3
"""Quantify whether a generated detail patch adds enough effective local resolution.

All region measurements are given in working-canvas space (the coordinates the
planner emits and `register_blend.py` composites against) and are projected onto
the delivery canvas here. Passing working-canvas coordinates and forgetting that
the deliverable is larger is what let a 1024x1536 composite be delivered as
4672x7008 while every patch still reported "accept".
"""

import argparse
import json

from job_contract import (
    PIXEL_BUDGET_THRESHOLDS,
    Canvas,
    RegionGeometry,
    effective_detail_ratio,
    parse_size,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate effective subject pixels in a planned/generated detail patch and "
            "project them onto the delivery canvas."
        )
    )
    parser.add_argument("--patch-size", required=True, type=parse_size, help="Generated patch output WIDTHxHEIGHT")
    parser.add_argument("--working-canvas", required=True, type=parse_size, help="LOOK MASTER canvas WIDTHxHEIGHT that region coordinates live in")
    parser.add_argument("--delivery-canvas", required=True, type=parse_size, help="Final delivered WIDTHxHEIGHT")
    parser.add_argument("--region-crop", required=True, type=RegionGeometry.from_flag, help="Working-canvas patch crop x,y,width,height")
    parser.add_argument("--region-subject", required=True, type=RegionGeometry.from_flag, help="Working-canvas subject box x,y,width,height inside the crop")
    parser.add_argument("--region-type", choices=sorted(PIXEL_BUDGET_THRESHOLDS), default="generic")
    parser.add_argument("--threshold", type=float, help="Override the region default minimum detail ratio")
    args = parser.parse_args()

    working = Canvas(*args.working_canvas)
    delivery = Canvas(*args.delivery_canvas)
    if args.region_subject.width > args.region_crop.width or args.region_subject.height > args.region_crop.height:
        raise SystemExit("Subject box cannot be larger than its crop")
    if working.aspect <= 0 or delivery.aspect <= 0:
        raise SystemExit("Canvas dimensions must be positive")
    if abs(working.aspect - delivery.aspect) / delivery.aspect > 0.01:
        raise SystemExit(
            "Working and delivery canvas aspect differ "
            f"({working.width}x{working.height} vs {delivery.width}x{delivery.height}); "
            "the delivery resize would change composition rather than scale it"
        )
    if args.threshold is not None and not 0 < args.threshold <= 2:
        raise SystemExit("Threshold must be > 0 and <= 2")

    ratio = effective_detail_ratio(
        patch_size=args.patch_size,
        region_crop_size=(args.region_crop.width, args.region_crop.height),
        region_subject_size=(args.region_subject.width, args.region_subject.height),
        working=working,
        delivery=delivery,
        region_type=args.region_type,
        threshold=args.threshold,
    )
    scale = delivery.width / working.width
    report = {
        "region_type": args.region_type,
        "patch_size": list(args.patch_size),
        "working_canvas": [working.width, working.height],
        "delivery_canvas": [delivery.width, delivery.height],
        "delivery_scale": round(scale, 6),
        "region_crop_working": [args.region_crop.width, args.region_crop.height],
        "region_subject_working": [args.region_subject.width, args.region_subject.height],
        "region_subject_delivery": [
            round(args.region_subject.width * scale),
            round(args.region_subject.height * scale),
        ],
        "subject_occupancy": {"width": ratio.occupancy_w, "height": ratio.occupancy_h},
        "effective_generated_subject_pixels": {"width": ratio.effective_w, "height": ratio.effective_h},
        "detail_ratio": {"width": ratio.width, "height": ratio.height, "minimum": ratio.minimum},
        "threshold": ratio.threshold,
        "accepted": ratio.accepted,
        "recommended_action": ratio.action,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not ratio.accepted:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
