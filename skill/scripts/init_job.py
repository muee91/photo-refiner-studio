#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from resolve_prompt import resolve_prompt
from validate_graph import validate_graph
from compile_graph_plan import compile_plan


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


def load_confirmation(path_value: Path) -> dict:
    confirmation_path = path_value.expanduser().resolve()
    confirmation_root = (Path.home() / ".codex" / "photo-refiner-flow" / "confirmed").resolve()
    if not confirmation_path.is_file() or not confirmation_path.is_relative_to(confirmation_root):
        raise SystemExit("Confirmation file must exist inside ~/.codex/photo-refiner-flow/confirmed")
    record = json.loads(confirmation_path.read_text(encoding="utf-8"))
    if record.get("confirmedBy") != "photo-refiner-flow-studio" or not record.get("confirmationId"):
        raise SystemExit("Invalid Photo Refiner Flow settings confirmation")
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


def load_flow_graph(path_value: Path) -> dict:
    graph_path = path_value.expanduser().resolve()
    graph_root = (Path.home() / ".codex" / "photo-refiner-flow" / "graphs").resolve()
    if not graph_path.is_file() or not graph_path.is_relative_to(graph_root):
        raise SystemExit("Flow graph must exist inside ~/.codex/photo-refiner-flow/graphs")
    try:
        record = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read Flow graph: {exc}") from exc
    if record.get("confirmedBy") != "photo-refiner-flow-studio":
        raise SystemExit("Invalid Photo Refiner Flow graph confirmation")
    graph = record.get("graph")
    if not isinstance(graph, dict) or graph.get("graphId") != record.get("graphId"):
        raise SystemExit("Flow graph record is malformed")
    try:
        validate_graph(graph)
        plan = compile_plan(graph)
    except ValueError as exc:
        raise SystemExit(f"Invalid Photo Refiner Flow graph: {exc}") from exc
    record["graphPath"] = str(graph_path)
    record["compiledPlan"] = plan
    return record


