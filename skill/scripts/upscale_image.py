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
  4. python realesrgan package (installed by --install-engine)
  5. Lanczos fallback — always succeeds, reported as `fallback-lanczos`

Output is a JSON status line so callers can label delivery honestly.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

UPSCALER_DIR = Path.home() / ".photo-refiner" / "upscaler"
MODEL_NAME = "4x-UltraSharp"
MODEL_PATH = UPSCALER_DIR / f"{MODEL_NAME}.pth"
NCNN_DIRS = [UPSCALER_DIR, UPSCALER_DIR / "models"]
MODEL_MIN_BYTES = 50_000_000
MODEL_CANDIDATES = [
    "https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/4x-UltraSharp.pth",
    "https://huggingface.co/kolibril13/4x-UltraSharp/resolve/main/4x-UltraSharp.pth",
]
UPSCAYL_BINARIES = [
    Path("/Applications/Upscayl.app/Contents/Resources/resources/binaries/upscayl-bin"),
    Path.home() / "Applications/Upscayl.app/Contents/Resources/resources/binaries/upscayl-bin",
]


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


def python_engine_ready() -> bool:
    return importlib.util.find_spec("realesrgan") is not None and MODEL_PATH.is_file()


def engine_status() -> dict:
    model_dir = find_ncnn_pair()
    return {
        "ultrashort_ready": bool(model_dir or python_engine_ready()),
        "ncnn_dir": str(model_dir) if model_dir else None,
        "ncnn_binary": find_ncnn_binary(),
        "python_engine": python_engine_ready(),
        "model_path": str(MODEL_PATH) if MODEL_PATH.is_file() else None,
        "model_candidates": MODEL_CANDIDATES,
        "upscaler_dir": str(UPSCALER_DIR),
    }


def run_ncnn(inp: Path, out: Path, scale: int, model_dir: Path, binary: str) -> dict:
    subprocess.run(
        [binary, "-i", str(inp), "-o", str(out), "-s", str(scale),
         "-n", str(model_dir / MODEL_NAME), "-f", "png"],
        check=True, capture_output=True, timeout=1800,
    )
    return {"engine": "4x-ultrasharp-ncnn"}


def run_python_engine(inp: Path, out: Path, scale: int) -> dict:
    inference = (
        "import sys, cv2\n"
        "from basicsr.archs.rrdbnet import RRDBNet\n"
        "from realesrgan import RealESRGANer\n"
        "inp, out, scale, model_path = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]\n"
        "model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)\n"
        "upsampler = RealESRGANer(scale=4, model_path=model_path, tile=512, tile_pad=32, half=False)\n"
        "image = cv2.imread(inp, cv2.IMREAD_COLOR)\n"
        "output, _ = upsampler.enhance(image, outscale=scale)\n"
        "cv2.imwrite(out, output)\n"
    )
    subprocess.run(
        [sys.executable, "-c", inference, str(inp), str(out), str(scale), str(MODEL_PATH)],
        check=True, capture_output=True, timeout=3600,
    )
    return {"engine": "4x-ultrasharp-realesrgan"}


def run_fallback(inp: Path, out: Path, scale: int) -> dict:
    from PIL import Image
    image = Image.open(inp)
    image.load()
    image = image.convert("RGB").resize(
        (image.width * scale, image.height * scale), Image.LANCZOS
    )
    image.save(out, "PNG")
    return {"engine": "fallback-lanczos", "note": "No AI upscaler engine installed; output is a plain Lanczos resize, not AI sharpening. Run --install-engine to enable 4X-UltraSharp."}


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
    if engine in {"auto", "realesrgan"} and python_engine_ready():
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
            [sys.executable, "-m", "pip", "install", "--quiet", "realesrgan==0.3.0"],
            check=True, capture_output=True, timeout=1800,
        )
        installed.append("realesrgan (python engine)")
    except subprocess.CalledProcessError as exc:
        failures.append(f"pip realesrgan failed: {exc.stderr[-400:] if exc.stderr else exc}")
    model_done = False
    for url in MODEL_CANDIDATES:
        target = MODEL_PATH.with_suffix(".part")
        try:
            with urllib.request.urlopen(url, timeout=120) as response, target.open("wb") as handle:
                total = 0
                while chunk := response.read(1 << 20):
                    total += len(chunk)
                    handle.write(chunk)
                    if total > 400_000_000:
                        raise ValueError("model download exceeds expected size")
            if target.stat().st_size < MODEL_MIN_BYTES:
                raise ValueError(f"downloaded model too small ({target.stat().st_size} bytes)")
            target.replace(MODEL_PATH)
            installed.append(f"{MODEL_NAME}.pth ({url})")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Upscale an image with 4X-UltraSharp (bundled engine) or an honest Lanczos fallback.")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--engine", choices=["auto", "ncnn", "realesrgan", "fallback"], default="auto")
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
    result = upscale(args.input, args.output, max(1, min(8, args.scale)), args.engine)
    result.update({"ok": True, "output": str(Path(args.output).expanduser().resolve()), "scale": args.scale})
    _print(result)


if __name__ == "__main__":
    main()
