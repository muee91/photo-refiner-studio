#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path


LABELS = {
    "global": {
        "exposure": "exposure compensation",
        "contrast": "contrast",
        "highlights": "highlight recovery",
        "shadows": "shadow detail",
        "temperature": "color temperature",
        "tint": "green-magenta tint",
        "saturation": "saturation",
        "vibrance": "vibrance",
        "clarity": "local clarity",
        "dehaze": "dehaze",
        "denoise": "noise reduction",
        "sharpen": "detail sharpening",
        "grain": "fine photographic grain",
    },
    "portrait": {
        "skinSmoothing": "natural skin smoothing while retaining pores",
        "blemishRemoval": "temporary blemish removal",
        "skinToneEven": "subtle skin-tone evening",
        "eyeEnhance": "natural eye and catchlight enhancement",
        "teethWhiten": "subtle natural teeth whitening",
        "faceSlim": "identity-preserving face slimming",
        "jawline": "subtle jawline definition",
        "eyeSize": "identity-preserving eye-size adjustment",
    },
    "body": {
        "waistSlim": "anatomy-preserving waist slimming",
        "armSlim": "anatomy-preserving arm slimming",
        "legSlim": "anatomy-preserving leg slimming",
        "legLength": "perspective-consistent leg-length adjustment",
        "shoulderAdjust": "anatomy-preserving shoulder adjustment",
    },
    "clothing": {
        "wrinkleReduction": "reduce distracting clothing wrinkles while preserving intended pleats, seams, drape, embroidery, and fabric weave",
        "preserveTexture": "preserve authentic fabric texture",
        "lintRemoval": "remove visible lint and loose fibers",
        "stainRemoval": "remove small clothing stains",
        "silhouetteCleanup": "clean the garment silhouette without redesigning it",
    },
    "background": {
        "cleanup": "clean minor background clutter",
        "removeDistractors": "remove small non-narrative distractions",
        "bokeh": "increase optically plausible background separation",
        "skyEnhance": "enhance the existing sky without inventing weather",
        "foliageEnhance": "enhance foliage detail without repeated leaf patterns",
        "architectureLines": "preserve and clarify architectural lines",
    },
}


def signed_instruction(label: str, value: float) -> str:
    direction = "increase" if value > 0 else "decrease"
    return f"{direction} {label} at strength {abs(value):g}/100"


def positive_instruction(label: str, value: float, maximum: int = 100) -> str:
    return f"{label} at strength {value:g}/{maximum}"


def style_execution_level(value: float) -> str:
    if value < 25:
        return "minimal"
    if value < 50:
        return "subtle"
    if value < 75:
        return "visible"
    if value < 90:
        return "strong"
    return "transformative"


