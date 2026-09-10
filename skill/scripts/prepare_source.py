#!/usr/bin/env python3
import argparse
from pathlib import Path

from PIL import Image, ImageOps


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize the first frame of a source photo to RGB PNG.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.input.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Missing input: {source}")
    if source == output:
        raise SystemExit("Refusing to overwrite the source image")
    if output.suffix.lower() != ".png":
        raise SystemExit("Normalized output must use a .png extension")
    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        try:
            image.seek(0)
        except EOFError:
            pass
        icc_profile = image.info.get("icc_profile")
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        save_options = {"format": "PNG", "compress_level": 4}
        if icc_profile:
            save_options["icc_profile"] = icc_profile
        normalized.save(output, **save_options)
        print(f"{output} {normalized.width}x{normalized.height}")


if __name__ == "__main__":
    main()
