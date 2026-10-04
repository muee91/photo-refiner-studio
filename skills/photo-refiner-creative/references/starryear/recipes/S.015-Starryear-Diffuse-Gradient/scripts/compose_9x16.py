#!/usr/bin/env python3
"""Compose a crop-only 16:9 evidence band above an artwork into a 9:16 PNG."""

import argparse
from pathlib import Path

from PIL import Image, ImageOps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="customer source photograph")
    parser.add_argument("artwork", type=Path, help="generated lower-panel artwork")
    parser.add_argument("output", type=Path, help="final PNG path")
    parser.add_argument("--width", type=int, default=1152)
    parser.add_argument("--height", type=int, default=2048)
    parser.add_argument(
        "--crop",
        choices=("center", "top", "bottom", "left", "right"),
        default="center",
        help="safe crop bias for the evidence band",
    )
    args = parser.parse_args()

    if args.width * 16 != args.height * 9:
        raise SystemExit("output width:height must be exactly 9:16")
    if (args.width * 9) % 16:
        raise SystemExit("output width must permit an integer-height 16:9 evidence band")

    band_height = args.width * 9 // 16
    lower_height = args.height - band_height
    centering = {
        "center": (0.5, 0.5),
        "top": (0.5, 0.0),
        "bottom": (0.5, 1.0),
        "left": (0.0, 0.5),
        "right": (1.0, 0.5),
    }[args.crop]

    with Image.open(args.source) as source_image:
        source = ImageOps.exif_transpose(source_image).convert("RGB")
        evidence = ImageOps.fit(
            source,
            (args.width, band_height),
            method=Image.Resampling.LANCZOS,
            centering=centering,
        )

    with Image.open(args.artwork) as artwork_image:
        artwork = ImageOps.exif_transpose(artwork_image).convert("RGB")
        lower = ImageOps.fit(
            artwork,
            (args.width, lower_height),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

    canvas = Image.new("RGB", (args.width, args.height))
    canvas.paste(evidence, (0, 0))
    canvas.paste(lower, (0, band_height))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, "PNG", optimize=True)


if __name__ == "__main__":
    main()
