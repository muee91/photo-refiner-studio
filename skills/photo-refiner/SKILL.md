---
name: photo-refiner
description: Refine source photographs in ChatGPT with review-first look generation, honest high-resolution recovery, optional depth guards, and auditable patch/tile delivery. Use the companion photo-refiner-creative skill only after a creative recipe is explicitly selected.
---

# Photo Refiner v2.4

Photo Refiner is the orchestration skill for one installed **Photo Refiner Studio** plugin. ChatGPT Images owns image generation/editing. This skill owns photographic authority, review checkpoints, high-resolution honesty, patch economics, deterministic registration/blending, and delivery evidence.

Do not call an image-generation API merely to duplicate ChatGPT's built-in image generator.

## 1. Intent gate

A question about Photo Refiner, its architecture, settings, limits, or source code is not an edit request. Inspect or explain only.

Start a job only when the user explicitly asks to edit/refine one or more specific source photographs. A folder, screenshot of the UI, or documentation image is not a source photograph.

## 2. Product surface and Studio gate

Photo Refiner is one plugin across Chat, Work, Voice, and Codex. The surface does not change the image authority model.

When a usable source photograph is present, prefer the plugin tool `open_photo_refiner_settings` (including namespaced variants). Pass the real source count plus subject-aware recommendations from `references/subject-routing.md` and `references/presets.yaml`.

Opening Studio is the final visible action of that turn. Do not print a parallel settings menu or auto-submit on the user's behalf.

After the user submits Studio, use the returned `confirmationPath` exactly:

```bash
python3 "$SKILL_ROOT/scripts/init_job.py" <source...> --confirmation-file <confirmationPath>
```

Current confirmations are schema 4 and freeze `config + executionMode + resolvedCreativeRecipe + creativeOutput + resolvedPrompt` with `confirmationHash`. `init_job.py` rejects modified or downgraded confirmations.

If the MCP tool is genuinely unavailable, use a compact text fallback, require explicit confirmation, then initialize with `--confirmed`.

## 3. Creative handoff

Normal refinement is owned by this skill. Creative translation is owned by the companion **`photo-refiner-creative`** skill.

When Studio confirms `creativeRecipe != none`:

1. initialize the job normally so the confirmation and job ledger are frozen;
2. load `photo-refiner-creative` and follow that skill for recipe interpretation, direct-effect/original-assembly behavior, creative preview checkpoints, and creative authority;
3. return to this skill's HD/evidence pipeline only where the creative skill explicitly says the output is eligible.

`references/starryear/catalog.json` remains in this skill only because deterministic job scripts validate recipe IDs and source-count contracts. Full recipe resources live in the companion creative skill.

## 4. Authorities

Ordinary refinement has three authorities:

- **SOURCE MASTER** — original high-resolution photograph. Owns identity, anatomy, factual geometry, garment/object construction, and authentic material reference.
- **LOOK MASTER** — approved ChatGPT Images base result. Owns color, lighting, tone, atmosphere, and approved visual style.
- **DETAIL PATCH** — localized generated detail. May add registered mid/high-frequency information but may not redefine SOURCE MASTER structure or LOOK MASTER low-frequency appearance.

Never use a failed generated image as the next source. Regenerate from the clean authority state.

## 5. Color contract

Use sRGB as the internal working and delivery space unless the active ChatGPT image pipeline exposes a reliable color-profile contract.

Normalize source pixels with:

```bash
python3 "$SKILL_ROOT/scripts/prepare_source.py" <source> <normalized.png>
```

If an embedded ICC profile can be converted through ImageCms/LittleCMS, convert the pixels. Do not merely relabel them. Never blindly attach the camera profile to generated pixels.

## 6. Base / LOOK MASTER pass

Before generation, build the frozen brief:

```bash
python3 "$SKILL_ROOT/scripts/build_edit_prompt.py" <job.json>
```

