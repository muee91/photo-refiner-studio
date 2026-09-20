#!/usr/bin/env python3
"""Single source of truth for the Photo Refiner job contract.

Two things live here because they were previously restated (and had drifted) in
`init_job.py`, `plan_detail_tiles.py`, `pixel_budget.py` and `SKILL.md`:

1. Generation budgets and Pixel Budget thresholds.
2. The rules that turn a settings-panel confirmation into validated job settings.

Canvases
--------
A job has two different pixel spaces and conflating them is what let a 1024x1536
composite be delivered as a 4672x7008 "high resolution" file:

- `working_canvas`  the approved LOOK MASTER / CREATIVE LOOK MASTER the patches are
                     composited onto; every region coordinate lives in this space.
- `delivery_canvas` the size the file is finally delivered at.

`delivery_scale = delivery_width / working_width` is how much of the deliverable is
interpolation rather than recovered detail.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from dataclasses import dataclass

ASPECT_RATIO_RE = re.compile(r"^[1-9]\d*:[1-9]\d*$")
RESOLUTION_RE = re.compile(r"^[1-9]\d*x[1-9]\d*$", re.IGNORECASE)

# Generation budgets are ceilings, never quotas.
BUDGET_POLICY = {
    "fast": {"soft": 1, "hard": 1, "threshold": 0.50, "overflow_threshold": 1.01},
    "balanced": {"soft": 3, "hard": 6, "threshold": 0.38, "overflow_threshold": 0.50},
    "max": {"soft": 5, "hard": 8, "threshold": 0.24, "overflow_threshold": 0.36},
}

# Creative-safe recovery is capped tighter than normal refinement, and the cap
# expands with portrait coverage so lower garments/hands/props are not omitted
# without degenerating into micro-patch tiling.
CREATIVE_SAFE_STAGE_POLICY = {
    "close": {"soft": 2, "hard": 3},
    "half": {"soft": 2, "hard": 3},
    "full": {"soft": 3, "hard": 4},
    "complex-full": {"soft": 4, "hard": 5},
    "scene": {"soft": 2, "hard": 3},
}
CREATIVE_SAFE_BUDGET_LIMITS = {"fast": 2, "balanced": 5, "max": 5}

PORTRAIT_EXTENTS = {"close", "half", "full", "complex-full"}
DETAIL_COMPLEXITIES = {"normal", "complex"}
RECOVERY_PROFILES = {"normal", "creative-safe"}

# The single source of truth for the product version. Everything that names a
# version (job.json release_version, planner ids, SKILL.md heading, config-schema)
# must agree with this constant; a test enforces that. Record formats carried
# alongside it (`version: 2` in job.json/presets.yaml, `schema_version` in vision
# analysis, observations and gate reports) are per-artifact schemas and evolve
# independently on purpose.
SKILL_VERSION = "2.4"
RELEASE_VERSION = SKILL_VERSION

PLANNER_NORMAL = f"adaptive-value-merge-v{SKILL_VERSION}"
PLANNER_CREATIVE_SAFE = f"adaptive-value-merge-v{SKILL_VERSION}-creative-safe"


PIXEL_BUDGET_THRESHOLDS = {
    "face": 0.85,
    "hand": 0.75,
    "head": 0.65,
    "costume": 0.50,
    "prop": 0.50,
    "architecture": 0.50,
    "background": 0.30,
    "generic": 0.50,
}
REGION_TYPES = tuple(sorted(PIXEL_BUDGET_THRESHOLDS))

# A deliverable may not exceed its working canvas by more than this without a
# passing delivery gate; below it, resize is a resampling detail-neutral crop or
# a rounding difference rather than an invented-resolution claim.
MAX_HONEST_UPSCALE = 1.05


def normal_budget(detail_budget: str) -> tuple[int, int]:
    policy = BUDGET_POLICY[detail_budget]
    return policy["soft"], policy["hard"]


def creative_safe_policy(detail_budget: str, portrait_extent: str, detail_complexity: str) -> dict:
    """Operative soft/hard ceilings plus value thresholds for one creative-safe job."""
    if portrait_extent not in CREATIVE_SAFE_STAGE_POLICY:
        portrait_extent = "half"
    if detail_complexity == "complex" and portrait_extent == "full":
        portrait_extent = "complex-full"
    stage = CREATIVE_SAFE_STAGE_POLICY[portrait_extent]
    base = BUDGET_POLICY[detail_budget]
    if detail_budget == "fast":
        soft = min(stage["soft"], 1)
        hard = min(stage["hard"], 2)
    elif detail_budget == "max":
        soft = min(stage["soft"] + 1, 5)
        hard = min(stage["hard"] + 1, 5)
    else:
        soft, hard = stage["soft"], stage["hard"]
    overflow = {"fast": 1.01, "max": 0.42}.get(detail_budget, 0.46)
    return {
        "soft": soft,
        "hard": hard,
        "threshold": max(base["threshold"], 0.34),
        "overflow_threshold": overflow,
    }


def creative_safe_budget(detail_budget: str, portrait_extent: str) -> tuple[int, int]:
    policy = creative_safe_policy(detail_budget, portrait_extent, "normal")
    return policy["soft"], policy["hard"]


def creative_safe_ceiling(detail_budget: str) -> int:
    """Absolute creative-safe ceiling; never a per-region permission."""
    return CREATIVE_SAFE_BUDGET_LIMITS[detail_budget]


def fit_patch_size(crop_width: int, crop_height: int, cap: tuple[int, int]) -> tuple[int, int]:
    """Largest patch at the region's own aspect that fits the observed return cap.

    The client returns fewer pixels than were requested (`register_blend.py`
    enforces the region aspect), so planning must size candidates against what
    this runtime has actually been observed to hand back.
    """
    cap_w, cap_h = cap
    aspect = crop_width / crop_height
    width = min(cap_w, (cap_w * cap_h * aspect) ** 0.5)
    height = width / aspect
    if height > cap_h:
        height = cap_h
        width = height * aspect
    return max(1, round(width)), max(1, round(height))


def delivery_headroom_width(
    crop_size: tuple[int, int],
    region_type: str,
    working_width: int,
    observed_patch_size: tuple[int, int],
    threshold: float | None = None,
) -> float:
    """Widest delivery canvas this region can honestly serve.

    The detail ratio reduces to `patch / (region footprint in the delivered file)`,
    so it is independent of how large the working canvas is: raising the canvas
    raises the region's coordinates by the same factor. That is why 4X improves the
    areas without patches but cannot feed a subject region that a single patch has
    already outgrown.
    """
    crop_w, crop_h = crop_size
    patch_w, patch_h = fit_patch_size(crop_w, crop_h, observed_patch_size)
    limit = pixel_budget_threshold(region_type) if threshold is None else threshold
    scale = min((patch_w / crop_w) / limit, (patch_h / crop_h) / limit)
    return working_width * scale


def tiles_for_span(
    span: tuple[int, int],
    tile_size: tuple[int, int],
    threshold: float,
    overlap: float = 0.15,
) -> int:
    """Tiles needed to cover a delivery-space span at one region type's threshold.

    A tile of `t` generated pixels honestly serves `t / threshold` delivered
    pixels, so grid density follows the region's own threshold rather than an
    assumed 1:1 pixel mapping: costume at 0.50 needs far fewer tiles than a face
    at 0.85 across the same area.
    """
    def axis(span_px: int, tile_px: int) -> int:
        reach = tile_px / max(threshold, 0.01)
        if span_px <= reach:
            return 1
        step = max(1.0, reach * (1 - overlap))
        return math.ceil((span_px - reach) / step) + 1
    return axis(span[0], tile_size[0]) * axis(span[1], tile_size[1])


def pixel_budget_threshold(region_type: str) -> float:
    return PIXEL_BUDGET_THRESHOLDS[region_type]


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write a job manifest without letting two writers clobber one temp file."""
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


