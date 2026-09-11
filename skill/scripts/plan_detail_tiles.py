#!/usr/bin/env python3
"""Plan a coarse, generation-budget-aware detail-tile layout.

Photo Refiner v2.2 deliberately treats the generation budget as a ceiling, not a
quota. The planner prefers zero/few broad patches over many micro-patches and
expects every selected region to pass pixel_budget.py before generation.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image


BUDGET_LIMITS = {"fast": 1, "balanced": 3, "max": 5}
BASE_VALUE = {
    "face": 1.00,
    "head": 0.78,
    "hand": 0.70,
    "costume": 0.62,
    "prop": 0.58,
    "architecture": 0.58,
    "generic": 0.50,
}
BUDGET_THRESHOLDS = {"fast": 0.50, "balanced": 0.38, "max": 0.24}
BLEND_ORDER = {"costume": 10, "architecture": 10, "generic": 10, "head": 20, "hand": 25, "prop": 25, "face": 30}


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return self.width * self.height

    def clip(self, image_w: int, image_h: int) -> "Box":
        x = max(0, min(self.x, image_w - 1))
        y = max(0, min(self.y, image_h - 1))
        right = max(x + 1, min(self.right, image_w))
        bottom = max(y + 1, min(self.bottom, image_h))
        return Box(x, y, right - x, bottom - y)

    def expand(self, image_w: int, image_h: int, *, left: float, top: float, right: float, bottom: float) -> "Box":
        dx1 = round(self.width * left)
        dy1 = round(self.height * top)
        dx2 = round(self.width * right)
        dy2 = round(self.height * bottom)
        return Box(self.x - dx1, self.y - dy1, self.width + dx1 + dx2, self.height + dy1 + dy2).clip(image_w, image_h)

    def intersection_area(self, other: "Box") -> int:
        x1 = max(self.x, other.x)
        y1 = max(self.y, other.y)
        x2 = min(self.right, other.right)
        y2 = min(self.bottom, other.bottom)
        return max(0, x2 - x1) * max(0, y2 - y1)

    def to_json(self) -> dict:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


def parse_box(value: str) -> Box:
    try:
        x, y, width, height = (int(part.strip()) for part in value.split(",", 3))
    except Exception as exc:
        raise argparse.ArgumentTypeError("Boxes must use x,y,width,height") from exc
    if width <= 0 or height <= 0 or x < 0 or y < 0:
        raise argparse.ArgumentTypeError("Boxes must be non-negative and use positive width/height")
    return Box(x, y, width, height)


def read_image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.width, image.height


def area_fraction(box: Box | None, image_w: int, image_h: int) -> float:
    return 0.0 if box is None else box.area / float(image_w * image_h)


def height_fraction(box: Box | None, image_h: int) -> float:
    return 0.0 if box is None else box.height / float(image_h)


def make_costume_box(subject_box: Box | None, image_w: int, image_h: int) -> Box | None:
    if subject_box is None:
        return None
    return subject_box.expand(image_w, image_h, left=0.08, top=0.05, right=0.08, bottom=0.10)


def make_head_box(face_box: Box | None, image_w: int, image_h: int) -> Box | None:
    if face_box is None:
        return None
    return face_box.expand(image_w, image_h, left=0.55, top=0.60, right=0.55, bottom=0.38)


def make_face_box(face_box: Box | None, image_w: int, image_h: int) -> Box | None:
    if face_box is None:
        return None
    return face_box.expand(image_w, image_h, left=0.10, top=0.12, right=0.10, bottom=0.22)


def candidate_value(region_type: str, subject_box: Box, image_w: int, image_h: int, *, importance: float = 1.0) -> float:
    # sqrt(area fraction) tracks linear visual scale better than raw area. Saturate
    # once a region is already large enough to justify local recovery.
    linear_fraction = math.sqrt(max(area_fraction(subject_box, image_w, image_h), 0.0))
    scale_factor = min(1.0, linear_fraction / 0.32)
    score = BASE_VALUE[region_type] * (0.35 + 0.65 * scale_factor) * importance
    return round(min(score, 1.0), 4)


def append_candidate(candidates: list[dict], *, region_type: str, crop: Box, subject_box: Box, image_w: int, image_h: int, rationale: str, importance: float = 1.0) -> None:
    score = candidate_value(region_type, subject_box, image_w, image_h, importance=importance)
    candidate = {
        "region_type": region_type,
        "blend_order": BLEND_ORDER[region_type],
        "crop": crop.to_json(),
        "subject_box": subject_box.to_json(),
        "value_score": score,
        "recommended_patch_size": [1536, 1536],
        "mask_mode": "lightweight",
        "requires_pixel_budget_check": True,
        "rationale": rationale,
    }
    # Deduplicate only same-type near-duplicates. Nested costume/head/face tiles are
    # intentional coarse levels and must not collapse into one another.
    for index, existing in enumerate(candidates):
        if existing["region_type"] != region_type:
            continue
        old = Box(**existing["crop"])
        overlap = old.intersection_area(crop)
        smaller = min(old.area, crop.area)
        if smaller and overlap / smaller >= 0.80:
            if crop.area > old.area or score > existing["value_score"]:
                candidates[index] = candidate
            return
    candidates.append(candidate)


def build_plan(
    image_w: int,
    image_h: int,
    *,
    subject_type: str,
    detail_budget: str,
    face_box: Box | None,
    subject_box: Box | None,
    hand_boxes: Iterable[Box],
    prop_boxes: Iterable[Box],
) -> dict:
    max_patches = BUDGET_LIMITS[detail_budget]
    threshold = BUDGET_THRESHOLDS[detail_budget]
    candidates: list[dict] = []
    skipped: list[dict] = []
    portrait_like = subject_type in {"portrait", "classical-portrait"}
    costume_box = make_costume_box(subject_box, image_w, image_h)
    head_box = make_head_box(face_box, image_w, image_h)
    planned_face = make_face_box(face_box, image_w, image_h)
    face_h = height_fraction(face_box, image_h)
    subject_area = area_fraction(subject_box, image_w, image_h)

    if portrait_like:
        # Tiny people do not justify separate face/head calls. One broad subject patch
        # is faster and more coherent if the person is large enough to merit anything.
        if face_box is not None and face_h < 0.055:
            if subject_box is not None and subject_area >= 0.055:
                append_candidate(
                    candidates,
                    region_type="costume",
                    crop=costume_box or subject_box,
                    subject_box=subject_box,
                    image_w=image_w,
                    image_h=image_h,
                    rationale="Face is too small for a separate recovery pass; keep one broad subject/costume patch instead.",
                )
            skipped.extend([
                {"region_type": "head", "reason": "face_too_small_for_separate_head_patch"},
                {"region_type": "face", "reason": "face_too_small_for_effective_face_patch"},
            ])
        else:
            # Costume is useful for full/three-quarter figures, but close portraits do
            # not spend a generation on it by default.
            if costume_box is not None and subject_area >= 0.12 and face_h < 0.30:
                append_candidate(
                    candidates,
                    region_type="costume",
                    crop=costume_box,
                    subject_box=subject_box,
                    image_w=image_w,
                    image_h=image_h,
                    rationale="Broad costume/body recovery preserves silhouette, embroidery and fabric structure without micro-patches.",
                )
            elif costume_box is not None:
                skipped.append({"region_type": "costume", "reason": "close_portrait_or_small_subject; broader costume generation not worth the budget"})

            if head_box is not None and face_h >= 0.055:
                append_candidate(
                    candidates,
                    region_type="head",
                    crop=head_box,
                    subject_box=face_box,
                    image_w=image_w,
                    image_h=image_h,
                    rationale="One head patch covers hair, ornaments, ears and head contour; do not split those into separate generations.",
                )
            if planned_face is not None and face_h >= 0.10:
                append_candidate(
                    candidates,
                    region_type="face",
                    crop=planned_face,
                    subject_box=face_box,
                    image_w=image_w,
                    image_h=image_h,
                    rationale="Complete face patch keeps forehead, cheeks, jawline and chin together for identity-safe detail.",
                )
            elif face_box is not None:
                skipped.append({"region_type": "face", "reason": "face_scale_below_separate_patch_threshold; head patch is preferred"})

        # Auxiliary hand/prop calls are intentionally expensive. Balanced normally
        # skips them; max considers only candidates that are visibly non-trivial.
        for box in hand_boxes:
            if detail_budget != "max":
                skipped.append({"region_type": "hand", "reason": "auxiliary_patch_reserved_for_max_budget"})
                continue
            expanded = box.expand(image_w, image_h, left=0.18, top=0.18, right=0.18, bottom=0.18)
            append_candidate(
                candidates,
                region_type="hand",
                crop=expanded,
                subject_box=box,
                image_w=image_w,
                image_h=image_h,
                rationale="Large important hand gets one coarse patch in max mode; fingers are never split into separate generations.",
            )
        for box in prop_boxes:
            if detail_budget != "max":
                skipped.append({"region_type": "prop", "reason": "auxiliary_patch_reserved_for_max_budget"})
                continue
            expanded = box.expand(image_w, image_h, left=0.12, top=0.12, right=0.12, bottom=0.12)
            append_candidate(
                candidates,
                region_type="prop",
                crop=expanded,
                subject_box=box,
                image_w=image_w,
                image_h=image_h,
                rationale="Important prop remains one broad object patch; do not split object parts into separate generations.",
            )
    else:
        # Landscape/architecture does not automatically spend calls on the entire
        # frame. A caller/vision pass must identify a meaningful subject region.
        if subject_box is not None:
            region_type = "architecture" if subject_type == "architecture" else "generic"
            crop = subject_box.expand(image_w, image_h, left=0.08, top=0.08, right=0.08, bottom=0.08)
            append_candidate(
                candidates,
                region_type=region_type,
                crop=crop,
                subject_box=subject_box,
                image_w=image_w,
                image_h=image_h,
                rationale="Use one broad high-value scene region; no automatic tiling of the whole landscape/background.",
            )
        else:
            skipped.append({"region_type": "generic", "reason": "no_high_value_region_identified; use LOOK MASTER without local generation"})

    # Filter by value first, then choose the best few. The ceiling is never treated
    # as a target count. Preserve blend order only after selection.
    worthy = []
    for candidate in candidates:
        if candidate["value_score"] >= threshold:
            worthy.append(candidate)
        else:
            skipped.append({
                "region_type": candidate["region_type"],
                "value_score": candidate["value_score"],
                "reason": f"below_{detail_budget}_value_threshold_{threshold:.2f}",
            })
    selected_by_value = sorted(worthy, key=lambda item: (-item["value_score"], item["blend_order"]))[:max_patches]
    selected_ids = {(item["region_type"], tuple(item["crop"].values())) for item in selected_by_value}
    for candidate in worthy:
        key = (candidate["region_type"], tuple(candidate["crop"].values()))
        if key not in selected_ids:
            skipped.append({"region_type": candidate["region_type"], "value_score": candidate["value_score"], "reason": "generation_budget_ceiling_reached"})
    regions = sorted(selected_by_value, key=lambda item: item["blend_order"])

    return {
        "subject_type": subject_type,
        "detail_budget": detail_budget,
        "max_generated_patches": max_patches,
        "estimated_generated_patches": len(regions),
        "region_count": len(regions),
        "regions": regions,
        "skipped_candidates": skipped,
        "planner": "adaptive-value-merge-v2",
        "value_threshold": threshold,
        "principle": "generation_budget_is_a_ceiling; prefer_merging_regions_over_splitting_them",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan coarse Photo Refiner v2.2 detail tiles with a generation ceiling.")
    parser.add_argument("--image", type=Path, required=True, help="Reference image used for dimensions")
    parser.add_argument("--subject-type", choices=["portrait", "classical-portrait", "landscape", "architecture", "generic"], default="portrait")
    parser.add_argument("--detail-budget", choices=sorted(BUDGET_LIMITS), default="balanced")
    parser.add_argument("--face-box", type=parse_box)
    parser.add_argument("--subject-box", type=parse_box)
    parser.add_argument("--hand-box", action="append", type=parse_box, default=[])
    parser.add_argument("--prop-box", action="append", type=parse_box, default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    image = args.image.expanduser().resolve()
    if not image.is_file():
        raise SystemExit(f"Missing image: {image}")
    image_w, image_h = read_image_size(image)
    plan = build_plan(
        image_w,
        image_h,
        subject_type=args.subject_type,
        detail_budget=args.detail_budget,
        face_box=args.face_box.clip(image_w, image_h) if args.face_box else None,
        subject_box=args.subject_box.clip(image_w, image_h) if args.subject_box else None,
        hand_boxes=[box.clip(image_w, image_h) for box in args.hand_box],
        prop_boxes=[box.clip(image_w, image_h) for box in args.prop_box],
    )
    rendered = json.dumps(plan, indent=2, ensure_ascii=False)
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
