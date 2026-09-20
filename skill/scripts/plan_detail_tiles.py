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
from typing import Any, Iterable

from PIL import Image


BUDGET_POLICY = {
    "fast": {"soft": 1, "hard": 1, "threshold": 0.50, "overflow_threshold": 1.01},
    "balanced": {"soft": 3, "hard": 6, "threshold": 0.38, "overflow_threshold": 0.50},
    "max": {"soft": 5, "hard": 8, "threshold": 0.24, "overflow_threshold": 0.36},
}
# Creative-safe recovery is intentionally capped more tightly than normal
# refinement. The cap expands with portrait coverage so full-body work can
# protect lower garments/hands/props without turning into micro-patch tiling.
CREATIVE_SAFE_STAGE_POLICY = {
    "close": {"soft": 2, "hard": 3},
    "half": {"soft": 2, "hard": 3},
    "full": {"soft": 3, "hard": 4},
    "complex-full": {"soft": 4, "hard": 5},
    "scene": {"soft": 2, "hard": 3},
}
PORTRAIT_EXTENTS = {"close", "half", "full", "complex-full"}
DETAIL_COMPLEXITIES = {"normal", "complex"}
RECOVERY_PROFILES = {"normal", "creative-safe"}
BUDGET_LIMITS = {name: policy["hard"] for name, policy in BUDGET_POLICY.items()}
BASE_VALUE = {
    "face": 1.00,
    "head": 0.78,
    "hand": 0.70,
    "costume": 0.62,
    "prop": 0.58,
    "architecture": 0.58,
    "generic": 0.50,
}
BUDGET_THRESHOLDS = {name: policy["threshold"] for name, policy in BUDGET_POLICY.items()}
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


VISION_SUBJECT_TYPES = {"portrait", "classical-portrait", "landscape", "architecture", "generic"}


def _analysis_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Vision analysis field {field} must be a finite number")
    return float(value)


def _analysis_box(value: Any, *, coordinate_space: str, image_w: int, image_h: int, field: str) -> Box:
    """Convert a Vision result box into the planner's pixel-space Box."""
    if isinstance(value, dict) and "box" in value:
        value = value["box"]
    if not isinstance(value, dict) or not all(key in value for key in ("x", "y", "width", "height")):
        raise ValueError(f"Vision analysis field {field} must contain x, y, width, height")
    x = _analysis_number(value["x"], f"{field}.x")
    y = _analysis_number(value["y"], f"{field}.y")
    width = _analysis_number(value["width"], f"{field}.width")
    height = _analysis_number(value["height"], f"{field}.height")
    if coordinate_space == "normalized":
        if min(x, y, width, height) < 0 or max(x, y, width, height) > 1:
            raise ValueError(f"Vision analysis field {field} must use values from 0 to 1 in normalized space")
        x, width = x * image_w, width * image_w
        y, height = y * image_h, height * image_h
    elif coordinate_space != "pixel":
        raise ValueError("Vision analysis coordinate_space must be pixel or normalized")
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"Vision analysis field {field} must use a non-negative origin and positive size")
    return Box(round(x), round(y), max(1, round(width)), max(1, round(height))).clip(image_w, image_h)


def load_vision_analysis(path: Path, image_w: int, image_h: int) -> dict:
    """Load the stable Vision -> Planner handoff contract.

    The file contains a subject type and coarse regions. Coordinates may be pixels
    or normalized fractions, but the coordinate space must be explicit.
    """
    try:
        payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Cannot read Vision analysis: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Vision analysis is not valid JSON: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Vision analysis schema_version must be 1")
    subject_type = payload.get("subject_type")
    if subject_type not in VISION_SUBJECT_TYPES:
        raise ValueError(f"Vision analysis subject_type must be one of: {', '.join(sorted(VISION_SUBJECT_TYPES))}")
    coordinate_space = payload.get("coordinate_space", "pixel")
    portrait_extent = payload.get("portrait_extent")
    if portrait_extent is not None and portrait_extent not in PORTRAIT_EXTENTS:
        raise ValueError(f"Vision analysis portrait_extent must be one of: {', '.join(sorted(PORTRAIT_EXTENTS))}")
    detail_complexity = payload.get("detail_complexity", "normal")
    if detail_complexity not in DETAIL_COMPLEXITIES:
        raise ValueError(f"Vision analysis detail_complexity must be one of: {', '.join(sorted(DETAIL_COMPLEXITIES))}")
    regions = payload.get("regions")
    if not isinstance(regions, dict):
        raise ValueError("Vision analysis regions must be an object")

    def optional_box(name: str) -> Box | None:
        value = regions.get(name)
        return None if value is None else _analysis_box(value, coordinate_space=coordinate_space, image_w=image_w, image_h=image_h, field=f"regions.{name}")

    def box_list(name: str) -> list[Box]:
        values = regions.get(name, [])
        if not isinstance(values, list):
            raise ValueError(f"Vision analysis regions.{name} must be an array")
        return [
            _analysis_box(value, coordinate_space=coordinate_space, image_w=image_w, image_h=image_h, field=f"regions.{name}[{index}]")
            for index, value in enumerate(values)
        ]

    return {
        "schema_version": 1,
        "coordinate_space": coordinate_space,
        "subject_type": subject_type,
        "portrait_extent": portrait_extent,
        "detail_complexity": detail_complexity,
        "subject_box": optional_box("subject"),
        "face_box": optional_box("face"),
        "hand_boxes": box_list("hands"),
        "prop_boxes": box_list("props"),
    }