@dataclass
class Canvas:
    width: int
    height: int

    @property
    def aspect(self) -> float:
        return self.width / self.height


@dataclass
class RegionGeometry:
    """A working-canvas box: x,y,width,height."""

    x: int
    y: int
    width: int
    height: int

    @classmethod
    def from_flag(cls, value: str) -> "RegionGeometry":
        parts = value.replace(" ", "").split(",")
        if len(parts) != 4:
            raise argparse.ArgumentTypeError("Region box must be X,Y,WIDTH,HEIGHT")
        try:
            x, y, width, height = (int(part) for part in parts)
        except ValueError:
            raise argparse.ArgumentTypeError("Region box values must be integers") from None
        if width <= 0 or height <= 0 or x < 0 or y < 0:
            raise argparse.ArgumentTypeError("Region box needs non-negative x/y and positive width/height")
        return cls(x, y, width, height)


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("Size must be WIDTHxHEIGHT") from None
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("Dimensions must be positive")
    return width, height


def delivery_scale(working: Canvas, delivery: Canvas) -> float:
    return delivery.width / working.width


@dataclass
class DetailRatio:
    width: float
    height: float
    minimum: float
    threshold: float
    accepted: bool
    action: str
    occupancy_w: float
    occupancy_h: float
    effective_w: float
    effective_h: float
    delivery_subject_w: float
    delivery_subject_h: float


