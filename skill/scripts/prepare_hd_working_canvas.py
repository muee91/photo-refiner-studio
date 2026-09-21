#!/usr/bin/env python3
"""Prepare the honest high-resolution working canvas for Photo Refiner.

This stage is shared by ordinary refinement, creative-safe recovery, and the
photographic first stage of hd-master creative jobs.

Routes:
- native-detail: approved master already supports the delivery canvas.
- ultrasharp-detail: raise the working canvas with the information-adding 4X model,
  then run normal local recovery on that raised canvas.
- full-canvas-tile-redraw: the requested delivery exceeds the model's honest
  information span (or no information-adding engine is installed). Build a
  delivery-size scaffold, then redraw the full canvas with observed-size tiles.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from job_contract import MAX_HONEST_UPSCALE, atomic_write_json
from upscale_image import engine_status


MODEL_NATIVE_SCALE = 4


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("Size must be WIDTHxHEIGHT") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("Dimensions must be positive")
    return width, height


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
        # Photography-oriented 4K: 4096 pixels on the long edge, preserving the
        # already-approved master's aspect. Framing/crop/outpaint happened earlier.
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
    # A changed framing owns its new aspect ratio. Keep the original photograph's
    # width as the requested width and derive height from the approved master.
    return source_size[0], max(1, round(source_size[0] * input_size[1] / input_size[0]))


def choose_route(
    input_size: tuple[int, int],
    target: tuple[int, int],
    informative_engine_ready: bool,
    honest_tail: float = MAX_HONEST_UPSCALE,
) -> dict:
    required = max(target[0] / input_size[0], target[1] / input_size[1])
    if required <= honest_tail:
        return {
            "route": "native-detail",
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an honest HD working canvas and choose local-patch vs full-tile recovery.")
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
    status = engine_status()
    informative_ready = bool(status.get("ultrasharp_ready"))
    decision = choose_route(start_size, target, informative_ready)

    upscale_result = None
    scaffold_interpolation = False
    output.parent.mkdir(parents=True, exist_ok=True)

    if decision["route"] == "native-detail":
        shutil.copy2(source, output)
    elif decision["route"] == "ultrasharp-detail":
        upscale_result = run_upscaler(job_path, source, output, decision["model_scale"])
        if not upscale_result.get("adds_information"):
            # Engine readiness changed between probe and execution. Never silently
            # downgrade an HD route to Lanczos; use the auditable full-canvas path.
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
        "schema_version": 1,
        "policy": "automatic-hd-working-canvas",
        "input": str(source),
        "input_size": list(start_size),
        "delivery_canvas": list(target),
        "route": decision["route"],
        "required_scale": round(float(decision["required_scale"]), 6),
        "model_native_scale": MODEL_NATIVE_SCALE,
        "model_scale_used": int(decision["model_scale"]),
        "informative_engine_ready": informative_ready,
        "output": str(output),
        "output_size": list(output_size),
        "requires_full_canvas_redraw": bool(decision["requires_full_canvas_redraw"]),
        "scaffold_interpolation": scaffold_interpolation,
        "upscale_result": upscale_result,
        "next_step": (
            "Run plan_tile_redraw.py on this exact output with --full-canvas --sliver-margin 0, "
            "using an observed client patch size, then execute every tile and pass --tile-plan "
            "to delivery_gate.py."
            if decision["requires_full_canvas_redraw"]
            else "Run plan_detail_tiles.py on this exact output using delivery_canvas, then execute its selected regions."
        ),
    }
    data["hd_working_canvas"] = record
    atomic_write_json(job_path, data)
    print(json.dumps(record, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
