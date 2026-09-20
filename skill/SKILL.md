---
name: photo-refiner
description: Refine photographs with an approved Image 2.5 look and high-resolution detail recovery, or run an explicitly selected bundled Starryear source-faithful creative translation recipe with effect-image selection and deterministic assembly.
---

# Photo Refiner v2.4

Photo Refiner is a **photographic refinement workflow**, not a generic image-redesign skill. Image 2.5 establishes the approved visual look; deterministic scripts and localized generation recover useful detail without pretending that a low-resolution generation is native high resolution.

Version 2.4 keeps the SOURCE / LOOK / DETAIL refinement model and makes high-resolution recovery the normal final stage for both ordinary refinement and eligible creative translation. Single-source `direct-effect` creative work uses a creative-safe adaptive recovery profile; `original-assembly` and multi-source creative layouts remain excluded from ordinary patching because region ownership is not yet safe.

## 1. Intent gate

A question about this Skill is **not** an edit request. If the user asks whether it can edit, how it works, how to optimize it, what its limits are, or asks to inspect/review the Skill, answer or inspect only. **Do not invoke image generation.**

Start a refinement job only when the user explicitly asks to edit/refine a **specific source photograph**. Even then, do not generate until the initialization settings have been shown and explicitly confirmed.

## 2. Creative translation gate

Normal Photo Refiner work and creative translation are separate execution modes:

- `photo-refinement` uses SOURCE MASTER / LOOK MASTER / DETAIL PATCH as described below.
- `creative-translation` is an optional second stage after the user has chosen the normal style preset. It uses a selected Starryear recipe with either a complete direct effect image (the default) or the original evidence/panel assembly. It runs only when the user selects a creative recipe in Studio or explicitly confirms one through the text fallback.

Never flatten a bundled creative recipe into a color preset or append its name to the normal refinement prompt. The selected normal preset remains the frozen upstream visual direction; apply it deliberately alongside the recipe-specific translation instructions, rather than replacing it or treating the result as a simple filter. When creative translation is selected:

