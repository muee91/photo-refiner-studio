---
name: photo-refiner-flow
description: Node-based photographic refinement with Look A, optional Starryear Effect B, explicit approval, creative-safe high-resolution recovery, and independent delivery.
---

# Photo Refiner Flow

Photo Refiner Flow is the independently installable node-workflow edition of Photo Refiner. It coexists with the original `photo-refiner` Skill and uses separate MCP tools and local state.

Its controlled graph is:

```text
Source -> Look A -> Effect B? -> Approval -> Recovery? -> Delivery
```

The existing Photo Refiner image-processing scripts remain the backend; the graph is the authoritative workflow configuration for Flow.

## Flow graph contract

Read `references/node-graph.md` before changing graph semantics. Validate confirmed graphs with `scripts/validate_graph.py` and compile them with `scripts/compile_graph_plan.py`.

Look A has two execution semantics:

- `direction-only`: A contributes visual direction without spending a separate generation.
- `look-master`: A renders a real LOOK_A before Effect B.

Effect B is optional. `direct-effect` produces one complete creative image; `original-assembly` follows the selected Starryear recipe's evidence/layout structure.

Recovery policy:

- no Effect B -> `normal`
- single-source `direct-effect` -> `creative-safe`
- `original-assembly` -> disabled
- multi-source creative recipes -> disabled in graph v1

The UI host is optional. A confirmed graph remains usable through its `graphPath` even if the embedded UI is unavailable.

## 1. Intent gate

A question about this Skill is **not** an edit request. If the user asks whether it can edit, how it works, how to optimize it, what its limits are, or asks to inspect/review the Skill, answer or inspect only. **Do not invoke image generation.**

Start a refinement job only when the user explicitly asks to edit/refine a **specific source photograph**. Even then, do not generate until the initialization settings have been shown and explicitly confirmed.

## 2. Creative translation gate

Normal Photo Refiner work and creative translation are separate execution modes:

- `photo-refinement` uses SOURCE MASTER / LOOK MASTER / DETAIL PATCH as described below.
- `creative-translation` is an optional second stage after the user has chosen the normal style preset. It uses a selected Starryear recipe with either a complete direct effect image (the default) or the original evidence/panel assembly. It runs only when the user enables Effect B in Photo Refiner Flow or explicitly confirms the same graph through a fallback.

Never flatten a bundled creative recipe into a color preset or append its name to the normal refinement prompt. The selected normal preset remains the frozen upstream visual direction; apply it deliberately alongside the recipe-specific translation instructions, rather than replacing it or treating the result as a simple filter. When creative translation is selected:

1. Read [references/starryear/catalog.md](references/starryear/catalog.md) and [references/starryear/catalog.json](references/starryear/catalog.json).
2. Validate the actual source count against the selected catalog entry.
3. Read the selected `recipePath/SKILL.md` completely, then read every prompt, reference, and script that recipe requires.
4. Resolve `creative_assembly_mode` from the confirmed settings. It defaults to `direct-effect`; `original-assembly` is an explicit alternative. Direct-effect generates one complete creative effect image using the frozen normal preset as its upstream visual direction plus the recipe's theme, prompt semantics, references, source-derived motifs, and visual grammar; it must not attach an unchanged source-evidence strip, place the original beside/below the artwork, crop an original assembly, or act as a simple filter. Original-assembly follows the recipe literally: preserve its evidence regions with actual source pixels, generate only its translated regions, and use its compositor. For single-source direct-effect jobs the creative canvas follows the confirmed panel aspect ratio (`original` means the source photograph's own ratio) instead of the recipe's documented output ratio; original-assembly and multi-photo recipes keep the recipe's documented output structure. `creative_output.aspect_ratio_source` / `effective_aspect_ratio` in `job.json` record the resolved choice. When `creative_output.upstream_binding` is `look-master` (`--creative-from-base`, offered conversationally: for a single-source direct-effect creative job in preview-first mode, ask once whether to 直接开始创意 or 先按预设出主图、确认后再创意), first run the Section 7 base pass with the frozen preset, show that main image, and continue only after explicit approval; the creative pass then anchors identity and motifs to the original source photograph and uses the approved main image only as its look reference, and the formal base-preview gate still applies to the creative artwork itself.
5. Default to preview-first. Present the generated direct effect preview or assembled original preview and stop for approval when the confirmed delivery mode is `preview-first`; one-click may continue without that pause.
6. Retry only failed generated regions. For direct-effect, retry the complete creative image; for original-assembly, retry only failed generated regions.
7. Do not run the ordinary face, head, garment, environment, or whole-image DETAIL PATCH stage over a completed creative collage. It can overwrite the translated art and create mixed-sharpness seams.

