#!/usr/bin/env python3
import argparse
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageCms, ImageOps


def srgb_profile_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def convert_to_srgb(image: Image.Image) -> Image.Image:
    oriented = ImageOps.exif_transpose(image)
    icc_profile = image.info.get("icc_profile")
    if not icc_profile:
        return oriented.convert("RGB")
    try:
        source_profile = ImageCms.ImageCmsProfile(BytesIO(icc_profile))
        target_profile = ImageCms.createProfile("sRGB")
        return ImageCms.profileToProfile(oriented, source_profile, target_profile, outputMode="RGB")
    except Exception as exc:  # Pillow/lcms raises several profile-specific exception types.
        raise SystemExit(
            "Embedded ICC profile could not be converted to the Photo Refiner sRGB working space; "
            "refusing to reinterpret the pixels with the wrong profile."
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize the first frame of a source photo to color-managed sRGB PNG.")
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
        normalized = convert_to_srgb(image)
        normalized.save(
            output,
            format="PNG",
            compress_level=4,
            icc_profile=srgb_profile_bytes(),
        )
        print(f"{output} {normalized.width}x{normalized.height} colorspace=sRGB")


if __name__ == "__main__":
    main()