1. Read [references/starryear/catalog.md](references/starryear/catalog.md) and [references/starryear/catalog.json](references/starryear/catalog.json).
2. Validate the actual source count against the selected catalog entry.
3. Read the selected `recipePath/SKILL.md` completely, then read every prompt, reference, and script that recipe requires.
4. Resolve `creative_assembly_mode` from the confirmed settings. It defaults to `direct-effect`; `original-assembly` is an explicit alternative. Direct-effect generates one complete creative effect image using the frozen normal preset as its upstream visual direction plus the recipe's theme, prompt semantics, references, source-derived motifs, and visual grammar; it must not attach an unchanged source-evidence strip, place the original beside/below the artwork, crop an original assembly, or act as a simple filter. Original-assembly follows the recipe literally: preserve its evidence regions with actual source pixels, generate only its translated regions, and use its compositor. For single-source direct-effect jobs the creative canvas follows the confirmed panel aspect ratio (`original` means the source photograph's own ratio) instead of the recipe's documented output ratio; original-assembly and multi-photo recipes keep the recipe's documented output structure. `creative_output.aspect_ratio_source` / `effective_aspect_ratio` in `job.json` record the resolved choice. When `creative_output.upstream_binding` is `look-master` (`--creative-from-base`, offered conversationally: for a single-source direct-effect creative job in preview-first mode, ask once whether to 直接开始创意 or 先按预设出主图、确认后再创意), first run the Section 7 base pass with the frozen preset, show that main image, and continue only after explicit approval; the creative pass then anchors identity and motifs to the original source photograph and uses the approved main image only as its look reference, and the formal base-preview gate still applies to the creative artwork itself. When `creative_output.upstream_binding` is `hd-master` (the panel's 高清创意链 toggle or `--creative-hd-chain`), run the full ordinary refinement first — Section 7 base pass, then Section 8/8A high-resolution recovery — so `details_processed` marks the approved high-definition master; then generate the creative draft on that master (identity, structure and micro-detail reference come from the HD master, grammar from the recipe), record `creative_generated`, and require `--approve-creative-preview` before the style-faithful redraw pass into `completed`.
5. Default to preview-first. Present the generated direct effect preview or assembled original preview and stop for approval when the confirmed delivery mode is `preview-first`; one-click may continue without that pause.
6. Retry only failed generated regions. For direct-effect, retry the complete creative image; for original-assembly, retry only failed generated regions.
7. When `creative_output.upscale.enabled` (the panel's 4X-UltraSharp toggle), first run `scripts/upscale_image.py --input <approved preview> --output <upscaled working canvas> --scale 4` — the bundled 4X-UltraSharp engine sharpens the non-patch areas of the approved creative image, patch planning then runs on the upscaled canvas, and the delivery resize keeps that sharpness. Without an installed engine the script records an honest Lanczos fallback (`upscale_image.py --install-engine` installs the self-contained engine; no ComfyUI needed). Every patch must be generated at its target region aspect — `register_blend.py` rejects patches whose aspect deviates more than 5% from the target region instead of recropping the target to match the generator output. For a **single-source `direct-effect`** result, the approved creative image becomes **CREATIVE LOOK MASTER** and must continue through the creative-safe adaptive high-resolution recovery in Section 8/8A before final delivery. Do not run the ordinary recovery profile over it. For `original-assembly` or multi-source creative layouts, keep local recovery disabled because ordinary patches can cross evidence/generated/layout boundaries and overwrite the translated art. For `hd-master` chains the order inverts: `details_processed` marks the ordinary high-resolution recovery of the approved main image (a photograph, so the ordinary profile applies); after the creative draft is approved, finish with the style-faithful tiled redraw — tile the approved HD master (~2048² tiles, ≥15% overlap), re-render each tile under the recipe grammar with the HD-master crop as structure reference and the matching creative-draft region as style reference, gate each tile on composition registration (median error ≤3 px against the draft region, one retry), and blend overlaps with the multiband model. The creative artwork itself still never receives ordinary photographic patches.

Effect images are selection aids, not visual source material. Never copy their people, places, wording, palette, or exact composition. If a catalog entry says its preview is missing, show that state honestly instead of substituting an unrelated image.

## 3. Three authorities

Ordinary refinement has three explicit authorities:

- **SOURCE MASTER** — the original high-resolution photograph. It owns identity, anatomy, factual scene geometry, garment/object construction, and authentic material reference.
- **LOOK MASTER** — the user-approved Image 2.5 base result. It owns approved color, lighting, tone, atmosphere, and visual style.
- **DETAIL PATCH** — a localized generated patch. It may add registered mid/high-frequency detail, but it must not redefine SOURCE MASTER identity/structure or LOOK MASTER color/light/tone.

Eligible single-source `direct-effect` creative work uses the same separation with a different visual authority:

- **SOURCE MASTER** still owns identity, anatomy, factual geometry and construction.
- **CREATIVE LOOK MASTER** is the approved complete creative result. It owns color, lighting, tone, materials, visual grammar and all approved creative transformations.
- **CREATIVE DETAIL PATCH** may recover registered mid/high-frequency detail only. It must not turn the creative region back into an ordinary photograph or invent a new style.

The high-resolution stage is therefore **controlled information recovery on top of the approved ordinary or creative look**, not a second global redesign.

## 4. Source and initialization gate

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

After a source photograph is known, look for `open_photo_refiner_settings` (including namespaced MCP variants). If available, opening the Photo Refiner Studio panel is mandatory. **Invoke the namespaced MCP tool as a native/top-level tool call, never through `functions.exec`, a shell wrapper, or another orchestration tool.** Pass a positive source count plus the subject-aware recommendation. **Make this panel call the final visible action of the turn: do not append a text acknowledgement, settings summary, or any other message after it.** The host needs the Widget metadata to mount the panel. Do not print a parallel text menu. Resume only after the user submits the panel and a `confirmationPath` is returned. Never call the submit tool on the user's behalf.

The panel has two separate states: editing fields only changes the Widget locally; clicking its confirmation button is the actual submission. When the Widget sends a `PHOTO_REFINER_PANEL_SUBMITTED` handoff containing a valid `confirmationPath`, treat that as explicit user confirmation. Do not ask “是否确认”, reopen the panel, or request the same settings again. Use that exact file with `init_job.py --confirmation-file` and continue the selected workflow. If no `confirmationPath` exists, the settings are not confirmed yet.

If the Studio tool is genuinely unavailable, use a compact text fallback and require explicit confirmation before calling `init_job.py --confirmed`. Never infer panel unavailability merely because it was not auto-suggested.

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

Photo Refiner v2.2 uses **sRGB as the internal working and delivery space** because Image 2.5 does not expose an ICC/P3 contract that this Skill can rely on.

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

For ordinary refinement, extract for each accepted region:

- an exact LOOK MASTER target crop for approved color/light/tone/placement;
- a SOURCE MASTER crop when available for identity/anatomy/construction/material truth.

For eligible single-source `direct-effect` creative recovery, use the approved **CREATIVE LOOK MASTER** crop as the appearance target and SOURCE MASTER only as the structural/identity reference. The patch instruction must preserve the current creative style, materials, lighting and transformation while increasing effective detail. Never ask the patch to "restore the original photographic look."

Generate the patch under both constraints. If dual-reference generation causes structural drift, allow one geometry-locked target-only retry. Maximum two generation attempts per tile unless the user explicitly asks for more.

### 8.4 Record actual client-returned patch dimensions

The ChatGPT client image-generation path is the runtime authority for patch output dimensions. Do **not** treat API documentation, planner recommendations, or requested dimensions as proof of the returned bitmap size.

After **every generated local DETAIL PATCH / CREATIVE DETAIL PATCH**:

1. Materialize the returned image inside the current job directory, normally under `intermediates/patches/`.
2. Record the exact size that was requested from the client generation call.
3. Run:

```bash
python3 "$SKILL_ROOT/scripts/record_patch_observation.py" <job.json> \
  --patch <generated-patch-file> \
  --region-type <face|hand|head|costume|prop|architecture|background|generic> \
  --region-role <planner-region-role> \
  --requested-size <WxH> \
  --source-crop-size <WxH> \
  --final-region-size <WxH> \
  --planner-region-index <zero-based-index> \
  --attempt <generation-attempt>
```

`record_patch_observation.py` opens the generated file itself with Pillow and writes the measured dimensions to `job.json.patch_observations[]`. The record includes requested size, actual size, file bytes/hash, region identity, normal-vs-creative detail mode, and requested-to-returned scale ratios.

Rules:

- `requested_size` must be the dimensions actually sent to the client generation path, not merely `recommended_patch_size`.
- `actual_size` must come from the returned image file. Never fill it from memory, documentation, API limits, or assumptions.
- Record failed/retried generations as separate observations only when an image file was actually returned; increment `--attempt`.
- A requested/actual mismatch is observational evidence, not an automatic failure. Pixel Budget and visual quality gates decide whether the patch remains useful.
- `original-assembly` and other jobs with `detail.mode = not-applicable` must not record local recovery patches.

After several local tests, summarize observed client behavior without claiming a platform limit:

```bash
python3 "$SKILL_ROOT/scripts/summarize_patch_observations.py" <job.json-or-jobs-directory> [...]
```

The summary reports requested→actual mappings, actual sizes grouped by normal/creative detail mode, and the largest **observed** width, height, and total pixel count. These are empirical observations from this runtime only.

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

# eligible single-source direct-effect creative work:
python3 "$SKILL_ROOT/scripts/plan_detail_tiles.py" \
  --image <approved-creative-look-master> \
  --vision-analysis <vision-analysis.json> \
  --detail-budget balanced \
  --recovery-profile creative-safe
```

The contract is documented in `references/vision-analysis-schema.md`. It accepts pixel or normalized boxes for the subject, face, hands, and props, plus optional `portrait_extent` and `detail_complexity` hints. The planner infers portrait extent from face-to-subject scale when the hint is omitted. The Vision pass remains responsible for detection; the planner remains responsible for value scoring, merging, and generation budgets. Manual box flags remain backward-compatible and override matching Vision fields.

This planner is intentionally conservative. The generation budget is a **ceiling, never a quota**. It scores candidate regions by visual value and final-image scale, prefers one broad region over several fine ones, and may return fewer patches—or zero patches—when local generation is not worth the latency.

Ordinary generated-patch policy:

- `fast` → soft 1 / hard 1
- `balanced` → soft 3 / hard 6
- `max` → soft 5 / hard 8

Creative-safe adaptive portrait policy under the normal `balanced` setting:

- close / half-body → soft 2 / hard 3
- full-body → soft 3 / hard 4
- complex full-body → soft 4 / hard 5
- non-portrait creative scenes → soft 2 / hard 3

The creative-safe planner uses broad regions only. Full-body portraits may split costume recovery into **upper-costume** and **lower-costume** coverage so long skirts, robes, trousers or lower-body texture are not silently omitted. Hands and important props are added only when they remain high-value and pass Pixel Budget. The absolute creative-safe hard ceiling is 5 generated patches.

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

LOOK MASTER remains authoritative for low-frequency appearance and most mid-frequency structure in ordinary refinement. For creative-safe recovery, **CREATIVE LOOK MASTER** takes the same role. The fusion model uses three bands:

```text
LOOK/CREATIVE LOOK MASTER low frequency
+
mostly LOOK/CREATIVE LOOK MASTER mid frequency + controlled PATCH mid detail
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

`hd-master` creative chains insert `creative_generated` between `details_processed` and `completed`, gated by `--approve-creative-preview` after the user approves the creative draft; skipping it, or jumping `details_processed` → `completed`, is rejected by `update_job.py`.
```

A `base-only` job may go directly from `base_generated` to `completed` after its required approval. Record `failed` only for a terminal failure, not for an optional tile rejection when the clean LOOK MASTER remains deliverable.

Keep generated artifacts inside the job directory. Do not scatter intermediates into the user's photo folders.