Effect images are selection aids, not visual source material. Never copy their people, places, wording, palette, or exact composition. If a catalog entry says its preview is missing, show that state honestly instead of substituting an unrelated image.

## 3. Three authorities

Every job has three explicit authorities:

- **SOURCE MASTER** — the original high-resolution photograph. It owns identity, anatomy, factual scene geometry, garment/object construction, and authentic material reference.
- **LOOK MASTER** — the user-approved Image 2.5 base result. It owns approved color, lighting, tone, atmosphere, and visual style.
- **DETAIL PATCH** — a localized generated patch. It may add registered mid/high-frequency detail, but it must not redefine SOURCE MASTER identity/structure or LOOK MASTER color/light/tone.

The high-resolution stage is therefore **controlled information recovery on top of an approved look**, not a second global redesign.

## 4. Source and initialization gate

A usable job requires at least one attached photograph or an exact existing image path. A folder, workspace directory, Skill screenshot, or documentation image is not a source photograph.

Resolve the directory containing this `SKILL.md` as `SKILL_ROOT`. Before the first job in an environment run:

```bash
python3 "$SKILL_ROOT/scripts/check_dependencies.py"
```

Stop if Pillow + ImageCms/LittleCMS, NumPy, PyYAML, OpenCV, or SIFT support is missing. Do not silently install packages.

After a source photograph is known, prefer the native Flow tool `open_photo_refiner_flow` (including namespaced MCP variants). Invoke it as a native/top-level tool call, never through `functions.exec`, a shell wrapper, or another orchestration tool. Pass the positive source count and subject-aware recommendation. Make the Flow UI call the final visible action of the turn.

When the Flow UI sends `PHOTO_REFINER_FLOW_GRAPH_SUBMITTED` with a valid `graphPath`, treat that as explicit user confirmation. Do not reopen the canvas or ask the user to confirm again. Initialize directly from the graph:

```bash
python3 "$SKILL_ROOT/scripts/init_job.py" <source...> --graph-file <graphPath>
```

The optional compact Flow settings fallback uses `open_photo_refiner_flow_settings` and sends `PHOTO_REFINER_FLOW_SETTINGS_SUBMITTED` with a `confirmationPath`. That path is also Flow-specific and must live under `~/.codex/photo-refiner-flow/confirmed`.

If Flow UI tools are genuinely unavailable, show a compact text summary and require explicit confirmation before using `--confirmed`. Never fall back to the original Photo Refiner plugin or its state files.

Every job gets its own directory and immutable source hashes. Never overwrite, move, or delete source photographs.

## 5. Subject-aware starting settings

Inspect the source before opening the panel. Use `$SKILL_ROOT/references/subject-routing.md` and `$SKILL_ROOT/references/presets.yaml`.

- There is **no global cinematic preset default**.
- Use the observed subject/light recommendation as the initial preset.
- If the recommendation is uncertain, use `natural-cinematic` as the neutral fallback.
- Use each preset's `default_strength` as the starting strength.
- The 0–100 strength is a UI/audit value only. It does **not** claim linear Image 2.5 control. `build_edit_prompt.py` maps it to `minimal`, `subtle`, `visible`, `strong`, or `transformative` before generation.

Core defaults unless the confirmed panel says otherwise:

