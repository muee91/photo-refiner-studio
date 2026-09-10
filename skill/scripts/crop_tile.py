#!/usr/bin/env python3
import argparse
import json
import math
from pathlib import Path

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract an exact crop for a detail tile.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument(
        "--face-safe",
        action="store_true",
        help="Expand a proposed face box to retain forehead, cheeks, jawline, chin, and transition skin.",
    )
    parser.add_argument(
        "--face-tight",
        action="store_true",
        help="Use a tighter face crop so facial features occupy more of the generated patch; keeps chin context.",
    )
    parser.add_argument("--face-side-context", type=float, default=0.22)
    parser.add_argument("--face-top-context", type=float, default=0.24)
    parser.add_argument("--face-bottom-context", type=float, default=0.42)
    args = parser.parse_args()
    source = args.input.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Missing input: {source}")
    if source == output:
        raise SystemExit("Refusing to overwrite the source image")
    if args.width <= 0 or args.height <= 0:
        raise SystemExit("Crop width and height must be positive")
    for value, name in [
        (args.face_side_context, "face-side-context"),
        (args.face_top_context, "face-top-context"),
        (args.face_bottom_context, "face-bottom-context"),
    ]:
        if value < 0 or value > 1:
            raise SystemExit(f"{name} must be between 0 and 1")
    with Image.open(source) as image:
        if args.x < 0 or args.y < 0 or args.x + args.width > image.width or args.y + args.height > image.height:
            raise SystemExit("Crop is outside image bounds")
        x, y, width, height = args.x, args.y, args.width, args.height
        if args.face_safe or args.face_tight:
            # A landmark/face detector box is not a safe retouch boundary. The lower
            # context is deliberately larger because jaw and chin detail are often lost.
            side_factor = 0.10 if args.face_tight else args.face_side_context
            top_factor = 0.12 if args.face_tight else args.face_top_context
            bottom_factor = 0.22 if args.face_tight else args.face_bottom_context
            side = math.ceil(width * side_factor)
            top = math.ceil(height * top_factor)
            bottom = math.ceil(height * bottom_factor)
            x = max(0, x - side)
            y = max(0, y - top)
            right = min(image.width, args.x + width + side)
            lower = min(image.height, args.y + height + bottom)
            width, height = right - x, lower - y
        tile = image.crop((x, y, x + width, y + height))
        output.parent.mkdir(parents=True, exist_ok=True)
        tile.save(output)
        print(json.dumps({
            "output": str(output),
            "size": [tile.width, tile.height],
            "crop": {"x": x, "y": y, "width": width, "height": height},
            "face_safe": args.face_safe,
            "face_tight": args.face_tight,
        }))


if __name__ == "__main__":
    main()