Generate the full base edit with ChatGPT Images. SOURCE MASTER remains authoritative for identity/geometry; the confirmed prompt/preset controls the look.

For `preview-first`, stop after base generation and review four things before approval:

- identity: face shape, feature spacing, gaze, expression;
- anatomy/structure: fingers, chin, hair ornaments, garment joins, props, architecture;
- patch readiness: no duplicated features, drift, rectangular seams, halos, or abrupt local sharpness/color changes;
- overall look: lighting, palette, framing, atmosphere, and source-derived geometry are coherent.

If the base fails, regenerate the base. Do not repair a failed global result with local patches.

Record approval with the exact bitmap the user saw:

```bash
python3 "$SKILL_ROOT/scripts/update_job.py" <job.json> \
  --approve-base-preview \
  --artifact base_preview=<approved-image>
```

The approved image is now LOOK MASTER.

## 7. Honest HD working canvas

Every current-version ordinary job and every eligible creative-safe job must enter high-resolution recovery through:

```bash
python3 "$SKILL_ROOT/scripts/prepare_hd_working_canvas.py" <job.json> \
  --input <exact-look-master> \
  --output <job-dir>/intermediates/hd-working.png
```

The router chooses one route:

- `native-detail` — current pixels already support delivery within the honest interpolation tail;
- `ultrasharp-detail` — the pinned 4X-UltraSharp engine can honestly raise the working canvas inside its native information span;
- `full-canvas-tile-redraw` — delivery exceeds the model-native information span or no information-adding upscaler is available.

A larger file is not proof of recovered information. `upscale_image.py` records `information_to`; any extra `interpolated_tail` does not raise delivery geometry.

For `source-width`, resolve delivery dimensions from the real source photograph. For custom framing, preserve the approved aspect ratio; never stretch.

## 8. Optional relative depth prior

Depth is a hidden spatial guard, not scene truth and never a reason to add generations by itself.

Read `references/depth-prior.md` and use depth only when it materially helps with:

- foreground occlusion;
- hand/prop front-back ordering;
- requested depth-of-field/background blur;
- haze/atmospheric perspective;
- overlapping subjects;
- creative spatial reconstruction.

Default source is coarse `vision-relative` depth from the active multimodal model. Do not invent metric distance.

After normal detail planning, annotate the plan without changing crop count or Pixel Budget:

```bash
python3 "$SKILL_ROOT/scripts/apply_depth_prior.py" \
  --plan <detail-plan.json> \
  --vision-analysis <vision-analysis.json> \
  --output <detail-plan.depth.json>
```

Use the annotated plan consistently for observation and blending so its SHA remains stable.

SOURCE MASTER always wins when depth and visible evidence disagree.

## 9. Detail planning and empirical client cap

Do not treat API limits, planner recommendations, or remembered ChatGPT limits as the client's actual patch size.

Use an observed client-returned bitmap size from prior `patch_observations`. If the current runtime has no observation, do one disposable calibration generation at the intended aspect, materialize the returned image, and record it **without** `--plan`. The calibration image is observation-only and must never be blended.

Plan local recovery:

```bash
python3 "$SKILL_ROOT/scripts/plan_detail_tiles.py" \
  --image <hd-working.png> \
  --vision-analysis <vision-analysis.json> \
  --delivery-canvas <WxH> \
  --observed-patch-size <actual-WxH> \
  --detail-budget <fast|balanced|max> \
  --output <detail-plan.json>
```

Planning rules:

- generation budgets are ceilings, not quotas;
- prefer broad valuable regions to micro-patches;
- balanced ordinary work normally stays at 0–3 generations and may overflow only when value/Pixel Budget justifies it;
- face/head/hands/costume/props retain their own Pixel Budget thresholds;
- depth may prevent unsafe merging but may not increase the quota by itself.

If the HD router chose `full-canvas-tile-redraw`, first build the subject-aware detail plan, then combine it with complete coverage:

