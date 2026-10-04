#!/usr/bin/env python3
"""Stack three horizontal 16:9 panels into an exact 16:27 triptych."""

import argparse
from pathlib import Path

from PIL import Image, ImageOps


def open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def fit_panel(path: Path, width: int) -> Image.Image:
    target = (width, width * 9 // 16)
    return ImageOps.fit(
        open_rgb(path), target, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--bottom", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--width", type=int, default=2048)
    args = parser.parse_args()

    if args.width < 16 or args.width % 16:
        parser.error("width must be a positive multiple of 16")

    panels = [
        fit_panel(args.top, args.width),
        fit_panel(args.evidence, args.width),
        fit_panel(args.bottom, args.width),
    ]
    total_height = sum(panel.height for panel in panels)
    canvas = Image.new("RGB", (args.width, total_height))

    y = 0
    for panel in panels:
        canvas.paste(panel, (0, y))
        y += panel.height

    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, "PNG", optimize=True)


if __name__ == "__main__":
    main()
