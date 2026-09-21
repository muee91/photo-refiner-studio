#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from job_contract import (
    PIXEL_BUDGET_THRESHOLDS,
    RELEASE_VERSION,
    PLANNER_CREATIVE_SAFE,
    PLANNER_NORMAL,
    PORTRAIT_EXTENTS,
    SettingError,
    creative_safe_budget,
    creative_safe_ceiling,
    normal_budget,
    validated_panel_settings,
)
from resolve_prompt import resolve_prompt


ASPECT_RATIO_RE = re.compile(r"^[1-9]\d*:[1-9]\d*$")
RESOLUTION_RE = re.compile(r"^[1-9]\d*x[1-9]\d*$", re.IGNORECASE)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".heif"}
SKILL_ROOT = Path(__file__).resolve().parents[1]
CREATIVE_CATALOG_PATH = SKILL_ROOT / "references" / "starryear" / "catalog.json"


def normalize_source_path(value: Path) -> Path:
    """Resolve common pasted-path escaping without silently changing real paths."""
    candidate = value.expanduser()
    if candidate.exists():
        return candidate.resolve()
    raw = str(candidate)
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


def confirmation_hash_payload(record: dict) -> dict:
    return {
        "config": record.get("config"),
        "executionMode": record.get("executionMode"),
        "resolvedCreativeRecipe": record.get("resolvedCreativeRecipe"),
        "creativeOutput": record.get("creativeOutput"),
        "resolvedPrompt": record.get("resolvedPrompt"),
    }


def canonical_json_sha256(value) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


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
    if int(record.get("schemaVersion") or 0) >= 4 or record.get("confirmationHash"):
        expected_confirmation_hash = canonical_json_sha256(confirmation_hash_payload(record))
        if record.get("confirmationHash") != expected_confirmation_hash:
            raise SystemExit("Confirmation settings hash mismatch")
    record["confirmationPath"] = str(confirmation_path)
    return record