```bash
python3 "$SKILL_ROOT/scripts/plan_tile_redraw.py" \
  --image <hd-working.png> \
  --observed-patch-size <actual-WxH> \
  --detail-plan <detail-plan.json> \
  --full-canvas --sliver-margin 0 \
  --output <tile-plan.json>
```

No part of a full-canvas fallback may be delegated back to an interpolated scaffold.

## 10. Generate, observe, register, blend

For every planned patch/tile:

1. crop the exact planned target;
2. generate with ChatGPT Images using SOURCE MASTER for identity/structure and LOOK MASTER for appearance;
3. materialize the returned bitmap inside the job directory;
4. record the actual file, dimensions, hash, plan SHA, region/tile index, and Pixel Budget;
5. register and blend from the latest clean accepted composite.

Detail observation:

```bash
python3 "$SKILL_ROOT/scripts/record_patch_observation.py" <job.json> \
  --patch <returned.png> \
  --region-type <type> \
  --requested-size <WxH> \
  --plan <detail-plan.json> \
  --planner-region-index <index>
```

Audited blend:

```bash
python3 "$SKILL_ROOT/scripts/register_blend.py" \
  --base <current-composite> \
  --target <exact-target-crop> \
  --patch <returned.png> \
  --output <next-composite> \
  --x <x> --y <y> \
  --region-type <type> \
  --job <job.json> \
  --plan <detail-plan.json> \
  --planner-region-index <index>
```

For tile redraw, replace `--plan/--planner-region-index` with `--tile-plan/--tile-index`.

`register_blend.py` writes hash-chain receipts: input base -> patch -> output composite. Broad structure goes first; face is normally last.

Read `references/quality-gates.md` for registration, identity, structure, seam, landmark, and retry gates. Passing registration alone never proves the patch is valid.

## 11. Delivery gate

Before `completed`, run the delivery gate against the exact master and final file:

```bash
python3 "$SKILL_ROOT/scripts/delivery_gate.py" <job.json> \
  --master <accepted-composite> \
  --final <delivered-file> \
  --plan <detail-plan.json>
```

For a tiled route use `--tile-plan <tile-plan.json>`.

Delivery is fail-closed. It verifies, as applicable:

- the original generated/approved canvas is bound by path/size/hash;
- geometry is supported by real information or a complete full-canvas redraw;
- plan canvas equals delivered canvas;
- every planned patch/tile has live actual-return evidence;
- every accepted patch still exists with the same hash/size;
- blend receipts form an ordered hash chain;
- the final receipt hash equals the delivery master;
- quality/review checkpoints required by the current job are complete.

A feasible plan is not execution evidence. A requested resolution is not returned resolution.

## 12. State and retry discipline

`job.json` is the execution ledger. Preserve immutable source hashes and explicit review checkpoints.

Typical ordinary flow:

```text
initialized
-> prepared
-> base_generated
-> details_processed
-> completed
```

Preview-first requires approval of the exact base bitmap before detail work. Retry only the failed generation from the last clean authority state. Do not continue from rejected composites.

Batch jobs must establish and approve one master look before applying consistency to the remainder.

## 13. Platform rules

- Chat, Work, Voice, and Codex are surfaces, not separate pipelines.
- Use Work for long multi-file/batch jobs or browser/reference gathering; do not replace the deterministic local evidence pipeline with browser automation.
- Voice may control the same semantic actions (approve, redo, change look, retry region) but is not a separate voice stack.
- MCP/Studio is for structured settings, confirmation, catalogs, and UI. Deterministic photo processing remains in skill scripts where local files are available.
- Prefer fewer broader edits and stronger review gates as ChatGPT Images improves.

## 14. Anti-duplication rules

Do not build a second image-generation service, browser, voice system, scheduler, or selection editor merely because ChatGPT already provides those capabilities.

Photo Refiner specializes in what the platform does not guarantee automatically: photographic authority, high-resolution honesty, spatial safety, patch economics, reproducible evidence, and review/retry discipline.
