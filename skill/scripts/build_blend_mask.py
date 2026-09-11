#!/usr/bin/env python3
"""Create a lightweight blend mask for a planned detail patch.

This is intentionally not a fine segmentation pipeline. It produces a coarse,
soft-edged mask that helps local blending avoid obvious rectangular seams while
keeping generation counts unchanged.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def parse_box(value: str) -> tuple[int, int, int, int]:
    try:
        x, y, width, height = (int(part.strip()) for part in value.split(",", 3))
    except Exception as exc:
        raise argparse.ArgumentTypeError("Boxes must use x,y,width,height") from exc
    if width <= 0 or height <= 0 or x < 0 or y < 0:
        raise argparse.ArgumentTypeError("Boxes must be non-negative and use positive width/height")
    return x, y, width, height


def rounded_box(mask: np.ndarray, box: tuple[int, int, int, int], radius: int) -> None:
    x, y, width, height = box
    x2, y2 = x + width, y + height
    radius = max(1, min(radius, width // 2, height // 2))
    cv2.rectangle(mask, (x + radius, y), (x2 - radius, y2), 255, thickness=-1)
    cv2.rectangle(mask, (x, y + radius), (x2, y2 - radius), 255, thickness=-1)
    for cx, cy in [(x + radius, y + radius), (x2 - radius, y + radius), (x + radius, y2 - radius), (x2 - radius, y2 - radius)]:
        cv2.circle(mask, (cx, cy), radius, 255, thickness=-1)


def ellipse_mask(mask: np.ndarray, box: tuple[int, int, int, int]) -> None:
    x, y, width, height = box
    center = (x + width // 2, y + height // 2)
    axes = (max(1, width // 2), max(1, height // 2))
    cv2.ellipse(mask, center, axes, 0, 0, 360, 255, thickness=-1)


def clamp_box(box: tuple[int, int, int, int], image_w: int, image_h: int) -> tuple[int, int, int, int]:
    x, y, width, height = box
    x = max(0, min(x, image_w - 1))
    y = max(0, min(y, image_h - 1))
    x2 = max(x + 1, min(x + width, image_w))
    y2 = max(y + 1, min(y + height, image_h))
    return x, y, x2 - x, y2 - y


def expand_box(box: tuple[int, int, int, int], image_w: int, image_h: int, *, left: float, top: float, right: float, bottom: float) -> tuple[int, int, int, int]:
    x, y, width, height = box
    return clamp_box(
        (
            x - round(width * left),
            y - round(height * top),
            width + round(width * (left + right)),
            height + round(height * (top + bottom)),
        ),
        image_w,
        image_h,
    )


def build_mask(width: int, height: int, region_type: str, focus_box: tuple[int, int, int, int] | None = None, mode: str = "auto", blur: float = 0.06) -> tuple[np.ndarray, str, tuple[int, int, int, int]]:
    if width <= 0 or height <= 0:
        raise ValueError("Mask dimensions must be positive")
    if blur < 0 or blur > 0.25:
        raise ValueError("Blur fraction must be between 0 and 0.25")
    mask = np.zeros((height, width), dtype=np.uint8)
    focus = clamp_box(focus_box, width, height) if focus_box else None
    resolved_mode = mode
    if resolved_mode == "auto":
        resolved_mode = "shape-lite" if region_type in {"face", "head", "hand"} else "softbox"
    if resolved_mode == "foreground-lite":
        resolved_mode = "shape-lite"
    if focus is None:
        focus = (round(width * 0.1), round(height * 0.1), round(width * 0.8), round(height * 0.8))

    if region_type == "face":
        shape_box = expand_box(focus, width, height, left=0.10, top=0.12, right=0.10, bottom=0.22)
        ellipse_mask(mask, shape_box)
    elif region_type == "head":
        shape_box = expand_box(focus, width, height, left=0.22, top=0.24, right=0.22, bottom=0.14)
        rounded_box(mask, shape_box, radius=max(12, min(shape_box[2], shape_box[3]) // 6))
    elif region_type == "hand":
        shape_box = expand_box(focus, width, height, left=0.16, top=0.16, right=0.16, bottom=0.16)
        rounded_box(mask, shape_box, radius=max(10, min(shape_box[2], shape_box[3]) // 5))
    else:
        shape_box = expand_box(focus, width, height, left=0.08, top=0.08, right=0.08, bottom=0.08)
        rounded_box(mask, shape_box, radius=max(10, min(shape_box[2], shape_box[3]) // 8))

    if resolved_mode == "shape-lite":
        kernel = np.ones((5, 5), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    blur_sigma = max(1.0, min(width, height) * blur)
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=blur_sigma, sigmaY=blur_sigma)
    return mask, resolved_mode, focus


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a lightweight grayscale blend mask for a detail patch.")
    parser.add_argument("input", type=Path, help="Patch or target image that defines the mask dimensions")
    parser.add_argument("output", type=Path, help="PNG mask output")
    parser.add_argument("--region-type", choices=["face", "head", "hand", "costume", "prop", "architecture", "background", "generic"], default="generic")
    parser.add_argument("--focus-box", type=parse_box, help="Optional x,y,width,height focus box inside the patch")
    parser.add_argument("--mode", choices=["auto", "softbox", "shape-lite", "foreground-lite"], default="auto", help="Geometric mask only; no semantic segmentation. foreground-lite is kept as a compatibility alias for shape-lite.")
    parser.add_argument("--blur", type=float, default=0.06, help="Gaussian blur as a fraction of the shorter image side")
    args = parser.parse_args()

    source = args.input.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Missing input: {source}")
    if source == output:
        raise SystemExit("Refusing to overwrite the source image")
    if output.suffix.lower() != ".png":
        raise SystemExit("Blend masks must be written as PNG")
    with Image.open(source) as image:
        width, height = image.size
    try:
        mask, mode, focus = build_mask(width, height, args.region_type, args.focus_box, args.mode, args.blur)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), mask)
    print(json.dumps({
        "output": str(output),
        "size": [width, height],
        "region_type": args.region_type,
        "mode": mode,
        "focus_box": {"x": focus[0], "y": focus[1], "width": focus[2], "height": focus[3]},
        "semantic_segmentation": False,
        "adds_generation_calls": False,
        "mean_mask_weight": float(mask.mean() / 255.0),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