```text
workflow: infer single/batch from source count
ui_mode: simple
aspect_ratio: original
framing: preserve
delivery_mode: preview-first
resolution: source-width
detail.mode: adaptive
detail.patch_scope: head-and-face
detail.generation_budget: balanced
detail.soft_generated_patch_budget: 3
detail.hard_generated_patch_ceiling: 6
detail.max_generated_patches: 6
detail.planner: adaptive-value-merge-v2.2
detail.mask_mode: lightweight
batch.consistency: balanced
output_format: jpg
working_color_space: sRGB
creative_recipe: none
```

When aspect ratio changes, require `crop`, `outpaint`, or `contain`; never silently stretch.

Initialize only after confirmation:

```bash
python3 "$SKILL_ROOT/scripts/init_job.py" <source...> --confirmation-file <confirmationPath>
```

or, only for text fallback:

```bash
python3 "$SKILL_ROOT/scripts/init_job.py" <source...> --preset <confirmed-preset> --confirmed
```

If the text fallback confirmed a Starryear creative recipe (Section 2), pass the
confirmed creative options explicitly; never infer them:

```bash
python3 "$SKILL_ROOT/scripts/init_job.py" <source...> --preset <confirmed-preset> \
  --creative-recipe <confirmed-recipe-id> \
  --creative-assembly-mode <direct-effect|original-assembly> \
  --confirmed
```

Every job gets its own directory and immutable source hashes. Never overwrite, move, or delete source photographs.

## 6. Color policy

Photo Refiner Flow uses **sRGB as the internal working and delivery space** because Image 2.5 does not expose an ICC/P3 contract that this Skill can rely on.

Normalize source pixels with:

```bash
python3 "$SKILL_ROOT/scripts/prepare_source.py" <source> <normalized.png>
```

If the source carries an ICC profile, convert the pixels through Pillow ImageCms/LittleCMS to sRGB. Do not merely relabel them. If the profile cannot be converted, stop rather than reinterpret the pixels incorrectly.

After the user approves the Image 2.5 base, that result becomes LOOK MASTER and is the visual color authority. Local detail recovery must preserve its low-frequency color, lighting, tone, and atmosphere.

Do **not** blindly reattach the camera file's original ICC profile to pixels that now contain Image 2.5/OpenCV-generated content. `resize_output.py --icc-source` is legacy compatibility only and does not relabel output pixels.

## 7. Base / LOOK MASTER pass

1. Normalize the source to sRGB and inspect it.
2. Build the deterministic brief from confirmed `job.json`:

```bash
python3 "$SKILL_ROOT/scripts/build_edit_prompt.py" <job.json>
```

3. Use the frozen preset/custom prompt plus explicit invariants. SOURCE MASTER remains authoritative for identity/anatomy/geometry; the selected semantic style level controls how visibly the approved look should change.
4. Generate the Image 2.5 base.
5. For `preview-first`, show the base and stop at `base_generated`. Do not upscale, regenerate local patches, or blend until the user approves it.
6. Record approval:

```bash
python3 "$SKILL_ROOT/scripts/update_job.py" <job.json> --approve-base-preview
```

The approved base is now **LOOK MASTER**.

For batch jobs, the equivalent checkpoint is the approved master frame. Never process the rest of a batch before that approval.

## 8. High-resolution recovery

The generator's bitmap dimensions alone are not evidence of recovered detail. Before every local generation, quantify whether the subject can receive enough effective pixels.

### 8.1 Plan regions

Choose only regions that materially benefit from more local information.

For portraits/classical-costume portraits, default order is:

1. costume/body structure
2. head/hair/ornaments
3. complete face + jaw + chin
4. hands/held objects when important

For landscapes, use terrain boundaries, foliage, water, clouds, atmospheric layers, and architecture only where the final scale justifies them.

The face tile should normally contain full forehead, temples, cheeks, jawline, chin, and a narrow transition-skin margin; the face should occupy about 60–80% of tile height. Never let a face tile be the sole source of hair or costume detail.

### 8.2 Pixel Budget gate

Before generation run:

```bash
python3 "$SKILL_ROOT/scripts/pixel_budget.py" \
  --patch-size <WxH> \
  --source-crop-size <WxH> \
  --source-subject-size <WxH> \
  --final-subject-size <WxH> \
  --region-type <face|hand|head|costume|prop|architecture|background|generic>
```