def effective_detail_ratio(
    patch_size: tuple[int, int],
    region_crop_size: tuple[int, int],
    region_subject_size: tuple[int, int],
    working: Canvas,
    delivery: Canvas,
    region_type: str,
    threshold: float | None = None,
) -> DetailRatio:
    """Project generated subject pixels onto the subject's delivery-space footprint.

    Every region measurement is taken in working-canvas space and scaled here, so a
    caller cannot accidentally compare working-canvas coordinates against a patch
    that has to serve the delivery canvas.
    """
    scale = delivery_scale(working, delivery)
    crop_w, crop_h = region_crop_size
    subject_w, subject_h = region_subject_size
    occupancy_w, occupancy_h = subject_w / crop_w, subject_h / crop_h
    effective_w = patch_size[0] * occupancy_w
    effective_h = patch_size[1] * occupancy_h
    final_w = subject_w * scale
    final_h = subject_h * scale
    ratio_w = effective_w / final_w
    ratio_h = effective_h / final_h
    minimum = min(ratio_w, ratio_h)
    limit = pixel_budget_threshold(region_type) if threshold is None else threshold
    if minimum >= limit:
        action = "accept"
    elif max(occupancy_w, occupancy_h) < 0.55:
        action = "tighten_crop"
    else:
        action = "request_larger_patch_or_reduce_final_scale"
    return DetailRatio(
        width=ratio_w,
        height=ratio_h,
        minimum=minimum,
        threshold=limit,
        accepted=minimum >= limit,
        action=action,
        occupancy_w=occupancy_w,
        occupancy_h=occupancy_h,
        effective_w=effective_w,
        effective_h=effective_h,
        delivery_subject_w=final_w,
        delivery_subject_h=final_h,
    )


WORKFLOW_VALUES = ("auto", "single", "batch")
FRAMING_VALUES = ("preserve", "crop", "outpaint", "contain")
OUTPUT_FORMAT_VALUES = ("png", "jpg", "both")
CONSISTENCY_VALUES = ("strict", "balanced", "creative")
DELIVERY_MODE_VALUES = ("preview-first", "one-click", "base-only")
UI_MODE_VALUES = ("simple", "professional")
DETAIL_MODE_VALUES = ("base-only", "face", "adaptive", "explicit")
GENERATION_BUDGET_VALUES = tuple(BUDGET_POLICY)
DETAIL_PATCH_SCOPE_VALUES = ("head-and-face", "face-only", "custom", "adaptive-subject")
CREATIVE_ASSEMBLY_MODE_VALUES = ("direct-effect", "original-assembly")
ASPECT_RATIO_KEYWORDS = ("original",)
RESOLUTION_KEYWORDS = ("preview", "4k", "source-width")

# Settings-panel key -> (job manifest key, validator name). The panel is the primary
# way a job is configured, so every field it can carry is validated here rather than
# relying on argparse, which never sees confirmation-supplied values.
PANEL_SETTINGS = (
    ("workflow", "workflow", "enum:workflow"),
    ("uiMode", "ui_mode", "enum:ui_mode"),
    ("aspectRatio", "aspect_ratio", "aspect_ratio"),
    ("framing", "framing", "enum:framing"),
    ("resolution", "resolution", "resolution"),
    ("deliveryMode", "delivery_mode", "enum:delivery_mode"),
    ("outputFormat", "output_format", "enum:output_format"),
    ("keepIntermediates", "keep_intermediates", "bool"),
    ("creativeAssemblyMode", "creative_assembly_mode", "enum:creative_assembly_mode"),
    (("batch", "consistency"), "consistency", "enum:consistency"),
    (("detail", "mode"), "detail_mode", "enum:detail_mode"),
    (("detail", "generationBudget"), "generation_budget", "enum:generation_budget"),
    (("detail", "patchScope"), "patch_scope", "enum:patch_scope"),
    (("detail", "strength"), "detail_strength", "percent"),
    (("detail", "regions"), "detail_regions", "text"),
    ("styleStrength", "style_strength", "percent"),
    ("customPrompt", "custom_prompt", "text"),
    ("customAvoid", "custom_avoid", "text"),
)

