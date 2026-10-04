---
name: photo-refiner
description: Refine source photographs in ChatGPT with review-first look generation, source-backed original-resolution delivery, optional depth guards, and auditable local recovery. Use the companion photo-refiner-creative skill only after a creative recipe is explicitly selected.
---

# Photo Refiner v2.4

Photo Refiner is the orchestration skill for one installed **Photo Refiner Studio** plugin. ChatGPT Images owns image generation/editing. This skill owns photographic authority, review checkpoints, high-resolution delivery, patch economics, deterministic registration/blending, and delivery evidence.

Do not call an image-generation API merely to duplicate ChatGPT's built-in image generator.

## 1. Intent gate

A question about Photo Refiner, its architecture, settings, limits, or source code is not an edit request. Inspect or explain only.

Start a job only when the user explicitly asks to edit/refine one or more specific source photographs.

## 2. Studio gate

When a usable source photograph is present, prefer the plugin tool `open_photo_refiner_settings` and pass the real source count plus subject-aware recommendations from `references/subject-routing.md` and `references/presets.yaml`.

Opening Studio is the final visible action of that turn. Do not print a parallel settings menu or auto-submit.

After Studio submits, initialize with the exact confirmation:

```bash
python3 "$SKILL_ROOT/scripts/init_job.py" <source...> --confirmation-file <confirmationPath>
```

Current confirmations are schema 4 and bind settings, execution mode, recipe/output routing, and resolved prompt with `confirmationHash`.

## 3. Creative handoff

Normal photographic refinement is owned by this skill. Creative translation is owned by **`photo-refiner-creative`**.

When Studio confirms `creativeRecipe != none`, initialize the job, then explicitly load the creative companion. Return to this skill's HD/evidence pipeline only where that skill says the creative output is eligible.

## 4. Image authorities

Ordinary refinement has three authorities:

- **SOURCE MASTER** — original high-resolution photograph. Owns identity, anatomy, factual geometry, garment/object construction, authentic texture, and source-resolution high-frequency detail.
- **LOOK MASTER** — approved ChatGPT Images result. Owns color, lighting, tone, atmosphere, retouch character, and approved visual style.
- **DETAIL PATCH** — localized generated detail. May add registered mid/high-frequency information where useful but may not redefine SOURCE MASTER structure or LOOK MASTER low-frequency appearance.

This distinction is critical: a smaller LOOK MASTER does **not** erase the high-resolution information already present in SOURCE MASTER.

Never continue from a rejected generated image.

## 5. Color contract

Use sRGB internally unless the active ChatGPT image pipeline exposes a reliable profile contract.

```bash
python3 "$SKILL_ROOT/scripts/prepare_source.py" <source> <normalized.png>
```

Convert embedded profiles through ImageCms/LittleCMS when possible; never merely relabel pixels.

## 6. Base / LOOK MASTER checkpoint

Build the frozen edit brief:

```bash
python3 "$SKILL_ROOT/scripts/build_edit_prompt.py" <job.json>
```

Generate the complete base edit with ChatGPT Images. SOURCE MASTER remains authoritative for identity/geometry; the confirmed settings control appearance.

For `preview-first`, review before approval:

- identity and expression;
- anatomy, garment joins, props, architecture;
- duplicated/drifted features, seams, halos, abrupt sharpness changes;
- overall lighting, palette, framing and atmosphere.

If the global result fails, regenerate globally. Do not patch a globally failed LOOK MASTER.

Record the exact approved bitmap:

```bash
python3 "$SKILL_ROOT/scripts/update_job.py" <job.json> \
  --approve-base-preview \
  --artifact base_preview=<approved-image>
```

## 7. HD working canvas: photographic delivery is source-backed

Every eligible job enters HD preparation through:

```bash
python3 "$SKILL_ROOT/scripts/prepare_hd_working_canvas.py" <job.json> \
  --input <exact-look-master> \
  --output <job-dir>/intermediates/hd-working.png
```

The router has four routes:

- **`native-detail`** — LOOK MASTER already supports the delivery canvas.
- **`source-backed-detail`** — default for **ordinary, single-source, original-framing, `source-width` photography**. SOURCE MASTER supplies real source-resolution fine luminance detail while LOOK MASTER supplies approved low/mid-frequency appearance. Only valuable local regions are regenerated afterwards.
- **`ultrasharp-detail`** — for canvases that cannot use SOURCE MASTER detail but fit the pinned 4X-UltraSharp information span.
- **`full-canvas-tile-redraw`** — for genuinely synthetic/transformed canvases that cannot be backed by SOURCE MASTER and exceed the honest information span.

### Product rule: original resolution is not an optional expensive mode

If Studio already confirmed `resolution = source-width` for an ordinary original-framing photograph, **deliver at source width by default**. Do not ask the user to choose between dozens of full-canvas redraws and a smaller file merely because ChatGPT returned a smaller LOOK MASTER.

For a 4672×7008 source, the normal target remains 4672×7008. The full source photograph does not need to be regenerated tile-by-tile to prove that dimension; SOURCE MASTER already contains those pixels.

Full-canvas tile redraw is reserved for cases where SOURCE MASTER cannot honestly back the canvas, such as:

- creative full-frame reconstruction;
- generated/synthetic panels;
- outpaint or changed framing with newly invented areas;
- a user explicitly requesting a fully regenerated native-resolution creative canvas.

Do not expose planner tile counts to the user for ordinary source-backed photography.

## 8. Detail planning

Never infer the client's actual patch size from API documentation or planner defaults. Use a previously observed returned bitmap size; on a fresh runtime do one disposable calibration generation, record its real `actual_size`, and never blend that calibration image.

Create the ordinary raw detail plan:

```bash
python3 "$SKILL_ROOT/scripts/plan_detail_tiles.py" \
  --image <hd-working.png> \
  --vision-analysis <vision-analysis.json> \
  --delivery-canvas <WxH> \
  --observed-patch-size <actual-WxH> \
  --detail-budget <fast|balanced|max> \
  --output <detail-plan.raw.json>
```

Budgets are ceilings, not quotas. Prefer zero/few broad valuable regions to micro-patches. Balanced ordinary work should usually remain around 0–3 generated regions.

### 8.1 Normalize source-backed plans

When `job.hd_working_canvas.route == source-backed-detail`, immediately normalize the raw plan:

```bash
python3 "$SKILL_ROOT/scripts/apply_source_backing.py" \
  <job.json> <detail-plan.raw.json> \
  --output <detail-plan.source-backed.json>
```

This step is mandatory for the source-backed route. It:

- converts raw `needs-tiling` pressure into audited SOURCE MASTER backing;
- preserves only the valuable local regions that are actually worth generating;
- records SOURCE MASTER-backed geometry in `job.upscale_passes` so delivery can verify where the source-resolution information came from;
- sets `user_confirmation_required = false` for the discarded full-canvas tiling option.

**Never** call `plan_tile_redraw.py` merely because the pre-normalized ordinary plan estimated many tiles. The raw tiling estimate is diagnostic only for source-backed photography.

### 8.2 Optional relative depth prior

Depth is a hidden spatial guard, not scene truth and not a patch multiplier. Use it only for occlusion, hand/prop front-back ordering, depth-of-field, haze, overlapping subjects, or creative spatial reconstruction.

Apply it **after** source-backed normalization so the final plan SHA is stable:

```bash
python3 "$SKILL_ROOT/scripts/apply_depth_prior.py" \
  --plan <detail-plan.source-backed-or-raw.json> \
  --vision-analysis <vision-analysis.json> \
  --output <detail-plan.final.json>
```

If depth is unnecessary, the normalized/raw plan itself is the final plan.

### 8.3 Full-canvas redraw only for non-source-backed canvases

Only when HD preparation actually returns `full-canvas-tile-redraw`:

```bash
python3 "$SKILL_ROOT/scripts/plan_tile_redraw.py" \
  --image <hd-working.png> \
  --observed-patch-size <actual-WxH> \
  --detail-plan <detail-plan.final.json> \
  --full-canvas --sliver-margin 0 \
  --output <tile-plan.json>
```

For this route, every final area must be backed by executed tile evidence.

## 9. Generate, observe, register, blend

For every **selected** patch/tile:

1. crop the exact planned target;
2. generate with ChatGPT Images using SOURCE MASTER for identity/structure and LOOK MASTER for appearance;
3. materialize the returned bitmap inside the job;
4. record actual dimensions/hash/plan SHA/region index and Pixel Budget;
5. register and blend from the latest clean accepted composite.

Observation:

```bash
python3 "$SKILL_ROOT/scripts/record_patch_observation.py" <job.json> \
  --patch <returned.png> \
  --region-type <type> \
  --requested-size <WxH> \
  --plan <detail-plan.final.json> \
  --planner-region-index <index>
```

Blend:

```bash
python3 "$SKILL_ROOT/scripts/register_blend.py" \
  --base <current-composite> \
  --target <exact-target-crop> \
  --patch <returned.png> \
  --output <next-composite> \
  --x <x> --y <y> \
  --region-type <type> \
  --job <job.json> \
  --plan <detail-plan.final.json> \
  --planner-region-index <index>
```

For a genuine tile-redraw route, use `--tile-plan/--tile-index` instead.

`register_blend.py` writes input-base → patch → output-composite hash-chain receipts. Broad structure first; face normally last.

## 10. Quality gates

Read `references/quality-gates.md` for identity, anatomy, registration, seam, landmark, depth-order and retry rules.

Passing geometric registration alone never proves a patch is visually valid. Failed local generations retry from the last clean accepted composite, not from the failed patch.

## 11. Delivery

Run against the exact master and delivered file:

```bash
python3 "$SKILL_ROOT/scripts/delivery_gate.py" <job.json> \
  --master <accepted-composite> \
  --final <delivered-file> \
  --plan <detail-plan.final.json>
```

A source-backed plan is a normal detail plan for gate purposes. It carries explicit SOURCE MASTER provenance and a geometry pass written by `apply_source_backing.py`.

For a genuine full-canvas creative/synthetic route use `--tile-plan` instead.

Delivery remains fail-closed for things that matter:

- approved/generated input identity is bound by path/size/hash;
- SOURCE MASTER backing or an information-adding route is explicit;
- every selected generated patch has live returned-image evidence;
- every selected patch still has the same hash/size;
- blend receipts form the expected chain;
- the final receipt equals the delivery master;
- required review/quality checkpoints are complete.

**Do not fail ordinary source-width delivery merely because unselected regions would need many generated tiles.** Those regions are explicitly retained from SOURCE MASTER by the source-backed plan.

## 12. State and retry discipline

`job.json` is the execution ledger. Preserve immutable source hashes and review checkpoints.

Typical ordinary flow:

```text
initialized
→ prepared
→ base_generated
→ details_processed
→ completed
```

Preview-first requires approval of the exact base bitmap. Batch jobs establish one approved master look before consistency work.

## 13. Platform rules

- Chat, Work, Voice and Codex are surfaces, not separate image pipelines.
- Use Work for long multi-file/batch jobs and reference gathering; do not replace deterministic local evidence with browser automation.
- Voice controls the same semantic actions; do not build a separate voice stack.
- MCP/Studio owns structured settings, confirmation and catalogs. Local scripts own deterministic file processing and evidence.
- As ChatGPT Images improves, prefer fewer broader generated edits and stronger review gates rather than more patches.

## 14. Anti-duplication rules

Do not build a second image-generation service, browser, voice system, scheduler, or selection editor where ChatGPT already supplies the capability.

Photo Refiner specializes in photographic authority, source-backed high-resolution delivery, spatial safety, patch economics, reproducible evidence, and review/retry discipline.