Default minimum effective detail ratios:

- face `0.85`
- hand `0.75`
- head/hair/ornaments `0.65`
- costume/prop/architecture `0.50`
- background `0.30`
- generic `0.50`

If the budget fails, tighten the crop first. If it is already tight, request a larger patch or reduce the final local scale. Never call a large but low-information bitmap “recovered detail.”

### 8.3 Generate against both authorities

For each accepted region, extract:

- an exact LOOK MASTER target crop for approved color/light/tone/placement;
- a SOURCE MASTER crop when available for identity/anatomy/construction/material truth.

Generate the patch under both constraints. If dual-reference generation causes structural drift, allow one geometry-locked target-only retry. Maximum two generation attempts per tile unless the user explicitly asks for more.

## 8A. Adaptive tile planning and generation budgets

Before local generation, v2.2 plans coarse detail regions with:

```bash
python3 "$SKILL_ROOT/scripts/plan_detail_tiles.py" --image <look-master-or-source> ...
```

When the visual analysis pass has identified the subject and important regions,
pass its result through the formal handoff contract:

```bash
python3 "$SKILL_ROOT/scripts/plan_detail_tiles.py" \
  --image <look-master-or-source> \
  --vision-analysis <vision-analysis.json> \
  --detail-budget balanced
```

The contract is documented in `references/vision-analysis-schema.md`. It accepts
pixel or normalized boxes for the subject, face, hands, and props. The Vision
pass remains responsible for detection; the planner remains responsible for
value scoring, merging, and generation budgets. Manual box flags remain
backward-compatible and override matching Vision fields.

This planner is intentionally conservative. The generation budget is a **ceiling, never a quota**. It scores candidate regions by visual value and final-image scale, prefers one broad region over several fine ones, and may return fewer patches—or zero patches—when local generation is not worth the latency.

Default generated-patch policy:

- `fast` → soft 1 / hard 1
- `balanced` → soft 3 / hard 6
- `max` → soft 5 / hard 8

The **soft budget** is the normal operating envelope. It is not a quota. A complex scene may exceed it only when the remaining regions are still high-value, visually large enough, and able to pass Pixel Budget. The **hard ceiling** prevents runaway generation time.

For portrait/classical-costume work, the preferred coarse ordering remains:

1. costume/body structure
2. head/hair/ornaments
3. complete face
4. hands/held objects only when genuinely large or important

Do not create separate generated patches for eyes, nose, mouth, sleeves, individual ornaments, or small hair subregions unless the user explicitly asks for a more expensive workflow.

## 9. Registration and fusion

Register with:

```bash
python3 "$SKILL_ROOT/scripts/register_blend.py" \
  --base <look-master-canvas> \
  --target <exact-look-master-crop> \
  --patch <generated-patch> \
  --output <new-composite> \
  --x <x> --y <y> \
  --region-type <type>
```

`--model auto` uses:

- face → `similarity`
- head/hair/ornaments → `affine`
- hand → `affine`
- costume/prop/architecture/background/generic → `homography`

Do not upgrade a failed face similarity registration to homography merely to force acceptance. A face that requires perspective warping to match is a structure/identity warning.

Default numeric registration gate: at least 40 inliers, inlier ratio at least `0.75`, median reprojection error ≤3 px, p95 ≤8 px, and warped-patch coverage ≥90%, plus transform plausibility checks.

Passing registration is **not** enough. Perform a separate visual SOURCE MASTER structure/identity review before accepting identity-sensitive regions.

### Lightweight blend masks

v2.2 may build an optional **lightweight geometric blend mask** with:

```bash
python3 "$SKILL_ROOT/scripts/build_blend_mask.py" <patch-or-target> <mask.png> --region-type <type> [--focus-box x,y,w,h]
```

This is **not semantic segmentation**. It creates a coarse, soft-edged geometric face/head/hand/object mask that reduces obvious rectangular seams. It is local OpenCV work only and **never adds Image 2.5 generation calls**.

`register_blend.py` accepts `--blend-mask <mask.png>` and warps the mask together with the patch. If no mask is supplied, the legacy rectangular feather path still applies.

