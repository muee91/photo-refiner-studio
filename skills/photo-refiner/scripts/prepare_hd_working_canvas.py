#!/usr/bin/env python3
"""Prepare the high-resolution working canvas for Photo Refiner.

Photography has a real high-resolution SOURCE MASTER. It is therefore different
from a fully synthetic/creative canvas: source-width delivery does not require
regenerating the whole frame merely because the approved LOOK MASTER returned at
a smaller bitmap size.

Routes:
- native-detail: approved master already supports the delivery canvas.
- source-backed-detail: ordinary, original-framing source-width photography uses
  SOURCE MASTER micro-detail under the approved LOOK MASTER and only regenerates
  valuable local regions.
- ultrasharp-detail: raise a non-source-backed working canvas with the information-
  adding 4X model, then run local recovery.
- full-canvas-tile-redraw: reserved for canvases whose pixels cannot be backed by
  SOURCE MASTER (notably transformed creative work) and that exceed the honest
  information span.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from job_contract import MAX_HONEST_UPSCALE, atomic_write_json
from upscale_image import engine_status


MODEL_NATIVE_SCALE = 4
SOURCE_DETAIL_RADIUS = 1.25
SOURCE_DETAIL_STRENGTH = 0.55


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("Size must be WIDTHxHEIGHT") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("Dimensions must be positive")
    return width, height


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            return image.width, image.height
    except OSError as exc:
        raise SystemExit(f"Cannot read image {path}: {exc}") from exc


def delivery_canvas(job: dict, input_size: tuple[int, int], override: tuple[int, int] | None) -> tuple[int, int]:
    if override is not None:
        return override
    resolution = str(job.get("resolution") or "source-width").lower()
    if "x" in resolution and resolution.replace("x", "").isdigit():
        return parse_size(resolution)
    if resolution == "preview":
        return input_size
    if resolution == "4k":
        width, height = input_size
        if width >= height:
            return 4096, max(1, round(4096 * height / width))
        return max(1, round(4096 * width / height)), 4096
    if resolution != "source-width":
        raise SystemExit(f"Unsupported delivery resolution: {resolution!r}")

    sources = job.get("sources") or []
    if not sources:
        raise SystemExit("source-width delivery requires at least one source path in job.json")
    source = Path(str(sources[0])).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Source image for source-width delivery is missing: {source}")
    source_size = image_size(source)
    if str(job.get("aspect_ratio") or "original") == "original":
        return source_size
    return source_size[0], max(1, round(source_size[0] * input_size[1] / input_size[0]))


def ultrasharp_allowed(job: dict) -> bool:
    creative = job.get("creative_output")
    if not isinstance(creative, dict):
        return True
    if creative.get("upstream_binding") == "hd-master":
        return True
    upscale = creative.get("upscale")
    if isinstance(upscale, dict):
        return bool(upscale.get("enabled"))
    return True


def source_backed_eligible(job: dict, target: tuple[int, int]) -> tuple[bool, Path | None]:
    """Whether SOURCE MASTER may honestly carry high-frequency source-width detail.

    Keep this deliberately narrow. It is only automatic for ordinary photographic
    refinement with original framing and exact source-width delivery. Creative
    translation, outpaint/reframing and synthetic regions must use their own HD
    route instead of borrowing unrelated source pixels.
    """
    if job.get("creative_recipe") is not None:
        return False, None
    if str(job.get("resolution") or "").lower() != "source-width":
        return False, None
    if str(job.get("aspect_ratio") or "original") != "original":
        return False, None
    sources = job.get("sources") or []
    if len(sources) != 1:
        return False, None
    source = Path(str(sources[0])).expanduser().resolve()
    if not source.is_file() or image_size(source) != target:
        return False, None
    return True, source


def choose_route(
    input_size: tuple[int, int],
    target: tuple[int, int],
    informative_engine_ready: bool,
    honest_tail: float = MAX_HONEST_UPSCALE,
    *,
    source_backed: bool = False,
) -> dict:
    required = max(target[0] / input_size[0], target[1] / input_size[1])
    if required <= honest_tail:
        return {
            "route": "native-detail",
            "required_scale": required,
            "model_scale": 1,
            "requires_full_canvas_redraw": False,
        }

    # SOURCE MASTER already contains the real source-resolution high frequencies.
    # Do not rebuild the whole photograph with generated tiles simply because the
    # style/look preview was returned smaller.
    if source_backed:
        return {
            "route": "source-backed-detail",
            "required_scale": required,
            "model_scale": 1,
            "requires_full_canvas_redraw": False,
        }

    model_scale = min(MODEL_NATIVE_SCALE, max(2, math.ceil(required / honest_tail)))
    if informative_engine_ready and required <= MODEL_NATIVE_SCALE * honest_tail:
        return {
            "route": "ultrasharp-detail",
            "required_scale": required,
            "model_scale": model_scale,
            "requires_full_canvas_redraw": False,
        }

    return {
        "route": "full-canvas-tile-redraw",
        "required_scale": required,
        "model_scale": MODEL_NATIVE_SCALE if informative_engine_ready else 1,
        "requires_full_canvas_redraw": True,
    }


def run_upscaler(job_path: Path, source: Path, output: Path, scale: int) -> dict:
    command = [
        sys.executable,
        str(Path(__file__).with_name("upscale_image.py")),
        "--job", str(job_path),
        "--input", str(source),
        "--output", str(output),
        "--scale", str(scale),
        "--engine", "auto",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(result.stdout + result.stderr)
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise SystemExit(f"upscale_image.py returned invalid JSON: {result.stdout!r}") from exc


def resize_scaffold(source: Path, output: Path, target: tuple[int, int]) -> None:
    with Image.open(source) as image:
        rgb = image.convert("RGB")
        source_ratio = rgb.width / rgb.height
        target_ratio = target[0] / target[1]
        if abs(source_ratio - target_ratio) / target_ratio > 0.002:
            raise SystemExit(
                f"Approved master aspect {rgb.width}:{rgb.height} does not match delivery "
                f"{target[0]}:{target[1]}; framing must be resolved before HD preparation"
            )
        resized = rgb.resize(target, Image.Resampling.LANCZOS)
        output.parent.mkdir(parents=True, exist_ok=True)
        resized.save(output, "PNG")


def lift_source_detail(source_master: Path, look_master: Path, output: Path, target: tuple[int, int]) -> dict:
    """Lift only fine luminance detail from SOURCE MASTER into the approved look.

    LOOK MASTER still owns low/mid-frequency appearance. SOURCE MASTER contributes
    a conservative luminance high-pass so real texture is retained at source-width
    without reintroducing the source palette. Important generated subject edits are
    still handled by the normal planned patch chain afterwards.
    """
    with Image.open(source_master) as raw_source, Image.open(look_master) as raw_look:
        source = raw_source.convert("RGB")
        look = raw_look.convert("RGB").resize(target, Image.Resampling.LANCZOS)
        if source.size != target:
            source = source.resize(target, Image.Resampling.LANCZOS)

        source_arr = np.asarray(source, dtype=np.float32)
        look_arr = np.asarray(look, dtype=np.float32)
        source_luma = (
            source_arr[..., 0] * 0.2126
            + source_arr[..., 1] * 0.7152
            + source_arr[..., 2] * 0.0722
        )
        luma_image = Image.fromarray(np.clip(source_luma, 0, 255).astype(np.uint8), mode="L")
        low_luma = np.asarray(luma_image.filter(ImageFilter.GaussianBlur(SOURCE_DETAIL_RADIUS)), dtype=np.float32)
        high_luma = source_luma - low_luma
        lifted = np.clip(look_arr + high_luma[..., None] * SOURCE_DETAIL_STRENGTH, 0, 255).astype(np.uint8)
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(lifted, mode="RGB").save(output, "PNG")

    return {
        "method": "source-luminance-highpass",
        "radius": SOURCE_DETAIL_RADIUS,
        "strength": SOURCE_DETAIL_STRENGTH,
        "source_master": str(source_master),
        "source_master_sha256": sha256_file(source_master),
        "look_master": str(look_master),
        "look_master_sha256": sha256_file(look_master),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an HD working canvas and choose source-backed/local-patch vs full-tile recovery.")
    parser.add_argument("job", type=Path, help="Path to job.json")
    parser.add_argument("--input", required=True, type=Path, help="Exact approved LOOK MASTER / CREATIVE LOOK MASTER")
    parser.add_argument("--output", type=Path, help="Prepared working canvas; defaults to intermediates/hd-working.png")
    parser.add_argument("--delivery-size", type=parse_size, help="Override resolved delivery canvas for testing or explicit orchestration")
    args = parser.parse_args()

    job_path = args.job.expanduser().resolve()
    if not job_path.is_file() or job_path.name != "job.json":
        raise SystemExit(f"Missing job manifest: {job_path}")
    job_dir = job_path.parent
    source = args.input.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Missing approved master: {source}")
    if not source.is_relative_to(job_dir):
        raise SystemExit("Approved master must live inside the job directory")

    output = (args.output or (job_dir / "intermediates" / "hd-working.png")).expanduser().resolve()
    if not output.is_relative_to(job_dir):
        raise SystemExit("Prepared HD working canvas must live inside the job directory")
    if output == source:
        raise SystemExit("Refusing to overwrite the approved master")

    data = json.loads(job_path.read_text(encoding="utf-8"))
    start_size = image_size(source)
    target = delivery_canvas(data, start_size, args.delivery_size)
    source_backed, source_master = source_backed_eligible(data, target)
    status = engine_status()
    allowed_by_job = ultrasharp_allowed(data)
    informative_ready = bool(status.get("ultrasharp_ready")) and allowed_by_job
    decision = choose_route(start_size, target, informative_ready, source_backed=source_backed)

    upscale_result = None
    source_detail_result = None
    scaffold_interpolation = False
    output.parent.mkdir(parents=True, exist_ok=True)

    if decision["route"] == "native-detail":
        shutil.copy2(source, output)
    elif decision["route"] == "source-backed-detail":
        source_detail_result = lift_source_detail(source_master, source, output, target)
    elif decision["route"] == "ultrasharp-detail":
        upscale_result = run_upscaler(job_path, source, output, decision["model_scale"])
        if not upscale_result.get("adds_information"):
            decision = {
                **decision,
                "route": "full-canvas-tile-redraw",
                "model_scale": 1,
                "requires_full_canvas_redraw": True,
                "runtime_engine_fallback": True,
            }
            resize_scaffold(source, output, target)
            scaffold_interpolation = True
    else:
        scaffold_source = source
        if informative_ready:
            native = job_dir / "intermediates" / "hd-information-4x.png"
            upscale_result = run_upscaler(job_path, source, native, MODEL_NATIVE_SCALE)
            if upscale_result.get("adds_information"):
                scaffold_source = native
        resize_scaffold(scaffold_source, output, target)
        scaffold_interpolation = image_size(scaffold_source) != target

    output_size = image_size(output)
    record = {
        "schema_version": 2,
        "policy": "automatic-hd-working-canvas",
        "input": str(source),
        "input_size": list(start_size),
        "input_sha256": sha256_file(source),
        "delivery_canvas": list(target),
        "route": decision["route"],
        "required_scale": round(float(decision["required_scale"]), 6),
        "model_native_scale": MODEL_NATIVE_SCALE,
        "model_scale_used": int(decision["model_scale"]),
        "ultrasharp_allowed_by_job": allowed_by_job,
        "informative_engine_ready": informative_ready,
        "source_backed": decision["route"] == "source-backed-detail",
        "source_detail_result": source_detail_result,
        "output": str(output),
        "output_size": list(output_size),
        "output_sha256": sha256_file(output),
        "requires_full_canvas_redraw": bool(decision["requires_full_canvas_redraw"]),
        "scaffold_interpolation": scaffold_interpolation,
        "upscale_result": upscale_result,
        "next_step": (
            "Run normal subject-aware detail planning. SOURCE MASTER already backs source-resolution micro-detail; "
            "do not request full-canvas redraw merely to prove the file dimensions. Generate only valuable planned regions."
            if decision["route"] == "source-backed-detail"
            else (
                "For adaptive/face/explicit recovery, first run plan_detail_tiles.py on this exact "
                "delivery-size scaffold with the observed client patch size. Then run plan_tile_redraw.py "
                "with BOTH --detail-plan <that-plan> and --full-canvas --sliver-margin 0. Execute every tile."
                if decision["requires_full_canvas_redraw"]
                else "Run plan_detail_tiles.py on this exact output using delivery_canvas, then execute its selected regions."
            )
        ),
    }
    data["hd_working_canvas"] = record
    atomic_write_json(job_path, data)
    print(json.dumps(record, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
