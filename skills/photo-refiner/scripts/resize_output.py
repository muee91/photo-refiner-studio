#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageCms, ImageOps

from job_contract import MAX_HONEST_UPSCALE


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("Size must be WIDTHxHEIGHT")
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("Dimensions must be positive")
    return width, height


def srgb_profile_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def main() -> None:
    parser = argparse.ArgumentParser(description="Resize an accepted sRGB composite to exact delivery dimensions.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--size", type=parse_size, required=True)
    parser.add_argument("--jpeg-quality", type=int, default=96)
    parser.add_argument(
        "--fit",
        choices=["reject", "cover", "contain", "stretch"],
        default="reject",
        help="How to handle an input/output aspect-ratio mismatch",
    )
    parser.add_argument("--background", default="#000000", help="Letterbox color for --fit contain")
    parser.add_argument(
        "--icc-source",
        type=Path,
        help="Deprecated compatibility flag. The working and output space is sRGB; source ICC is never blindly reattached.",
    )
    args = parser.parse_args()
    source = args.input.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Missing input: {source}")
    if source == output:
        raise SystemExit("Refusing to overwrite the input image")
    if not 1 <= args.jpeg_quality <= 100:
        raise SystemExit("JPEG quality must be between 1 and 100")
    if output.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise SystemExit("Output extension must be .png, .jpg, or .jpeg")
    if args.icc_source:
        legacy = args.icc_source.expanduser().resolve()
        if not legacy.is_file():
            raise SystemExit(f"Missing ICC source: {legacy}")
        print(
            "warning: --icc-source is deprecated; the accepted composite stays in sRGB and the source profile is not reattached",
            file=sys.stderr,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        source_rgb = image.convert("RGB")
        source_ratio = source_rgb.width / source_rgb.height
        target_ratio = args.size[0] / args.size[1]
        ratio_matches = abs(source_ratio - target_ratio) / target_ratio <= 0.001
        if not ratio_matches and args.fit == "reject":
            raise SystemExit(
                f"Aspect-ratio mismatch: input {source_rgb.width}:{source_rgb.height}, "
                f"output {args.size[0]}:{args.size[1]}; choose --fit cover, contain, or stretch explicitly"
            )
        if ratio_matches or args.fit == "stretch":
            resized = source_rgb.resize(args.size, Image.Resampling.LANCZOS)
        elif args.fit == "cover":
            resized = ImageOps.fit(source_rgb, args.size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        else:
            contained = ImageOps.contain(source_rgb, args.size, method=Image.Resampling.LANCZOS)
            try:
                background = Image.new("RGB", args.size, args.background)
            except ValueError as exc:
                raise SystemExit(f"Invalid background color: {args.background}") from exc
            offset = ((args.size[0] - contained.width) // 2, (args.size[1] - contained.height) // 2)
            background.paste(contained, offset)
            resized = background
        save_options = {"icc_profile": srgb_profile_bytes()}
        if output.suffix.lower() in {".jpg", ".jpeg"}:
            resized.save(output, quality=args.jpeg_quality, subsampling=0, optimize=True, **save_options)
        else:
            resized.save(output, format="PNG", compress_level=4, **save_options)
        factor = max(resized.width / source_rgb.width, resized.height / source_rgb.height)
        if factor > MAX_HONEST_UPSCALE:
            print(
                f"warning: enlarging the accepted composite by {factor:.2f}x interpolates pixels; "
                "this is not recovered detail and the delivery gate will refuse to complete the job",
                file=sys.stderr,
            )
        print(
            f"{output} {resized.width}x{resized.height} colorspace=sRGB "
            f"input={source_rgb.width}x{source_rgb.height} scale={factor:.4f}"
        )


if __name__ == "__main__":
    main()