### Multiband frequency fusion

LOOK MASTER remains authoritative for low-frequency appearance and most mid-frequency structure. v2.2 uses three bands:

```text
LOOK MASTER low frequency
+
mostly LOOK MASTER mid frequency + controlled PATCH mid detail
+
registered DETAIL PATCH high frequency
```

Default patch mid-frequency contribution is region-aware and deliberately conservative (face lowest; costume/props higher).

Do not paste a generated patch wholesale over the approved look. Reject visible white-balance changes, relighting, saturation jumps, seams, halos, double features, or local sharpness discontinuities.

Always blend from the clean latest accepted state. Broad tiles first, specific tiles last; face is normally last.

Read `$SKILL_ROOT/references/quality-gates.md` for the full rejection/retry rules.

### Optional landmark identity gate

When a backend/vision pass can provide at least the canonical five facial landmarks for SOURCE MASTER and the candidate patch, run:

```bash
python3 "$SKILL_ROOT/scripts/landmark_identity_gate.py" \
  --source <source-landmarks.json> \
  --candidate <candidate-landmarks.json>
```

The JSON uses named `[x,y]` points (`left_eye`, `right_eye`, `nose_tip`, `mouth_left`, `mouth_right`; optional `chin`, `jaw_left`, `jaw_right`). The script similarity-aligns candidate to SOURCE MASTER and measures normalized residual structure. Do not run a separate detector solely to satisfy this gate if doing so would materially increase latency; it is opportunistic evidence, not a mandatory dependency.

## 10. Identity and factual integrity

Reject regardless of numeric score for changed identity, face shape, feature spacing, gaze/expression, hand anatomy, finger count, garment construction, broken embroidery, shifted props, invented buildings/terrain, doubled contours, or other factual scene drift.

Do not invent missing anatomy or scene content merely to complete a crop. If the source itself cuts off a chin/hand/object, preserve the approved LOOK MASTER and report the limitation.

Face-embedding backends may be added as optional evidence later, but v2.2 does not require a heavyweight identity model. When source/candidate landmarks are available, run `$SKILL_ROOT/scripts/landmark_identity_gate.py` before accepting an identity-sensitive face patch. It similarity-aligns the landmark sets and rejects proportion/structure drift. This gate is supplementary; visual identity review remains required.

## 11. Batch consistency

For batch work, pick one master frame with usable exposure, a sharp important subject, key props, and low occlusion. The user must approve its look before the rest of the batch proceeds.

All frames refer to the same approved master look, frozen prompt version, palette intent, and strength policy. Never chain each result from the previous generated result.

- `strict`: deterministic grading first, minimal generative regions
- `balanced`: shared master look plus adaptive regions (default)
- `creative`: lock identity/core palette while allowing more environmental variation

A shared prompt alone does not guarantee consistency because generation is stochastic.

## 12. Delivery

Use `resize_output.py` only after the accepted composite is complete:

```bash
python3 "$SKILL_ROOT/scripts/resize_output.py" <accepted> <final.jpg> --size <WxH>
```

Aspect-ratio mismatch rejects by default. Use `--fit cover` or `contain` only when confirmed; use `stretch` only on explicit request. Generative outpainting happens before deterministic resize.

Do not describe a resized Image 2.5 base as native high-resolution output. Report remaining non-native-upscaling areas honestly.

Final report should include:

- final path, dimensions, format, and size
- selected preset/custom prompt and semantic style level
- whether LOOK MASTER was explicitly approved
- detail regions accepted/rejected
- Pixel Budget ratios
- registration model/metrics and retries
- any identity, anatomy, texture, seam, or non-native-upscaling limitations

## 13. State discipline

Use `update_job.py` for accepted state transitions:

```text
initialized → prepared → base_generated → details_processed → completed
```

A `base-only` job may go directly from `base_generated` to `completed` after its required approval. Record `failed` only for a terminal failure, not for an optional tile rejection when the clean LOOK MASTER remains deliverable.

Keep generated artifacts inside the job directory. Do not scatter intermediates into the user's photo folders.