def read_image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.width, image.height


def area_fraction(box: Box | None, image_w: int, image_h: int) -> float:
    return 0.0 if box is None else box.area / float(image_w * image_h)


def height_fraction(box: Box | None, image_h: int) -> float:
    return 0.0 if box is None else box.height / float(image_h)


def infer_portrait_extent(
    subject_box: Box | None,
    face_box: Box | None,
    image_h: int,
    hand_boxes: Iterable[Box],
    prop_boxes: Iterable[Box],
) -> str:
    """Infer coarse portrait coverage when Vision does not supply it.

    Face-to-subject height is a stable proxy for close/half/full framing. A
    complex-full classification is only inferred when a full figure also has
    multiple high-value auxiliaries; Vision may provide it explicitly.
    """
    if subject_box is None or face_box is None:
        return "half"
    face_to_subject = face_box.height / float(max(1, subject_box.height))
    subject_h = subject_box.height / float(max(1, image_h))
    if face_to_subject <= 0.18 and subject_h >= 0.52:
        extent = "full"
    elif face_to_subject <= 0.30:
        extent = "half"
    else:
        extent = "close"
    if extent == "full":
        auxiliary_count = len(list(hand_boxes)) + len(list(prop_boxes))
        if auxiliary_count >= 3:
            return "complex-full"
    return extent


def creative_safe_policy(detail_budget: str, extent: str, detail_complexity: str) -> dict:
    if extent not in CREATIVE_SAFE_STAGE_POLICY:
        extent = "half"
    if detail_complexity == "complex" and extent == "full":
        extent = "complex-full"
    stage = CREATIVE_SAFE_STAGE_POLICY[extent]
    base = BUDGET_POLICY[detail_budget]
    if detail_budget == "fast":
        soft = min(stage["soft"], 1)
        hard = min(stage["hard"], 2)
    elif detail_budget == "max":
        soft = min(stage["soft"] + 1, 5)
        hard = min(stage["hard"] + 1, 5)
    else:
        soft = stage["soft"]
        hard = stage["hard"]
    creative_overflow_threshold = 1.01 if detail_budget == "fast" else (0.42 if detail_budget == "max" else 0.46)
    return {
        "soft": soft,
        "hard": hard,
        "threshold": max(base["threshold"], 0.34),
        "overflow_threshold": creative_overflow_threshold,
    }


def make_costume_box(subject_box: Box | None, image_w: int, image_h: int) -> Box | None:
    if subject_box is None:
        return None
    return subject_box.expand(image_w, image_h, left=0.08, top=0.05, right=0.08, bottom=0.10)


def make_upper_costume_box(subject_box: Box | None, image_w: int, image_h: int) -> Box | None:
    if subject_box is None:
        return None
    top = subject_box.y + round(subject_box.height * 0.10)
    height = max(1, round(subject_box.height * 0.52))
    return Box(subject_box.x, top, subject_box.width, height).expand(
        image_w, image_h, left=0.10, top=0.08, right=0.10, bottom=0.08
    )


def make_lower_costume_box(subject_box: Box | None, image_w: int, image_h: int) -> Box | None:
    if subject_box is None:
        return None
    top = subject_box.y + round(subject_box.height * 0.44)
    height = max(1, subject_box.bottom - top)
    return Box(subject_box.x, top, subject_box.width, height).expand(
        image_w, image_h, left=0.10, top=0.08, right=0.10, bottom=0.12
    )


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


