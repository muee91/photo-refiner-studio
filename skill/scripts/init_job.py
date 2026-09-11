#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from resolve_prompt import resolve_prompt


ASPECT_RATIO_RE = re.compile(r"^[1-9]\d*:[1-9]\d*$")
RESOLUTION_RE = re.compile(r"^[1-9]\d*x[1-9]\d*$", re.IGNORECASE)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".heif"}


def normalize_source_path(value: Path) -> Path:
    """Resolve common pasted-path escaping without silently changing real paths."""
    candidate = value.expanduser()
    if candidate.exists():
        return candidate.resolve()
    raw = str(candidate)
    # Markdown/JSON escaping can turn an underscore into a literal ``\\_``.
    # Only use the unescaped candidate when it actually exists.
    if "\\_" in raw:
        unescaped = Path(raw.replace("\\_", "_"))
        if unescaped.exists():
            return unescaped.resolve()
    return candidate.resolve()


def validate_source_files(values: list[Path]) -> list[Path]:
    files: list[Path] = []
    directories: list[str] = []
    missing: list[str] = []
    for value in values:
        item = normalize_source_path(value)
        try:
            if item.is_file():
                if item.suffix.lower() not in IMAGE_SUFFIXES:
                    raise SystemExit(f"Unsupported source image type: {item}")
                files.append(item)
            elif item.is_dir():
                directories.append(str(item))
            else:
                missing.append(str(item))
        except OSError as exc:
            raise SystemExit(f"Cannot access source path {item}: {exc}") from exc
    if directories:
        joined = ", ".join(directories)
        raise SystemExit(
            "Source path is a directory, not a photograph: "
            f"{joined}. Pass one or more exact image files; do not pass the photo folder itself."
        )
    if missing:
        suggestions: list[str] = []
        for raw in missing:
            item = Path(raw)
            try:
                siblings = sorted(
                    candidate for candidate in item.parent.iterdir()
                    if candidate.is_dir() and candidate.name.startswith(item.name)
                )
            except OSError:
                siblings = []
            suggestions.extend(str(candidate) for candidate in siblings[:3])
        hint = f" Possible similarly named directories (not selected automatically): {', '.join(suggestions)}." if suggestions else ""
        raise SystemExit(
            "Missing source files: " + ", ".join(missing) +
            ". Check that the path is an exact image file; pasted paths containing \\_ are normalized only when the unescaped path exists." + hint
        )
    if not files:
        raise SystemExit("At least one source photograph is required")
    return files


def validate_aspect_ratio(value: str) -> str:
    if value in {"original", "16:9", "3:2", "4:5", "9:16"} or ASPECT_RATIO_RE.fullmatch(value):
        return value
    raise argparse.ArgumentTypeError("Aspect ratio must be original or W:H")