def style_execution_intent(value: float) -> str:
    level = style_execution_level(value)
    return {
        "minimal": "Apply only minimal polish; keep the image visually close to the source.",
        "subtle": "Apply a subtle but perceptible grade; source fidelity remains the dominant visual outcome.",
        "visible": "Apply a clearly visible cinematic grade; do not return a near-identical source image.",
        "strong": (
            "Make the requested cinematic grade unmistakably visible in the delivered image. "
            "Prioritize the requested light, palette, atmosphere, tonal separation, and film response over a "
            "conservative near-identical retouch while preserving identity and scene geometry."
        ),
        "transformative": (
            "Apply a bold, highly visible stylistic transformation. Preserve identity and core geometry, "
            "but allow stronger lighting, palette, atmosphere, and tonal redesign."
        ),
    }[level]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a deterministic image-edit brief from a confirmed Photo Refiner job.")
    parser.add_argument("job", type=Path, help="Path to job.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    job_path = args.job.expanduser().resolve()
    data = json.loads(job_path.read_text(encoding="utf-8"))
    resolved = data.get("resolved_prompt") or {}
    if not data.get("confirmed_at") or not resolved.get("prompt"):
        raise SystemExit("Job is not confirmed or has no frozen resolved prompt")

    execution_mode = data.get("execution_mode", "photo-refinement")
    creative_output = data.get("creative_output") or {}
    two_stage_look_master = (
        execution_mode == "creative-translation"
        and creative_output.get("upstream_binding") == "look-master"
    )
    creative_direct = execution_mode == "creative-translation" and not two_stage_look_master

    retouch = data.get("retouch") or {}
    instructions = []
    style_strength = retouch.get("style_strength")
    style_intent = None
    style_level = None
    if isinstance(style_strength, (int, float)):
        style_level = style_execution_level(style_strength)
        style_intent = style_execution_intent(style_strength)
        instructions.append(f"apply the frozen style using the {style_level} execution level: {style_intent}")

    for group, labels in LABELS.items():
        values = retouch.get(group) or {}
        if group in {"portrait", "body"} and values.get("enabled") is False:
            continue
        for key, label in labels.items():
            value = values.get(key, 0)
            if not isinstance(value, (int, float)) or value == 0:
                continue
            if group == "global" and key not in {"denoise", "sharpen", "grain"}:
                instructions.append(signed_instruction(label, value))
            else:
                maximum = 40 if group in {"portrait", "body"} and key in {"faceSlim", "jawline", "eyeSize", "waistSlim", "armSlim", "legSlim", "legLength", "shoulderAdjust"} else 100
                instructions.append(positive_instruction(label, value, maximum))

    detail = data.get("detail") or {}
    detail_strength = retouch.get("detail_strength")
    if isinstance(detail_strength, (int, float)):
        region_text = ", ".join(detail.get("regions") or []) or "visible subject and scene regions"
        instructions.append(f"{detail.get('mode', 'adaptive')} detail recovery at strength {detail_strength:g}/100 for {region_text}")
    generation_budget = detail.get("generation_budget")
    soft_generated_patches = detail.get("soft_generated_patch_budget")
    hard_generated_patches = detail.get("hard_generated_patch_ceiling") or detail.get("max_generated_patches")
    if generation_budget and hard_generated_patches:
        if soft_generated_patches and soft_generated_patches < hard_generated_patches:
            instructions.append(
                f"follow the {generation_budget} adaptive generation budget: normally stay within {soft_generated_patches} generated detail patches, but allow high-value regions that pass scale/pixel-budget gates to overflow up to the hard ceiling of {hard_generated_patches}; never treat either number as a quota"
            )
        else:
            instructions.append(
                f"follow the {generation_budget} generation budget and prefer the fewest patches that can recover the needed detail; do not exceed {hard_generated_patches} generated detail patches unless the user explicitly overrides the limit"
            )
    planner = detail.get("planner")
    if planner:
        instructions.append(f"use the {planner} planner principle: treat the generation budget as a ceiling, merge regions before splitting them, skip low-value regions, and avoid micro-patches for facial parts, hair strands, sleeves, or ornaments")
    instructions.append(
        "treat the approved base as LOOK MASTER: preserve its approved low-frequency color, lighting, tone, atmosphere, and style; detail patches may add registered spatial detail but must not redefine the approved look"
    )
    instructions.append(
        "treat the original photograph as SOURCE MASTER for identity, anatomy, garment/object construction, factual scene geometry, and authentic material reference"
    )
    face_requested = detail.get("mode") == "face" or any(
        token in region.lower() for region in detail.get("regions") or [] for token in ("face", "人脸", "脸部", "五官")
    )
    if face_requested:
        instructions.append(
            "for every face-detail tile, include the full forehead, temples, cheeks, jawline, chin, and surrounding transition skin; do not end a tile at the lips, jaw, or chin"
        )
    patch_scope = detail.get("patch_scope", "head-and-face")
    if patch_scope == "head-and-face":
        instructions.append(
            "use a person-priority detail plan: first a broad costume-and-body-structure patch preserving garment silhouette, sleeves, collar, waist, hem, embroidery, weave, and drape; then a large head-and-hair-and-hair-ornaments patch covering the complete visible hair mass; then a tighter face patch for facial features and chin; the face must occupy most of the face patch (approximately 60–80% of its height), with only a narrow forehead, cheek, jaw, chin, and transition-skin margin; never use the face patch as the sole hair or costume restoration region"
        )
    elif patch_scope == "face-only":
        instructions.append("restore only the complete face outline and chin; do not infer or sharpen hair outside the face patch")
    if two_stage_look_master:
        instructions.append(
            "two-stage creative translation, stage 1: render the confirmed preset as the main image for explicit user approval; run the creative pass only after that approval, keeping identity anchored to the original source photograph"
        )

    invariants = (
        "Preserve identity, expression, gaze, anatomy, hands, joints, pose, clothing construction, intentional "
        "pleats and embroidery, meaningful props, architecture, terrain, reflections, contact shadows, and scene "
        "geometry. Keep natural skin and material texture. Do not use these preservation constraints to suppress a "
        "requested visible color, lighting, atmosphere, contrast, or film-response change. Reject doubled edges, "
        "warped anatomy, repeated foliage, invented objects, text, logos, borders, and watermarks."
    )
    brief = {
        "preset": resolved.get("preset"),
        "style_strength": style_strength,
        "style_execution_level": style_level,
        "style_execution_intent": style_intent,
        "base_prompt": resolved["prompt"],
        "avoid": resolved.get("avoid", ""),
        "requested_adjustments": instructions,
        "invariants": invariants,
        "authority_model": data.get("authority_model"),
        "working_color_space": data.get("working_color_space", "sRGB"),
        "framing": data.get("framing", "preserve"),
        "aspect_ratio": data.get("aspect_ratio", "original"),
        "resolution": data.get("resolution", "source-width"),
        "delivery_mode": data.get("delivery_mode", "preview-first"),
    }
    if creative_direct:
        # Single-pass creative translation: the recipe is the sole structural
        # authority. The frozen preset is demoted to a look direction, and the
        # photographic-preservation invariants would contradict the recipe's
        # non-photographic grammar, so the brief carries a creative variant.
        recipe = data.get("creative_recipe") or {}
        brief = {
            "preset": resolved.get("preset"),
            "style_strength": style_strength,
            "upstream_style_direction": (
                "Apply the frozen preset only as an upstream look direction (color, light, tone, atmosphere). "
                "It must not add a photorealistic rendering pass; wherever it conflicts with the recipe's guardrails, the recipe's guardrails win."
            ),
            "creative_recipe": recipe,
            "recipe_instruction": (
                f"Execute the selected Starryear recipe as the sole structural authority: read "
                f"{recipe.get('skill_path', 'the recipe SKILL.md')} and every prompt, reference, and script it requires, "
                "then produce the creative artwork it defines."
            ),
            "avoid": resolved.get("avoid", ""),
            "requested_adjustments": [],
            "invariants": (
                "Subject identity and theme must stay traceable to the source photograph(s) exactly as the recipe requires. "
                "The recipe's guardrails override any photographic-preservation language. "
                "Never run ordinary detail patches over the creative artwork."
            ),
            "authority_model": data.get("authority_model"),
            "working_color_space": data.get("working_color_space", "sRGB"),
            "framing": data.get("framing", "preserve"),
            "aspect_ratio": creative_output.get("effective_aspect_ratio") or data.get("aspect_ratio", "original"),
            "resolution": data.get("resolution", "source-width"),
            "delivery_mode": data.get("delivery_mode", "preview-first"),
        }
    canonical = json.dumps(brief, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    brief["edit_brief_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    rendered = json.dumps(brief, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        output = args.output.expanduser().resolve()
        if output == job_path:
            raise SystemExit("Refusing to overwrite job.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