def append_candidate(candidates: list[dict], *, region_type: str, crop: Box, subject_box: Box, image_w: int, image_h: int, rationale: str, importance: float = 1.0, region_role: str | None = None) -> None:
    score = candidate_value(region_type, subject_box, image_w, image_h, importance=importance)
    candidate = {
        "region_type": region_type,
        "region_role": region_role or region_type,
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
    recovery_profile: str = "normal",
    portrait_extent: str | None = None,
    detail_complexity: str = "normal",
) -> dict:
    if recovery_profile not in RECOVERY_PROFILES:
        raise ValueError(f"Unknown recovery profile: {recovery_profile}")
    if detail_complexity not in DETAIL_COMPLEXITIES:
        raise ValueError(f"Unknown detail complexity: {detail_complexity}")
    hand_boxes = list(hand_boxes)
    prop_boxes = list(prop_boxes)
    portrait_like = subject_type in {"portrait", "classical-portrait"}
    resolved_extent = portrait_extent
    if portrait_like:
        resolved_extent = resolved_extent or infer_portrait_extent(subject_box, face_box, image_h, hand_boxes, prop_boxes)
        if detail_complexity == "complex" and resolved_extent == "full":
            resolved_extent = "complex-full"
    elif recovery_profile == "creative-safe":
        resolved_extent = "scene"

    policy = (
        creative_safe_policy(detail_budget, resolved_extent or "half", detail_complexity)
        if recovery_profile == "creative-safe"
        else BUDGET_POLICY[detail_budget]
    )
    soft_patches = policy["soft"]
    hard_patches = policy["hard"]
    threshold = policy["threshold"]
    overflow_threshold = policy["overflow_threshold"]
    candidates: list[dict] = []
    skipped: list[dict] = []
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
                if recovery_profile == "creative-safe" and resolved_extent in {"full", "complex-full"}:
                    upper_costume = make_upper_costume_box(subject_box, image_w, image_h)
                    lower_costume = make_lower_costume_box(subject_box, image_w, image_h)
                    if upper_costume is not None:
                        append_candidate(
                            candidates,
                            region_type="costume",
                            region_role="upper-costume",
                            crop=upper_costume,
                            subject_box=upper_costume,
                            image_w=image_w,
                            image_h=image_h,
                            importance=1.20,
                            rationale="Creative-safe full-body recovery keeps the upper costume as one broad style-preserving patch.",
                        )
                    if lower_costume is not None:
                        append_candidate(
                            candidates,
                            region_type="costume",
                            region_role="lower-costume",
                            crop=lower_costume,
                            subject_box=lower_costume,
                            image_w=image_w,
                            image_h=image_h,
                            importance=1.24,
                            rationale="Creative-safe full-body recovery reserves a separate lower-garment patch so skirts, robes and legs are not omitted.",
                        )
                else:
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

        # Hands/props are auxiliary candidates. Fast never spends calls on them.
        # Balanced may exceed its soft budget only for large/high-value auxiliaries;
        # max is more permissive but still obeys a hard ceiling.
        for box in hand_boxes:
            if detail_budget == "fast":
                skipped.append({"region_type": "hand", "reason": "auxiliary_patch_disabled_in_fast_budget"})
                continue
            expanded = box.expand(image_w, image_h, left=0.18, top=0.18, right=0.18, bottom=0.18)
            append_candidate(
                candidates,
                region_type="hand",
                crop=expanded,
                subject_box=box,
                image_w=image_w,
                image_h=image_h,
                importance=1.20,
                rationale="Important hand remains one coarse patch; fingers are never split into separate generations.",
            )
        for box in prop_boxes:
            if detail_budget == "fast":
                skipped.append({"region_type": "prop", "reason": "auxiliary_patch_disabled_in_fast_budget"})
                continue
            expanded = box.expand(image_w, image_h, left=0.12, top=0.12, right=0.12, bottom=0.12)
            append_candidate(
                candidates,
                region_type="prop",
                crop=expanded,
                subject_box=box,
                image_w=image_w,
                image_h=image_h,
                importance=1.15,
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

    # Filter by value first. The soft budget is the normal envelope, not a quota.
    # High-value leftovers may overflow to the hard ceiling. For portraits, core
    # broad regions are protected from being displaced by hands/props in the first
    # three balanced slots.
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

    ranked = sorted(worthy, key=lambda item: (-item["value_score"], item["blend_order"]))
    core_types = {"costume", "head", "face", "architecture", "generic"}
    core = [item for item in ranked if item["region_type"] in core_types]
    auxiliary = [item for item in ranked if item["region_type"] not in core_types]

    selected_by_value = core[:soft_patches]
    if len(selected_by_value) < soft_patches:
        selected_by_value.extend(auxiliary[:soft_patches - len(selected_by_value)])

    selected_keys = {(item["region_type"], tuple(item["crop"].values())) for item in selected_by_value}
    remaining = [
        item for item in ranked
        if (item["region_type"], tuple(item["crop"].values())) not in selected_keys
    ]
    overflow_slots = max(0, hard_patches - len(selected_by_value))
    overflow = [
        item for item in remaining
        if item["value_score"] >= overflow_threshold
    ][:overflow_slots]
    selected_by_value.extend(overflow)

    selected_ids = {(item["region_type"], tuple(item["crop"].values())) for item in selected_by_value}
    for candidate in worthy:
        key = (candidate["region_type"], tuple(candidate["crop"].values()))
        if key in selected_ids:
            continue
        reason = (
            f"below_overflow_threshold_{overflow_threshold:.2f}"
            if candidate["value_score"] < overflow_threshold and len(selected_by_value) >= soft_patches
            else "hard_generation_ceiling_reached"
        )
        skipped.append({
            "region_type": candidate["region_type"],
            "value_score": candidate["value_score"],
            "reason": reason,
        })
    regions = sorted(selected_by_value, key=lambda item: item["blend_order"])
    overflow_count = max(0, len(regions) - soft_patches)

    return {
        "subject_type": subject_type,
        "recovery_profile": recovery_profile,
        "portrait_extent": resolved_extent,
        "detail_complexity": detail_complexity,
        "detail_budget": detail_budget,
        "soft_generated_patch_budget": soft_patches,
        "hard_generated_patch_ceiling": hard_patches,
        "max_generated_patches": hard_patches,
        "estimated_generated_patches": len(regions),
        "overflow_generated_patches": overflow_count,
        "adaptive_overflow_used": overflow_count > 0,
        "region_count": len(regions),
        "regions": regions,
        "skipped_candidates": skipped,
        "planner": "adaptive-value-merge-v2.4-creative-safe" if recovery_profile == "creative-safe" else "adaptive-value-merge-v2.2",
        "value_threshold": threshold,
        "overflow_value_threshold": overflow_threshold,
        "principle": "soft_budget_is_normal; high_value_regions_may_overflow_to_hard_ceiling; prefer_merging_over_splitting",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan coarse Photo Refiner v2.2 detail tiles with a soft generation budget and adaptive hard ceiling.")
    parser.add_argument("--image", type=Path, required=True, help="Reference image used for dimensions")
    parser.add_argument("--subject-type", choices=sorted(VISION_SUBJECT_TYPES), help="Subject type; Vision analysis supplies this when omitted")
    parser.add_argument("--detail-budget", choices=sorted(BUDGET_LIMITS), default="balanced")
    parser.add_argument("--recovery-profile", choices=sorted(RECOVERY_PROFILES), default="normal")
    parser.add_argument("--portrait-extent", choices=sorted(PORTRAIT_EXTENTS))
    parser.add_argument("--detail-complexity", choices=sorted(DETAIL_COMPLEXITIES), default="normal")
    parser.add_argument("--face-box", type=parse_box)
    parser.add_argument("--subject-box", type=parse_box)
    parser.add_argument("--hand-box", action="append", type=parse_box, default=[])
    parser.add_argument("--prop-box", action="append", type=parse_box, default=[])
    parser.add_argument(
        "--vision-analysis",
        type=Path,
        help="JSON file from the Vision pass; supplies subject_type and coarse subject/face/hands/props regions",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    image = args.image.expanduser().resolve()
    if not image.is_file():
        raise SystemExit(f"Missing image: {image}")
    image_w, image_h = read_image_size(image)
    analysis = None
    if args.vision_analysis:
        try:
            analysis = load_vision_analysis(args.vision_analysis, image_w, image_h)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    subject_type = args.subject_type or (analysis["subject_type"] if analysis else "portrait")
    face_box = args.face_box or (analysis["face_box"] if analysis else None)
    subject_box = args.subject_box or (analysis["subject_box"] if analysis else None)
    hand_boxes = args.hand_box or (analysis["hand_boxes"] if analysis else [])
    prop_boxes = args.prop_box or (analysis["prop_boxes"] if analysis else [])
    portrait_extent = args.portrait_extent or (analysis["portrait_extent"] if analysis else None)
    detail_complexity = args.detail_complexity
    if analysis and args.detail_complexity == "normal":
        detail_complexity = analysis["detail_complexity"]
    plan = build_plan(
        image_w,
        image_h,
        subject_type=subject_type,
        detail_budget=args.detail_budget,
        face_box=face_box.clip(image_w, image_h) if face_box else None,
        subject_box=subject_box.clip(image_w, image_h) if subject_box else None,
        hand_boxes=[box.clip(image_w, image_h) for box in hand_boxes],
        prop_boxes=[box.clip(image_w, image_h) for box in prop_boxes],
        recovery_profile=args.recovery_profile,
        portrait_extent=portrait_extent,
        detail_complexity=detail_complexity,
    )
    if analysis:
        plan["vision_analysis"] = {
            "schema_version": analysis["schema_version"],
            "coordinate_space": analysis["coordinate_space"],
            "source": str(args.vision_analysis.expanduser().resolve()),
        }
    rendered = json.dumps(plan, indent=2, ensure_ascii=False)
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