def resolve_creative_recipe(recipe_id: str, source_count: int, confirmation: dict | None) -> dict | None:
    if not recipe_id or recipe_id == "none":
        return None
    try:
        catalog = json.loads(CREATIVE_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read creative recipe catalog {CREATIVE_CATALOG_PATH}: {exc}") from exc
    recipes: dict[str, dict] = {}
    for item in catalog.get("recipes", []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise SystemExit("Creative recipe catalog contains a malformed entry")
        recipes[item["id"]] = item
    recipe = recipes.get(recipe_id)
    if recipe is None:
        raise SystemExit(f"Unknown creative recipe: {recipe_id}")
    for key in ("titleZh", "recipePath"):
        if not isinstance(recipe.get(key), str):
            raise SystemExit(f"Creative recipe {recipe_id} is missing {key}")
    count_range = recipe.get("sourceCount")
    if (
        not isinstance(count_range, dict)
        or not isinstance(count_range.get("min"), int)
        or not isinstance(count_range.get("max"), int)
    ):
        raise SystemExit(f"Creative recipe {recipe_id} has an invalid sourceCount")
    minimum = count_range["min"]
    maximum = count_range["max"]
    if source_count < minimum or source_count > maximum:
        expected = str(minimum) if minimum == maximum else f"{minimum}-{maximum}"
        raise SystemExit(f"{recipe['titleZh']} requires {expected} source photographs; received {source_count}")
    recipe_root = (CREATIVE_CATALOG_PATH.parent / recipe["recipePath"]).resolve()
    if not (recipe_root / "SKILL.md").is_file():
        raise SystemExit(f"Creative recipe is incomplete: missing {recipe_root / 'SKILL.md'}")
    if confirmation is not None:
        frozen = confirmation.get("resolvedCreativeRecipe")
        if not isinstance(frozen, dict) or frozen.get("id") != recipe_id:
            raise SystemExit("Confirmation is missing the selected creative recipe metadata")
        if frozen.get("sourceCommit") != recipe.get("sourceCommit"):
            raise SystemExit("Creative recipe source revision does not match the installed catalog")
    return {
        "id": recipe["id"],
        "number": recipe.get("number", ""),
        "title_zh": recipe["titleZh"],
        "title_en": recipe.get("titleEn", ""),
        "summary_zh": recipe.get("summaryZh", ""),
        "source_count": count_range,
        "output": recipe.get("output", {}),
        "source_url": recipe.get("sourceUrl", ""),
        "source_commit": recipe.get("sourceCommit", ""),
        "recipe_root": str(recipe_root),
        "skill_path": str(recipe_root / "SKILL.md"),
        "shared_workflow_with": recipe.get("sharedWorkflowWith"),
    }


def resolve_creative_output_mode(value: str) -> dict:
    if value not in {"direct-effect", "original-assembly"}:
        raise SystemExit("Creative output mode must be direct-effect or original-assembly")
    return {
        "mode": value,
        "label_zh": "原版拼接" if value == "original-assembly" else "直接效果图",
        "original_assembly": value == "original-assembly",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an isolated photo refinement job.")
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--workflow", choices=["auto", "single", "batch"], default="auto")
    parser.add_argument("--confirmation-file", type=Path, help="Confirmation JSON created by Photo Refiner Studio")
    parser.add_argument("--preset", help="Confirmed named preset or custom for text-only fallback")
    parser.add_argument("--creative-recipe", default="none", help="Confirmed Starryear recipe id or none for text-only fallback")
    parser.add_argument("--creative-assembly-mode", choices=["direct-effect", "original-assembly"], default="direct-effect", help="Creative output: complete effect image by default, or the original evidence/assembly layout")
    parser.add_argument("--creative-from-base", action="store_true", help="Two-stage: first render the confirmed preset as an approved main image, then translate creatively from it (single-source direct-effect only)")
    parser.add_argument("--creative-upscale", action="store_true", help="Upscale the approved creative preview with 4X-UltraSharp (bundled engine) before detail recovery")
    parser.add_argument("--creative-hd-chain", action="store_true", help="Full HD creative chain: ordinary refinement to an approved HD master, creative draft on it, then style-faithful tiled redraw to native resolution (single-source direct-effect only)")
    parser.add_argument("--custom-prompt", default="")
    parser.add_argument("--custom-avoid", default="")
    parser.add_argument("--aspect-ratio", type=validate_aspect_ratio, default="original")
    parser.add_argument("--framing", choices=["preserve", "crop", "outpaint", "contain"], default="preserve")
    parser.add_argument("--resolution", type=validate_resolution, default="source-width")
    parser.add_argument("--output-format", choices=["png", "jpg", "both"], default="png")
    parser.add_argument("--consistency", choices=["strict", "balanced", "creative"], default="balanced")
    parser.add_argument("--master-frame", default="auto")
    parser.add_argument("--detail-mode", choices=["base-only", "face", "adaptive", "explicit"], default="adaptive")
    parser.add_argument("--detail-budget", choices=["fast", "balanced", "max"], help="Generation policy: fast=1 hard, balanced=3 soft/6 hard, max=5 soft/8 hard. Explicit CLI value overrides Studio default.")
    parser.add_argument("--detail-regions", default="", help="Comma-separated regions required for explicit detail mode")
    parser.add_argument("--keep-intermediates", action="store_true")
    parser.add_argument("--confirmed", action="store_true", help="Assert that the displayed settings were confirmed by the user")
    args = parser.parse_args()

    cli_detail_budget = args.detail_budget
    settings: dict = {}
    confirmation = None
    if args.confirmation_file:
        confirmation = load_confirmation(args.confirmation_file)
        ui_config = confirmation["config"]
        try:
            settings = validated_panel_settings(ui_config)
        except SettingError as exc:
            raise SystemExit(str(exc)) from exc
        args.workflow = settings["workflow"]
        args.creative_recipe = ui_config.get("creativeRecipe", "none")
        args.creative_assembly_mode = settings["creative_assembly_mode"] or "direct-effect"
        # Explicit CLI opt-ins may raise a confirmed false to true, but Studio
        # values are type-checked by job_contract before they reach this point.
        args.creative_from_base = args.creative_from_base or bool(settings.get("creative_from_base"))
        args.creative_hd_chain = args.creative_hd_chain or bool(settings.get("creative_hd_chain"))
        args.creative_upscale = args.creative_upscale or bool(settings.get("creative_upscale"))
        args.preset = ui_config["preset"]
        args.custom_prompt = settings["custom_prompt"] or ""
        args.custom_avoid = settings["custom_avoid"] or ""
        args.aspect_ratio = settings["aspect_ratio"]
        args.framing = settings["framing"]
        args.resolution = settings["resolution"]
        delivery_mode = settings["delivery_mode"]
        ui_mode = settings["ui_mode"] or "simple"
        args.output_format = settings["output_format"]
        args.keep_intermediates = bool(settings["keep_intermediates"])
        args.consistency = settings["consistency"]
        args.detail_mode = settings["detail_mode"]
        args.detail_budget = cli_detail_budget or settings["generation_budget"] or "balanced"
        args.detail_regions = settings["detail_regions"] or ""
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
    creative_recipe = resolve_creative_recipe(args.creative_recipe, len(sources), confirmation)
    creative_output = resolve_creative_output_mode(args.creative_assembly_mode) if creative_recipe else None
    execution_mode = "creative-translation" if creative_recipe else "photo-refinement"
    if creative_output is not None:
        # Single-source direct-effect canvases follow the confirmed panel
        # aspect ratio (original = the source photograph's own ratio).
        # Original-assembly and multi-photo recipes keep the recipe's
        # documented output structure because their deterministic layout
        # and panel geometry depend on it.
        recipe_ratio = str((creative_recipe.get("output") or {}).get("aspectRatio") or "recipe-documented")
        inherit_panel_ratio = creative_output["mode"] == "direct-effect" and len(sources) == 1
        creative_output["aspect_ratio_source"] = "panel" if inherit_panel_ratio else "recipe"
        creative_output["recipe_aspect_ratio"] = recipe_ratio
        creative_output["effective_aspect_ratio"] = str(args.aspect_ratio) if inherit_panel_ratio else recipe_ratio
        # Opt-in two-stage flow: stage 1 renders the confirmed preset as an
        # approved main image; stage 2 translates creatively with that image
        # as look reference while identity stays anchored to the source.
        hd_chain_eligible = creative_output["mode"] == "direct-effect" and len(sources) == 1
        if args.creative_hd_chain and not hd_chain_eligible:
            raise SystemExit("HD creative chain requires exactly one source and direct-effect creative output")
        hd_chain = bool(args.creative_hd_chain) and hd_chain_eligible
        if hd_chain and delivery_mode != "preview-first":
            raise SystemExit("HD creative chain requires preview-first because both HD master and creative draft need approval")
        creative_output["upstream_binding"] = (
            "hd-master"
            if hd_chain
            else (
                "look-master"
                if args.creative_from_base and creative_output["mode"] == "direct-effect" and len(sources) == 1
                else "direction-only"
            )
        )
        creative_output["hd_chain"] = hd_chain
        creative_output["upscale"] = {
            "enabled": bool(getattr(args, "creative_upscale", False)) and not hd_chain,
            "engine": "auto",
            "note": (
                "Disabled for hd-master: final resolution is produced by style-faithful tile redraw."
                if hd_chain
                else "After approval the preview is upscaled with 4X-UltraSharp when the bundled engine is installed (upscale_image.py --install-engine, no ComfyUI needed); patch planning then runs on the raised canvas. Without an engine an honest Lanczos fallback is recorded."
            ),
        }
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
    normal_soft, normal_hard = normal_budget(args.detail_budget)
    stage_budgets = {
        extent: dict(zip(("soft", "hard"), creative_safe_budget(args.detail_budget, extent)))
        for extent in sorted(PORTRAIT_EXTENTS)
    }
    scene_soft, scene_hard = creative_safe_budget(args.detail_budget, "scene")
    patch_scope = "head-and-face" if confirmation is None else (settings.get("patch_scope") or "head-and-face")
    hd_chain = (
        bool(getattr(args, "creative_hd_chain", False))
        and creative_output is not None
        and creative_output["mode"] == "direct-effect"
        and len(sources) == 1
    )
    creative_recovery_eligible = (
        creative_recipe is not None
        and creative_output is not None
        and creative_output["mode"] == "direct-effect"
        and len(sources) == 1
        and not hd_chain
    )

    normal_detail_manifest = {
        "mode": args.detail_mode,
        "generation_budget": args.detail_budget,
        "soft_generated_patch_budget": normal_soft,
        "hard_generated_patch_ceiling": normal_hard,
        "max_generated_patches": normal_hard,
        "adaptive_overflow": args.detail_budget != "fast",
        "planner": PLANNER_NORMAL,
        "mask_mode": "lightweight",
        "regions": detail_regions,
        "patch_scope": patch_scope,
        "head_patch": patch_scope == "head-and-face",
        "pixel_budget_thresholds": dict(PIXEL_BUDGET_THRESHOLDS),
    }
    creative_safe_detail_manifest = {
        "mode": "creative-safe-adaptive",
        "generation_budget": args.detail_budget,
        "adaptive_overflow": args.detail_budget != "fast",
        "planner": PLANNER_CREATIVE_SAFE,
        "mask_mode": "lightweight",
        "regions": [],
        "patch_scope": "adaptive-subject",
        "head_patch": True,
        "allowed_region_types": ["face", "head", "hand", "costume", "prop", "architecture", "generic"],
        "background_generation": False,
        "look_authority": "CREATIVE_LOOK_MASTER",
        "identity_authority": "SOURCE_MASTER",
        # The operative soft/hard ceilings depend on the portrait coverage the
        # Vision pass reports, so the manifest carries the whole table instead of
        # one permissive number an agent could read as permission to over-generate.
        "portrait_budget_policy": stage_budgets,
        "scene_budget_policy": {"soft": scene_soft, "hard": scene_hard},
        "absolute_generated_patch_ceiling": creative_safe_ceiling(args.detail_budget),
        "pixel_budget_thresholds": {
            key: value for key, value in PIXEL_BUDGET_THRESHOLDS.items() if key != "background"
        },
        "frequency_policy": {
            "low_frequency": "creative-look-master-only",
            "mid_frequency": "creative-look-master-dominant",
            "high_frequency": "registered-detail-patch",
        },
        "note": "Single-source direct-effect creative work must run adaptive high-resolution recovery after approval. Preserve the approved creative look; use SOURCE MASTER only for identity, anatomy, factual geometry and construction.",
    }
    creative_disabled_detail_manifest = {
        "mode": "not-applicable",
        "generation_budget": "recipe-controlled",
        "soft_generated_patch_budget": 0,
        "hard_generated_patch_ceiling": 0,
        "max_generated_patches": 0,
        "adaptive_overflow": False,
        "planner": "creative-recipe",
        "mask_mode": "recipe-controlled",
        "regions": [],
        "patch_scope": "none",
        "head_patch": False,
        "note": (
            "Do not run ordinary recovery over original assembled creative artwork."
            if args.creative_assembly_mode == "original-assembly"
            else "Multi-source creative recovery is disabled until region ownership can be preserved safely."
        ),
    }
    detail_manifest = (
        normal_detail_manifest
        if creative_recipe is None or hd_chain
        else creative_safe_detail_manifest
        if creative_recovery_eligible
        else creative_disabled_detail_manifest
    )

    manifest = {
        "version": 2,
        "release_version": RELEASE_VERSION,
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
        "execution_mode": execution_mode,
        "creative_recipe": creative_recipe,
        "authority_model": {
            "source_master": ["identity", "anatomy", "factual_geometry", "construction", "authentic_material_reference"],
            "look_master": ["approved_color", "lighting", "tone", "atmosphere", "visual_style"],
            "detail_patch": ["registered_mid_frequency_detail", "registered_high_frequency_detail"],
        } if creative_recipe is None else ({
            "source_evidence": ["unchanged_source_pixels", "identity", "factual_scene_truth"],
            "generated_panels": ["recipe_specific_visual_translation"],
            "deterministic_assembly": ["layout", "source_pixel_placement", "final_dimensions"],
        } if args.creative_assembly_mode == "original-assembly" else ({
            "stage_1_refinement": {
                "source_master": ["identity", "anatomy", "factual_geometry", "construction", "authentic_material_reference"],
                "look_master": ["approved_color", "lighting", "tone", "atmosphere", "visual_style"],
                "detail_patch": ["registered_mid_frequency_detail", "registered_high_frequency_detail"],
            },
            "stage_2_creative": {
                "hd_master": ["identity", "refined_detail", "approved_photographic_structure"],
                "creative_draft": ["creative_style", "materials", "visual_grammar"],
            },
            "stage_3_tile_redraw": {
                "creative_draft": ["style_authority"],
                "hd_master": ["identity_and_structure_reference"],
                "tile_redraw": ["delivery_resolution_detail"],
            },
        } if hd_chain else ({
            "source_master": ["identity", "anatomy", "factual_geometry", "construction", "authentic_material_reference"],
            "creative_look_master": ["approved_creative_canvas", "color", "lighting", "tone", "materials", "visual_grammar"],
            "creative_detail_patch": ["registered_mid_frequency_detail", "registered_high_frequency_detail"],
        } if creative_recovery_eligible else {
            "source_reference": ["identity", "theme", "source-derived motifs"],
            "generated_artwork": ["complete creative canvas", "recipe visual grammar"],
            "deterministic_assembly": [],
        }))),
        "creative_output": creative_output,
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
        "base_preview": {"required": delivery_mode == "preview-first" and (workflow == "single" or creative_recipe is not None), "approved": False},
        "creative_preview": {"required": hd_chain, "approved": False},
        "output_format": args.output_format,
        "batch": {
            "consistency": args.consistency,
            "master_frame": args.master_frame,
            "shared_identity": creative_recipe is None,
            "shared_scene": creative_recipe is None,
            "shared_prompt": creative_recipe is None,
            "master_frame_approved": None if workflow == "single" or creative_recipe is not None else False,
        },
        "detail": detail_manifest,
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
        "patch_observation": {
            "enabled": detail_manifest.get("mode") != "not-applicable",
            "recorder": "scripts/record_patch_observation.py",
            "actual_size_source": "generated-image-file",
            "requested_size_source": "generation-call",
            "note": "Record every generated local detail patch after it is materialized inside the job directory. Never infer actual size from API/client documentation.",
        },
        "patch_observations": [],
        "patch_observation_summary": {
            "count": 0,
            "size_match_count": 0,
            "size_mismatch_count": 0,
            "actual_sizes": [],
            "requested_sizes": [],
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