def enabled_graph_node(graph: dict, node_type: str) -> dict | None:
    for node in graph.get("nodes", []):
        if node.get("enabled") is True and node.get("type") == node_type:
            return node
    return None


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
    parser.add_argument("--graph-file", type=Path, help="Confirmed graph JSON created by Photo Refiner Flow")
    parser.add_argument("--confirmation-file", type=Path, help="Fallback settings confirmation JSON created by Photo Refiner Flow")
    parser.add_argument("--preset", help="Confirmed named preset or custom for text-only fallback")
    parser.add_argument("--creative-recipe", default="none", help="Confirmed Starryear recipe id or none for text-only fallback")
    parser.add_argument("--creative-assembly-mode", choices=["direct-effect", "original-assembly"], default="direct-effect", help="Creative output: complete effect image by default, or the original evidence/assembly layout")
    parser.add_argument("--creative-from-base", action="store_true", help="Two-stage: first render the confirmed preset as an approved main image, then translate creatively from it (single-source direct-effect only)")
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

    if args.graph_file and args.confirmation_file:
        raise SystemExit("Use either --graph-file or --confirmation-file, not both")

    sources = validate_source_files(args.sources)
    cli_detail_budget = args.detail_budget
    confirmation = None
    flow_graph_record = None
    flow_graph = None
    flow_plan = None
    flow_recovery_mode = None
    flow_style_strength = None
    flow_patch_scope = "head-and-face"

    if args.graph_file:
        flow_graph_record = load_flow_graph(args.graph_file)
        flow_graph = flow_graph_record["graph"]
        flow_plan = flow_graph_record["compiledPlan"]
        source_node = enabled_graph_node(flow_graph, "source")
        look_node = enabled_graph_node(flow_graph, "look")
        creative_node = enabled_graph_node(flow_graph, "creative-effect")
        approval_node = enabled_graph_node(flow_graph, "approval")
        recovery_node = enabled_graph_node(flow_graph, "recovery")
        delivery_node = enabled_graph_node(flow_graph, "delivery")
        if not all((source_node, look_node, approval_node, delivery_node)):
            raise SystemExit("Flow graph is missing a required node")
        expected_count = int(source_node["config"].get("sourceCount", 0))
        if expected_count != len(sources):
            raise SystemExit(f"Flow graph expects {expected_count} source photographs; received {len(sources)}")

        look_config = look_node["config"]
        args.workflow = "batch" if len(sources) > 1 else "single"
        args.preset = look_config.get("preset", "natural-cinematic")
        args.custom_prompt = look_config.get("customPrompt", "")
        args.custom_avoid = look_config.get("customAvoid", "")
        args.aspect_ratio = validate_aspect_ratio(str(look_config.get("aspectRatio", "original")))
        args.framing = look_config.get("framing", "preserve")
        if args.framing not in {"preserve", "crop", "outpaint", "contain"}:
            raise SystemExit("Flow look node has invalid framing")
        flow_style_strength = float(look_config.get("styleStrength", 45))
        if not 0 <= flow_style_strength <= 100:
            raise SystemExit("Flow look styleStrength must be 0-100")

        if creative_node:
            creative_config = creative_node["config"]
            args.creative_recipe = creative_config.get("recipeId", "none")
            args.creative_assembly_mode = creative_config.get("mode", "direct-effect")
            args.creative_from_base = look_config.get("renderMode", "look-master") == "look-master"
        else:
            args.creative_recipe = "none"
            args.creative_assembly_mode = "direct-effect"
            args.creative_from_base = False

        approval_config = approval_node["config"]
        delivery_mode = approval_config.get("deliveryMode", "preview-first")
        if delivery_mode not in {"preview-first", "one-click"}:
            raise SystemExit("Flow approval node has invalid deliveryMode")

        delivery_config = delivery_node["config"]
        args.resolution = validate_resolution(str(delivery_config.get("resolution", "source-width")))
        args.output_format = delivery_config.get("outputFormat", "jpg")
        if args.output_format not in {"png", "jpg", "both"}:
            raise SystemExit("Flow delivery node has invalid outputFormat")
        args.keep_intermediates = bool(delivery_config.get("keepIntermediates", False))

        if recovery_node:
            recovery_config = recovery_node["config"]
            flow_recovery_mode = recovery_config.get("mode", "normal")
            args.detail_mode = recovery_config.get("detailMode", "adaptive")
            args.detail_budget = cli_detail_budget or recovery_config.get("generationBudget", "balanced")
            flow_patch_scope = recovery_config.get("patchScope", "head-and-face")
        else:
            flow_recovery_mode = "disabled"
            args.detail_mode = "base-only"
            args.detail_budget = cli_detail_budget or "balanced"
        args.detail_regions = ""
        args.consistency = "balanced"
        ui_mode = "flow"

        try:
            resolved_prompt = resolve_prompt(args.preset, args.custom_prompt, args.custom_avoid)
        except (OSError, ValueError, KeyError) as exc:
            raise SystemExit(str(exc)) from exc
        resolved_prompt["default_strength"] = flow_style_strength
        digest_source = json.dumps(
            {key: value for key, value in resolved_prompt.items() if key != "prompt_hash"},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        resolved_prompt["prompt_hash"] = hashlib.sha256(digest_source).hexdigest()

    elif args.confirmation_file:
        confirmation = load_confirmation(args.confirmation_file)
        ui_config = confirmation["config"]
        args.workflow = ui_config["workflow"]
        args.creative_recipe = ui_config.get("creativeRecipe", "none")
        args.creative_assembly_mode = ui_config.get("creativeAssemblyMode", "direct-effect")
        # The panel no longer carries a two-stage control; the choice is
        # offered conversationally, so an explicit CLI flag must survive a
        # confirmation whose config predates or omits the field.
        args.creative_from_base = args.creative_from_base or bool(ui_config.get("creativeFromBase", False))
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
            raise SystemExit("Refusing to initialize: confirm a Flow graph/settings configuration or pass --confirmed for text fallback")
        if not args.preset:
            raise SystemExit("--preset is required for text-only confirmed initialization")
        try:
            resolved_prompt = resolve_prompt(args.preset, args.custom_prompt, args.custom_avoid)
        except (OSError, ValueError, KeyError) as exc:
            raise SystemExit(str(exc)) from exc
        delivery_mode = "preview-first"
        ui_mode = "simple"
        args.detail_budget = args.detail_budget or "balanced"

    creative_recipe = resolve_creative_recipe(args.creative_recipe, len(sources), confirmation)
    if flow_graph is not None and creative_recipe is not None:
        creative_node = enabled_graph_node(flow_graph, "creative-effect")
        frozen_commit = (creative_node or {}).get("config", {}).get("sourceCommit")
        if frozen_commit and frozen_commit != creative_recipe.get("source_commit"):
            raise SystemExit("Flow graph creative recipe source revision does not match the installed catalog")
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
        creative_output["upstream_binding"] = (
            "look-master"
            if args.creative_from_base and creative_output["mode"] == "direct-effect" and len(sources) == 1
            else "direction-only"
        )
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

    output_root = args.output_root or (sources[0].parent / "_photo_refiner_flow")
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
    budget_policy = {
        "fast": {"soft": 1, "hard": 1},
        "balanced": {"soft": 3, "hard": 6},
        "max": {"soft": 5, "hard": 8},
    }

    if creative_recipe is None:
        detail_manifest = {
            "mode": args.detail_mode,
            "generation_budget": args.detail_budget,
            "soft_generated_patch_budget": budget_policy[args.detail_budget]["soft"],
            "hard_generated_patch_ceiling": budget_policy[args.detail_budget]["hard"],
            "max_generated_patches": budget_policy[args.detail_budget]["hard"],
            "adaptive_overflow": args.detail_budget != "fast",
            "planner": "adaptive-value-merge-v2.2",
            "mask_mode": "lightweight",
            "regions": detail_regions,
            "patch_scope": flow_patch_scope if flow_graph is not None else ("head-and-face" if confirmation is None else ui_config.get("detail", {}).get("patchScope", "head-and-face")),
            "head_patch": (flow_patch_scope == "head-and-face") if flow_graph is not None else (True if confirmation is None else ui_config.get("detail", {}).get("patchScope", "head-and-face") == "head-and-face"),
            "pixel_budget_thresholds": {
                "face": 0.85, "hand": 0.75, "head": 0.65, "costume": 0.50,
                "prop": 0.50, "architecture": 0.50, "background": 0.30, "generic": 0.50,
            },
        }
    elif flow_graph is not None and flow_recovery_mode == "creative-safe":
        detail_manifest = {
            "mode": "creative-safe",
            "generation_budget": args.detail_budget,
            "soft_generated_patch_budget": min(2, budget_policy[args.detail_budget]["soft"]),
            "hard_generated_patch_ceiling": min(3, budget_policy[args.detail_budget]["hard"]),
            "max_generated_patches": min(3, budget_policy[args.detail_budget]["hard"]),
            "adaptive_overflow": False,
            "planner": "adaptive-value-merge-v2.2",
            "mask_mode": "lightweight",
            "regions": [],
            "patch_scope": flow_patch_scope,
            "head_patch": flow_patch_scope == "head-and-face",
            "allowed_region_types": ["face", "head", "hand", "costume", "prop"],
            "background_generation": False,
            "look_authority": "LOOK_AB",
            "identity_authority": "SOURCE_MASTER",
            "note": "Creative-safe recovery preserves the approved A+B look and uses fewer, lower-impact local patches.",
        }
    else:
        detail_manifest = {
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
            "note": ("Do not run ordinary recovery over original assembled creative artwork." if args.creative_assembly_mode == "original-assembly" else "Recovery disabled for this creative graph."),
        }

    manifest = {
        "version": 2,
        "release_version": "3.0-flow",
        "created_at": now.isoformat(),
        "confirmed_at": now.isoformat(),
        "product": "photo-refiner-flow",
        "graph_confirmation": None if flow_graph_record is None else {
            "id": flow_graph_record["graphId"],
            "path": flow_graph_record["graphPath"],
            "confirmed_at": flow_graph_record.get("confirmedAt"),
            "confirmed_by": flow_graph_record.get("confirmedBy"),
            "plan_hash": (flow_plan or {}).get("planHash"),
        },
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
        } if args.creative_assembly_mode == "original-assembly" else {
            "source_reference": ["identity", "theme", "source-derived motifs"],
            "generated_artwork": ["complete creative canvas", "recipe visual grammar"],
            "deterministic_assembly": [],
        }),
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
        "retouch": (
            {
                "style_strength": flow_style_strength,
                "detail_strength": 60,
                "source": "flow-graph",
            }
            if flow_graph is not None
            else ({
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
            })
        ),
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
