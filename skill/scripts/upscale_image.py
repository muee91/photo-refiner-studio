#!/usr/bin/env python3
"""Pluggable upscaler adapter: 4X-UltraSharp when an engine is installed,
deterministic Lanczos fallback that is always available and honestly labeled.

The engine is fully self-contained — no ComfyUI or other app required:

    python3 upscale_image.py --install-engine

downloads the Real-ESRGAN python stack and the 4x-UltraSharp weights into
~/.photo-refiner/upscaler/. Engines are probed in this order:

  1. bundled ncnn model dir (~/.photo-refiner/upscaler, 4x-UltraSharp.param/bin)
  2. Upscayl app-bundle binary (macOS) with a compatible model
  3. realesrgan-ncnn-vulkan on PATH
  4. spandrel + torch (installed by --install-engine), MPS when available
  5. Lanczos fallback — always succeeds, reported as `fallback-lanczos`

Output is a JSON status line so callers can label delivery honestly.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image

from job_contract import atomic_write_json

UPSCALER_DIR = Path.home() / ".photo-refiner" / "upscaler"
MODEL_NAME = "4x-UltraSharp"
MODEL_PATH = UPSCALER_DIR / f"{MODEL_NAME}.pth"
MODEL_DIGEST_PATH = UPSCALER_DIR / f"{MODEL_NAME}.pth.sha256"
NCNN_DIRS = [UPSCALER_DIR, UPSCALER_DIR / "models"]
MODEL_MIN_BYTES = 50_000_000
MODEL_EXPECTED_SHA256 = "a5812231fc936b42af08a5edba784195495d303d5b3248c24489ef0c4021fe01"
MODEL_CANDIDATES = [
    "https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/4x-UltraSharp.pth",
    "https://huggingface.co/aiunivers/upscale-models/resolve/main/4x-UltraSharp.pth",
]
UPSCAYL_BINARIES = [
    Path("/Applications/Upscayl.app/Contents/Resources/resources/binaries/upscayl-bin"),
    Path.home() / "Applications/Upscayl.app/Contents/Resources/resources/binaries/upscayl-bin",
]


FALLBACK_NOTE = (
    "No AI upscaler engine installed; output is a plain Lanczos resize, not AI sharpening. "
    "Run --install-engine to enable 4X-UltraSharp."
)


def _save_like(image, out: Path) -> None:
    """Write the pixel format the output extension promises."""
    suffix = out.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        image.save(out, "JPEG", quality=95, subsampling=0, optimize=True)
    elif suffix == ".webp":
        image.save(out, "WEBP", quality=95)
    else:
        image.save(out, "PNG")


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def find_ncnn_pair() -> Path | None:
    for directory in NCNN_DIRS:
        param = directory / f"{MODEL_NAME}.param"
        if param.is_file() and (directory / f"{MODEL_NAME}.bin").is_file():
            return directory
    return None


def find_ncnn_binary() -> str | None:
    local = UPSCALER_DIR / "realesrgan-ncnn-vulkan"
    if local.is_file():
        return str(local)
    for bundle in UPSCAYL_BINARIES:
        if bundle.is_file():
            return str(bundle)
    on_path = shutil.which("realesrgan-ncnn-vulkan")
    return on_path


def cached_model_matches_digest() -> bool:
    """Require the executable pickle to match the repository-pinned digest."""
    if not MODEL_PATH.is_file():
        return False
    digest = hashlib.sha256()
    with MODEL_PATH.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == MODEL_EXPECTED_SHA256


def python_engine_ready() -> bool:
    return (
        importlib.util.find_spec("spandrel") is not None
        and importlib.util.find_spec("torch") is not None
        and MODEL_PATH.is_file()
        and cached_model_matches_digest()
    )


def engine_status() -> dict:
    model_dir = find_ncnn_pair()
    ncnn_binary = find_ncnn_binary()
    ncnn_ready = bool(model_dir and ncnn_binary)
    python_ready = python_engine_ready()
    return {
        "ultrasharp_ready": bool(ncnn_ready or python_ready),
        "ultrashort_ready": bool(ncnn_ready or python_ready),
        "ncnn_ready": ncnn_ready,
        "ncnn_dir": str(model_dir) if model_dir else None,
        "ncnn_binary": ncnn_binary,
        "python_engine": python_ready,
        "model_path": str(MODEL_PATH) if MODEL_PATH.is_file() else None,
        "model_digest_matches": cached_model_matches_digest() if MODEL_PATH.is_file() else None,
        "model_expected_sha256": MODEL_EXPECTED_SHA256,
        "model_candidates": MODEL_CANDIDATES,
        "upscaler_dir": str(UPSCALER_DIR),
    }


def run_ncnn(inp: Path, out: Path, scale: int, model_dir: Path, binary: str) -> dict:
    """Run the 4x model at native scale and transcode to the promised extension."""
    native_scale = 4
    descriptor, name = tempfile.mkstemp(prefix="ultrasharp-native-", suffix=".png", dir=out.parent)
    os.close(descriptor)
    native_path = Path(name)
    try:
        subprocess.run(
            [binary, "-i", str(inp), "-o", str(native_path), "-s", str(native_scale),
             "-n", str(model_dir / MODEL_NAME), "-f", "png"],
            check=True, capture_output=True, timeout=1800,
        )
        with Image.open(native_path) as image, Image.open(inp) as source:
            target_size = (source.width * scale, source.height * scale)
            rendered = image.convert("RGB")
            if rendered.size != target_size:
                rendered = rendered.resize(
                    target_size,
                    Image.Resampling.LANCZOS if scale < native_scale else Image.Resampling.BICUBIC,
                )
            _save_like(rendered, out)
    finally:
        native_path.unlink(missing_ok=True)
    return {
        "engine": "4x-ultrasharp-ncnn",
        "adds_information": True,
        "native_information_scale": native_scale,
    }


def _run_model(model, device, rgb_hwc, net_scale: int):
    """One forward pass on float [0,1] HWC RGB, returning float [0,1] HWC RGB."""
    import numpy as np
    import torch

    tensor = torch.from_numpy(np.ascontiguousarray(rgb_hwc.transpose(2, 0, 1))).unsqueeze(0).to(device)
    with torch.no_grad():
        output = model(tensor)
    result = output.squeeze(0).permute(1, 2, 0).clamp_(0, 1).cpu().numpy().astype(np.float32)
    return result


def _enhance_tiled(model, device, rgb_hwc, net_scale: int, tile: int = 512, pad: int = 32):
    """Tile so a 4x pass does not need gigabytes of activations on the full canvas."""
    import numpy as np

    height, width = rgb_hwc.shape[:2]
    if max(height, width) <= tile:
        return _run_model(model, device, rgb_hwc, net_scale)
    canvas = np.zeros((height * net_scale, width * net_scale, 3), dtype=np.float32)
    for y0 in range(0, height, tile):
        y1 = min(height, y0 + tile)
        for x0 in range(0, width, tile):
            x1 = min(width, x0 + tile)
            py0, px0 = max(0, y0 - pad), max(0, x0 - pad)
            py1, px1 = min(height, y1 + pad), min(width, x1 + pad)
            tile_out = _run_model(model, device, rgb_hwc[py0:py1, px0:px1], net_scale)
            oy0, ox0 = (y0 - py0) * net_scale, (x0 - px0) * net_scale
            piece = tile_out[oy0:oy0 + (y1 - y0) * net_scale, ox0:ox0 + (x1 - x0) * net_scale]
            canvas[y0 * net_scale:y1 * net_scale, x0 * net_scale:x1 * net_scale] = piece
    return canvas


def run_python_engine(inp: Path, out: Path, scale: int) -> dict:
    """4x-UltraSharp through spandrel.

    spandrel, not `realesrgan`: this checkpoint is a 24-block RRDB whose parameter
    names (`model.N` / `.sub.N.RDB1.convK.0`) are not basicsr's RRDBNet layout, and
    basicsr cannot build on modern Python. A hand-written architecture would load
    with mismatched weights and produce plausible-looking mush, so the layout is
    resolved by the loader instead of guessed here.
    """
    import numpy as np
    from PIL import Image

    from spandrel import ModelLoader
    import torch

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    descriptor = ModelLoader(device=device).load_from_file(str(MODEL_PATH))
    descriptor.model.eval()
    net_scale = int(descriptor.scale)
    with Image.open(inp) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    result = _enhance_tiled(descriptor.model, descriptor.device, rgb, net_scale)
    if scale != net_scale:
        factor = scale / net_scale
        resized = Image.fromarray((result * 255.0).round().astype(np.uint8)).resize(
            (round(result.shape[1] * factor), round(result.shape[0] * factor)),
            Image.LANCZOS if factor < 1 else Image.BICUBIC,
        )
        result = np.asarray(resized, dtype=np.float32) / 255.0
    _save_like(Image.fromarray((np.clip(result, 0, 1) * 255.0).round().astype(np.uint8)), out)
    return {
        "engine": "4x-ultrasharp-spandrel",
        "adds_information": True,
        "native_information_scale": net_scale,
        "device": str(descriptor.device),
        "architecture": type(descriptor.model).__name__,
    }


def run_fallback(inp: Path, out: Path, scale: int) -> dict:
    from PIL import Image
    image = Image.open(inp)
    image.load()
    image = image.convert("RGB").resize(
        (image.width * scale, image.height * scale), Image.LANCZOS
    )
    _save_like(image, out)
    return {
        "engine": "fallback-lanczos",
        "adds_information": False,
        "native_information_scale": 1,
        "note": FALLBACK_NOTE,
    }


def upscale(inp: Path, out: Path, scale: int, engine: str) -> dict:
    inp, out = inp.expanduser().resolve(), out.expanduser().resolve()
    if not inp.is_file():
        raise SystemExit(f"Input image not found: {inp}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if engine in {"auto", "ncnn"}:
        model_dir = find_ncnn_pair()
        binary = find_ncnn_binary()
        if model_dir and binary:
            return run_ncnn(inp, out, scale, model_dir, binary)
    if engine in {"auto", "spandrel"} and python_engine_ready():
        return run_python_engine(inp, out, scale)
    if engine == "fallback":
        return run_fallback(inp, out, scale)
    if engine == "auto":
        return run_fallback(inp, out, scale)
    raise SystemExit(f"Requested engine {engine!r} is not available; run --install-engine or use --engine fallback")


def install_engine() -> dict:
    UPSCALER_DIR.mkdir(parents=True, exist_ok=True)
    installed, failures = [], []
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "spandrel"],
            check=True, capture_output=True, timeout=1800,
        )
        installed.append("spandrel + torch (python engine)")
    except subprocess.CalledProcessError as exc:
        failures.append(f"pip spandrel failed: {exc.stderr[-400:] if exc.stderr else exc}")
    model_done = False
    for url in MODEL_CANDIDATES:
        descriptor, temp_name = tempfile.mkstemp(prefix=f"{MODEL_NAME}.", suffix=".part", dir=UPSCALER_DIR)
        target = Path(temp_name)
        try:
            digest = hashlib.sha256()
            with os.fdopen(descriptor, "wb") as handle, urllib.request.urlopen(url, timeout=120) as response:
                total = 0
                while chunk := response.read(1 << 20):
                    total += len(chunk)
                    digest.update(chunk)
                    handle.write(chunk)
                    if total > 400_000_000:
                        raise ValueError("model download exceeds expected size")
            if target.stat().st_size < MODEL_MIN_BYTES:
                raise ValueError(f"downloaded model too small ({target.stat().st_size} bytes)")
            actual_digest = digest.hexdigest().lower()
            if actual_digest != MODEL_EXPECTED_SHA256:
                raise ValueError(
                    f"model sha256 mismatch: expected {MODEL_EXPECTED_SHA256}, got {actual_digest}"
                )
            target.replace(MODEL_PATH)
            MODEL_DIGEST_PATH.write_text(f"{MODEL_EXPECTED_SHA256}  {MODEL_NAME}.pth\n", encoding="utf-8")
            installed.append(f"{MODEL_NAME}.pth ({url}, pinned sha256 {MODEL_EXPECTED_SHA256[:16]})")
            model_done = True
            break
        except Exception as exc:
            failures.append(f"{url}: {exc}")
            target.unlink(missing_ok=True)
    if not model_done:
        failures.append("All model mirrors failed; download 4x-UltraSharp.pth manually into " + str(MODEL_PATH))
    result = {"ok": bool(model_done and python_engine_ready()), "installed": installed, "failures": failures,
              "upscaler_dir": str(UPSCALER_DIR),
              "note": "Engine is self-contained; ComfyUI is not required. Re-run check_dependencies.py to verify."}
    _print(result)
    if not result["ok"]:
        raise SystemExit(1)
    return result


def record_upscale_pass(job_path: Path, entry: dict) -> None:
    """The delivery gate counts only recorded information-adding passes, so an
    upscale that is never recorded silently disappears from the evidence trail."""
    job_path = job_path.expanduser().resolve()
    if not job_path.is_file() or job_path.name != "job.json":
        raise SystemExit(f"Missing job manifest: {job_path}")
    data = json.loads(job_path.read_text(encoding="utf-8"))
    data.setdefault("upscale_passes", []).append(entry)
    atomic_write_json(job_path, data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upscale an image with 4X-UltraSharp (bundled engine) or an honest Lanczos fallback.")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--engine", choices=["auto", "ncnn", "spandrel", "fallback"], default="auto")
    parser.add_argument("--job", type=Path, help="job.json to record this pass in; the delivery gate only counts recorded information-adding passes")
    parser.add_argument("--install-engine", action="store_true", help="Install the self-contained 4X-UltraSharp engine (no ComfyUI needed)")
    parser.add_argument("--status", action="store_true", help="Print detected engines as JSON")
    args = parser.parse_args()
    if args.status:
        _print(engine_status())
        return
    if args.install_engine:
        install_engine()
        return
    if not args.input or not args.output:
        parser.error("--input and --output are required unless --status or --install-engine is used")
    if not 1 <= args.scale <= 8:
        parser.error("--scale must be between 1 and 8")
    source = args.input.expanduser().resolve()
    target = args.output.expanduser().resolve()
    result = upscale(args.input, args.output, args.scale, args.engine)
    with Image.open(source) as raw:
        from_size = [raw.width, raw.height]
    with Image.open(target) as made:
        to_size = [made.width, made.height]
    adds_information = bool(result.get("adds_information", True))
    native_information_scale = int(result.get("native_information_scale") or (4 if adds_information else 1))
    information_scale = min(max(1, args.scale), native_information_scale) if adds_information else 1
    information_to = [
        from_size[0] * information_scale,
        from_size[1] * information_scale,
    ]
    result.update({
        "ok": True,
        "output": str(target),
        "scale": args.scale,
        "from": from_size,
        "to": to_size,
        "adds_information": adds_information,
        "native_information_scale": native_information_scale,
        "information_scale": information_scale,
        "information_to": information_to,
        "interpolated_tail": (
            [max(0, to_size[0] - information_to[0]), max(0, to_size[1] - information_to[1])]
            if adds_information else list(to_size)
        ),
    })
    if args.job:
        record_upscale_pass(args.job, {
            key: result[key]
            for key in (
                "engine", "adds_information", "from", "to",
                "native_information_scale", "information_scale",
                "information_to", "interpolated_tail"
            )
        })
    _print(result)


if __name__ == "__main__":
    main()