_ENUMS = {
    "enum:workflow": WORKFLOW_VALUES,
    "enum:ui_mode": UI_MODE_VALUES,
    "enum:framing": FRAMING_VALUES,
    "enum:output_format": OUTPUT_FORMAT_VALUES,
    "enum:delivery_mode": DELIVERY_MODE_VALUES,
    "enum:consistency": CONSISTENCY_VALUES,
    "enum:detail_mode": DETAIL_MODE_VALUES,
    "enum:generation_budget": GENERATION_BUDGET_VALUES,
    "enum:patch_scope": DETAIL_PATCH_SCOPE_VALUES,
    "enum:creative_assembly_mode": CREATIVE_ASSEMBLY_MODE_VALUES,
}


class SettingError(ValueError):
    """A confirmed setting cannot be used; named so the caller can report the field."""

    def __init__(self, field: str, value, allowed, target: str | None = None):
        self.field = field
        shown = ".".join(field) if isinstance(field, tuple) else field
        where = f"{shown} (job.{target})" if target and target != shown else shown
        self.message = f"Confirmed setting {where}={value!r} is not supported; expected one of: {allowed}"
        super().__init__(self.message)


def _panel_get(config: dict, key):
    if isinstance(key, tuple):
        node = config
        for part in key:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node
    return config.get(key)


def validate_setting(field, value, kind, required: bool = True):
    """Return the canonical value, or raise SettingError naming the offending field."""
    if value is None:
        if required:
            raise SettingError(field, value, f"a value for {'.'.join(field) if isinstance(field, tuple) else field}")
        return None
    if kind == "bool":
        if not isinstance(value, bool):
            raise SettingError(field, value, "true or false")
        return value
    if kind == "text":
        if not isinstance(value, str):
            raise SettingError(field, value, "a string")
        return value.strip()
    if kind == "percent":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise SettingError(field, value, "a number between 0 and 100")
        return value
    if kind.startswith("enum:"):
        allowed = _ENUMS[kind]
        if value not in allowed:
            raise SettingError(field, value, ", ".join(allowed))
        return value
    if kind == "aspect_ratio":
        if not isinstance(value, str) or not (value in ASPECT_RATIO_KEYWORDS or ASPECT_RATIO_RE.fullmatch(value)):
            raise SettingError(field, value, "original or W:H")
        return value
    if kind == "resolution":
        if not isinstance(value, str):
            raise SettingError(field, value, ", ".join(RESOLUTION_KEYWORDS) + " or WIDTHxHEIGHT")
        lowered = value.lower()
        if lowered in RESOLUTION_KEYWORDS or RESOLUTION_RE.fullmatch(lowered):
            return lowered
        raise SettingError(field, value, ", ".join(RESOLUTION_KEYWORDS) + " or WIDTHxHEIGHT")
    raise AssertionError(f"unknown setting kind {kind}")


def validated_panel_settings(config: dict) -> dict:
    """Validate everything the panel can carry in one pass.

    Returns job-manifest keyed settings. `styleStrength` and `preset` are handled by
    the prompt resolver, which already binds them to the confirmation hash.
    """
    settings = {}
    for field, target, kind in PANEL_SETTINGS:
        optional = target in {"generation_budget", "patch_scope", "detail_regions", "detail_strength",
                              "custom_prompt", "custom_avoid", "creative_assembly_mode", "keep_intermediates"}
        value = _panel_get(config, field)
        if value is None and optional:
            settings[target] = None
            continue
        try:
            settings[target] = validate_setting(field, value, kind, required=not optional)
        except SettingError as exc:
            raise SettingError(field, value, str(exc).split(": ", 1)[-1], target=target) from None
    return settings
