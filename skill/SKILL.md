---
name: photo-refiner
description: Refine photographs with an approved Image 2.5 look, high-resolution local detail recovery, registration, frequency-aware blending, and deterministic delivery sizing while preserving source identity and scene truth.
---

# Photo Refiner v2.2

Photo Refiner is a **photographic refinement workflow**, not a generic image-redesign skill. Image 2.5 establishes the approved visual look; deterministic scripts and localized generation recover useful detail without pretending that a low-resolution generation is native high resolution.

Version 2.2 keeps the v2.1 SOURCE / LOOK / DETAIL authority model, but adds three execution rules: **adaptive tile planning**, **generation budgets**, and **lightweight blend masks**. The goal is to improve local recovery without exploding the number of generated patches.

## 1. Intent gate

A question about this Skill is **not** an edit request. If the user asks whether it can edit, how it works, how to optimize it, what its limits are, or asks to inspect/review the Skill, answer or inspect only. **Do not invoke image generation.**

Start a refinement job only when the user explicitly asks to edit/refine a **specific source photograph**. Even then, do not generate until the initialization settings have been shown and explicitly confirmed.

## 2. Three authorities

Every job has three explicit authorities:

- **SOURCE MASTER** — the original high-resolution photograph. It owns identity, anatomy, factual scene geometry, garment/object construction, and authentic material reference.
- **LOOK MASTER** — the user-approved Image 2.5 base result. It owns approved color, lighting, tone, atmosphere, and visual style.
- **DETAIL PATCH** — a localized generated patch. It may add registered mid/high-frequency detail, but it must not redefine SOURCE MASTER identity/structure or LOOK MASTER color/light/tone.

The high-resolution stage is therefore **controlled information recovery on top of an approved look**, not a second global redesign.

## 3. Source and initialization gate

A usable job requires at least one attached photograph or an exact existing image path. A folder, workspace directory, Skill screenshot, or documentation image is not a source photograph.

The commands in this document are relative to the directory that contains this
`SKILL.md`, not to the user's photo or workspace directory. Resolve that
directory as `SKILL_ROOT` before running any command. Use
`$SKILL_ROOT/scripts/...` and `$SKILL_ROOT/references/...` below; do not run
bare `scripts/...` paths from an unrelated working directory.

Before the first job in an environment run:

```bash
python3 "$SKILL_ROOT/scripts/check_dependencies.py"
```

Stop if Pillow + ImageCms/LittleCMS, NumPy, PyYAML, OpenCV, or SIFT support is missing. Do not silently install packages.

After a source photograph is known, look for `open_photo_refiner_settings` (including namespaced MCP variants). If available, opening the Photo Refiner Studio panel is mandatory. Pass a positive source count plus the subject-aware recommendation. Do not print a parallel text menu. Resume only after the user submits the panel and a `confirmationPath` is returned. Never call the submit tool on the user's behalf.

If the Studio tool is genuinely unavailable, use a compact text fallback and require explicit confirmation before calling `init_job.py --confirmed`. Never infer panel unavailability merely because it was not auto-suggested.

## 4. Subject-aware starting settings

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

Every job gets its own directory and immutable source hashes. Never overwrite, move, or delete source photographs.

## 5. Color policy

Photo Refiner v2.2 uses **sRGB as the internal working and delivery space** because Image 2.5 does not expose an ICC/P3 contract that this Skill can rely on.

Normalize source pixels with:

```bash
python3 "$SKILL_ROOT/scripts/prepare_source.py" <source> <normalized.png>
```

If the source carries an ICC profile, convert the pixels through Pillow ImageCms/LittleCMS to sRGB. Do not merely relabel them. If the profile cannot be converted, stop rather than reinterpret the pixels incorrectly.

After the user approves the Image 2.5 base, that result becomes LOOK MASTER and is the visual color authority. Local detail recovery must preserve its low-frequency color, lighting, tone, and atmosphere.

Do **not** blindly reattach the camera file's original ICC profile to pixels that now contain Image 2.5/OpenCV-generated content. `resize_output.py --icc-source` is legacy compatibility only and does not relabel output pixels.

## 6. Base / LOOK MASTER pass

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

## 7. High-resolution recovery

The generator's bitmap dimensions alone are not evidence of recovered detail. Before every local generation, quantify whether the subject can receive enough effective pixels.

### 7.1 Plan regions

Choose only regions that materially benefit from more local information.

For portraits/classical-costume portraits, default order is:

1. costume/body structure
2. head/hair/ornaments
3. complete face + jaw + chin
4. hands/held objects when important

For landscapes, use terrain boundaries, foliage, water, clouds, atmospheric layers, and architecture only where the final scale justifies them.

The face tile should normally contain full forehead, temples, cheeks, jawline, chin, and a narrow transition-skin margin; the face should occupy about 60–80% of tile height. Never let a face tile be the sole source of hair or costume detail.

### 7.2 Pixel Budget gate

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

### 7.3 Generate against both authorities

For each accepted region, extract:

- an exact LOOK MASTER target crop for approved color/light/tone/placement;
- a SOURCE MASTER crop when available for identity/anatomy/construction/material truth.

Generate the patch under both constraints. If dual-reference generation causes structural drift, allow one geometry-locked target-only retry. Maximum two generation attempts per tile unless the user explicitly asks for more.

## 7A. Adaptive tile planning and generation budgets

Before local generation, v2.2 plans coarse detail regions with:

```bash
python3 "$SKILL_ROOT/scripts/plan_detail_tiles.py" --image <look-master-or-source> ...
```

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

## 8. Registration and fusion

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

## 9. Identity and factual integrity

Reject regardless of numeric score for changed identity, face shape, feature spacing, gaze/expression, hand anatomy, finger count, garment construction, broken embroidery, shifted props, invented buildings/terrain, doubled contours, or other factual scene drift.

Do not invent missing anatomy or scene content merely to complete a crop. If the source itself cuts off a chin/hand/object, preserve the approved LOOK MASTER and report the limitation.

Face-embedding backends may be added as optional evidence later, but v2.2 does not require a heavyweight identity model. When source/candidate landmarks are available, run `$SKILL_ROOT/scripts/landmark_identity_gate.py` before accepting an identity-sensitive face patch. It similarity-aligns the landmark sets and rejects proportion/structure drift. This gate is supplementary; visual identity review remains required.

## 10. Batch consistency

For batch work, pick one master frame with usable exposure, a sharp important subject, key props, and low occlusion. The user must approve its look before the rest of the batch proceeds.

All frames refer to the same approved master look, frozen prompt version, palette intent, and strength policy. Never chain each result from the previous generated result.

- `strict`: deterministic grading first, minimal generative regions
- `balanced`: shared master look plus adaptive regions (default)
- `creative`: lock identity/core palette while allowing more environmental variation

A shared prompt alone does not guarantee consistency because generation is stochastic.

## 11. Delivery

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

## 12. State discipline

Use `update_job.py` for accepted state transitions:

```text
initialized → prepared → base_generated → details_processed → completed
```

A `base-only` job may go directly from `base_generated` to `completed` after its required approval. Record `failed` only for a terminal failure, not for an optional tile rejection when the clean LOOK MASTER remains deliverable.

Keep generated artifacts inside the job directory. Do not scatter intermediates into the user's photo folders.