def validate_resolution(value: str) -> str:
    if value in {"preview", "4k", "source-width"} or RESOLUTION_RE.fullmatch(value):
        return value.lower()
    raise argparse.ArgumentTypeError("Resolution must be preview, 4k, source-width, or WIDTHxHEIGHT")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_confirmation(path_value: Path) -> dict:
    confirmation_path = path_value.expanduser().resolve()
    confirmation_root = (Path.home() / ".codex" / "photo-refiner" / "confirmed").resolve()
    if not confirmation_path.is_file() or not confirmation_path.is_relative_to(confirmation_root):
        raise SystemExit("Confirmation file must exist inside ~/.codex/photo-refiner/confirmed")
    record = json.loads(confirmation_path.read_text(encoding="utf-8"))
    if record.get("confirmedBy") != "photo-refiner-studio" or not record.get("confirmationId"):
        raise SystemExit("Invalid Photo Refiner Studio confirmation")
    resolved = record.get("resolvedPrompt")
    expected_hash = hashlib.sha256(
        json.dumps(resolved, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if record.get("promptHash") != expected_hash:
        raise SystemExit("Confirmation prompt hash mismatch")
    if not isinstance(record.get("config"), dict):
        raise SystemExit("Confirmation is missing its config")
    record["confirmationPath"] = str(confirmation_path)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an isolated photo refinement job.")
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--workflow", choices=["auto", "single", "batch"], default="auto")
    parser.add_argument("--confirmation-file", type=Path, help="Confirmation JSON created by Photo Refiner Studio")
    parser.add_argument("--preset", help="Confirmed named preset or custom for text-only fallback")
    parser.add_argument("--custom-prompt", default="")
    parser.add_argument("--custom-avoid", default="")
    parser.add_argument("--aspect-ratio", type=validate_aspect_ratio, default="original")
    parser.add_argument("--framing", choices=["preserve", "crop", "outpaint", "contain"], default="preserve")
    parser.add_argument("--resolution", type=validate_resolution, default="source-width")
    parser.add_argument("--output-format", choices=["png", "jpg", "both"], default="png")
    parser.add_argument("--consistency", choices=["strict", "balanced", "creative"], default="balanced")
    parser.add_argument("--master-frame", default="auto")
    parser.add_argument("--detail-mode", choices=["base-only", "face", "adaptive", "explicit"], default="adaptive")
    parser.add_argument("--detail-budget", choices=["fast", "balanced", "max"], help="Generation ceiling: fast=1, balanced=3, max=5. Explicit CLI value overrides Studio default.")
    parser.add_argument("--detail-regions", default="", help="Comma-separated regions required for explicit detail mode")
    parser.add_argument("--keep-intermediates", action="store_true")
    parser.add_argument("--confirmed", action="store_true", help="Assert that the displayed settings were confirmed by the user")
    args = parser.parse_args()

    cli_detail_budget = args.detail_budget
    confirmation = None
    if args.confirmation_file:
        confirmation = load_confirmation(args.confirmation_file)
        ui_config = confirmation["config"]
        args.workflow = ui_config["workflow"]
        args.preset = ui_config["preset"]
        args.custom_prompt = ui_config.get("customPrompt", "")
        args.custom_avoid = ui_config.get("customAvoid", "")
        args.aspect_ratio = ui_config["aspectRatio"]
        args.framing = ui_config["framing"]
        args.resolution = ui_config["resolution"]
        delivery_mode = ui_config["deliveryMode"]
        ui_mode = ui_config.get("uiMode", "simple")
        args.output_format = ui_config["outputFormat"]
        args.keep_intermediates = ui_config["keepIntermediates"]
        args.consistency = ui_config["batch"]["consistency"]
        args.detail_mode = ui_config["detail"]["mode"]
        args.detail_budget = cli_detail_budget or ui_config["detail"].get("generationBudget", "balanced")
        args.detail_regions = ui_config["detail"].get("regions", "")
        resolved_prompt = {
            "preset": confirmation["resolvedPrompt"]["preset"],
            "label": confirmation["resolvedPrompt"]["label"],
            "summary": confirmation["resolvedPrompt"]["summary"],
            "prompt": confirmation["resolvedPrompt"]["prompt"],
            "avoid": confirmation["resolvedPrompt"]["avoid"],
            "default_strength": confirmation["resolvedPrompt"].get(
                "defaultStrength", confirmation["config"]["styleStrength"]
            ),
            "preset_version": confirmation["resolvedPrompt"]["presetVersion"],
            "prompt_hash": confirmation["promptHash"],
        }
    else:
        if not args.confirmed:
            raise SystemExit("Refusing to initialize: show the settings and obtain user confirmation, then pass --confirmed")
        if not args.preset:
            raise SystemExit("--preset is required for text-only confirmed initialization")
        try:
            resolved_prompt = resolve_prompt(args.preset, args.custom_prompt, args.custom_avoid)
        except (OSError, ValueError, KeyError) as exc:
            raise SystemExit(str(exc)) from exc
        delivery_mode = "preview-first"
        ui_mode = "simple"
        args.detail_budget = args.detail_budget or "balanced"

    sources = validate_source_files(args.sources)
    workflow = args.workflow
    if workflow == "auto":
        workflow = "batch" if len(sources) > 1 else "single"
    if workflow == "single" and len(sources) != 1:
        raise SystemExit("Single workflow requires exactly one source")
    if workflow == "batch" and len(sources) < 2:
        raise SystemExit("Batch workflow requires at least two sources")
    if args.aspect_ratio != "original" and args.framing == "preserve":
        raise SystemExit("Changing aspect ratio requires --framing crop, outpaint, or contain")
    detail_regions = [item.strip() for item in args.detail_regions.split(",") if item.strip()]
    if args.detail_mode == "explicit" and not detail_regions:
        raise SystemExit("--detail-regions is required when --detail-mode explicit is selected")

    output_root = args.output_root or (sources[0].parent / "_photo_refiner")
    output_root = output_root.expanduser().resolve()
    label = "batch" if workflow == "batch" else sources[0].stem
    now = datetime.now().astimezone()
    timestamp = now.strftime("%Y%m%d-%H%M%S-%f")
    job_dir = output_root / f"{timestamp}-{label}"
    job_dir.mkdir(parents=True, exist_ok=False)
    (job_dir / "intermediates").mkdir()
    (job_dir / "outputs").mkdir()

    source_records = [
        {"path": str(item), "size": item.stat().st_size, "sha256": sha256_file(item)} for item in sources
    ]
    budget_limits = {"fast": 1, "balanced": 3, "max": 5}

    manifest = {
        "version": 2,
        "release_version": "2.2",
        "created_at": now.isoformat(),
        "confirmed_at": now.isoformat(),
        "confirmation": None
        if confirmation is None
        else {
            "id": confirmation["confirmationId"],
            "path": confirmation["confirmationPath"],
            "confirmed_at": confirmation["confirmedAt"],
            "confirmed_by": confirmation["confirmedBy"],
        },
        "status": "initialized",
        "working_color_space": "sRGB",
        "authority_model": {
            "source_master": ["identity", "anatomy", "factual_geometry", "construction", "authentic_material_reference"],
            "look_master": ["approved_color", "lighting", "tone", "atmosphere", "visual_style"],
            "detail_patch": ["registered_mid_frequency_detail", "registered_high_frequency_detail"],
        },
        "workflow": workflow,
        "ui_mode": ui_mode,
        "sources": [str(item) for item in sources],
        "source_records": source_records,
        "preset": resolved_prompt["preset"],
        "resolved_prompt": resolved_prompt,
        "aspect_ratio": args.aspect_ratio,
        "framing": args.framing,
        "resolution": args.resolution,
        "delivery_mode": delivery_mode,
        # Batch jobs already use the approved master frame as their base-look review.
        "base_preview": {"required": delivery_mode == "preview-first" and workflow == "single", "approved": False},
        "output_format": args.output_format,
        "batch": {
            "consistency": args.consistency,
            "master_frame": args.master_frame,
            "shared_identity": True,
            "shared_scene": True,
            "shared_prompt": True,
            "master_frame_approved": None if workflow == "single" else False,
        },
        "detail": {
            "mode": args.detail_mode,
            "generation_budget": args.detail_budget,
            "max_generated_patches": budget_limits[args.detail_budget],
            "planner": "adaptive-value-merge-v2",
            "mask_mode": "lightweight",
            "regions": detail_regions,
            "patch_scope": "head-and-face" if confirmation is None else ui_config.get("detail", {}).get("patchScope", "head-and-face"),
            "head_patch": True if confirmation is None else ui_config.get("detail", {}).get("patchScope", "head-and-face") == "head-and-face",
            "pixel_budget_thresholds": {
                "face": 0.85,
                "hand": 0.75,
                "head": 0.65,
                "costume": 0.50,
                "prop": 0.50,
                "architecture": 0.50,
                "background": 0.30,
                "generic": 0.50,
            },
        },
        "retouch": {
            "style_strength": resolved_prompt.get("default_strength", 50),
            "detail_strength": 60,
        }
        if confirmation is None
        else {
            "style_strength": confirmation["config"]["styleStrength"],
            "global": confirmation["config"]["global"],
            "portrait": confirmation["config"]["portrait"],
            "body": confirmation["config"]["body"],
            "clothing": confirmation["config"]["clothing"],
            "background": confirmation["config"]["background"],
            "detail_strength": confirmation["config"]["detail"]["strength"],
        },
        "quality_gate": {
            "registration_min_ratio": 0.75,
            "registration_min_inliers": 40,
            "registration_model_by_region": {
                "face": "similarity",
                "head": "affine",
                "hand": "affine",
                "costume": "homography",
                "prop": "homography",
                "architecture": "homography",
                "background": "homography",
                "generic": "homography",
            },
            "identity_structure_review_required": True,
            "landmark_identity_gate": {
                "mode": "optional-when-landmarks-available",
                "max_normalized_rmse": 0.055,
                "max_point_error": 0.10,
            },
            "max_retries": 2,
        },
        "output": {
            "separate_job_folder": True,
            "keep_intermediates": args.keep_intermediates,
        },
        "artifacts": [],
        "history": [{"status": "initialized", "at": now.isoformat()}],
    }
    (job_dir / "job.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(job_dir)


if __name__ == "__main__":
    main()
