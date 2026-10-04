---
name: photo-refiner
description: Refine source photographs in ChatGPT with a deterministic review workflow, source-backed original-resolution delivery, optional depth guards, and auditable local recovery. Use the companion photo-refiner-creative skill only after a creative recipe is explicitly selected.
---

# Photo Refiner v2.4

Photo Refiner is the photographic orchestration skill inside **Photo Refiner Studio**. ChatGPT Images owns image generation/editing. Photo Refiner owns authority, review checkpoints, high-resolution delivery, patch economics, deterministic registration/blending, and delivery evidence.

Do not call an image-generation API merely to duplicate ChatGPT's built-in image path.

## 1. Product rule: hide engineering complexity

The user chooses photographic intent:

- look / preset / strength;
- creative recipe when wanted;
- review mode;
- delivery target;
- professional controls only when requested.

Keep automatic unless the user explicitly asks for technical detail:

- client patch cap;
- Pixel Budget math;
- patch/tile count;
- HD route;
- source-backing internals;
- depth prior;
- registration model;
- blend receipts;
- retry bookkeeping.

For ordinary original-framing `source-width` photography, original resolution is the normal delivery target. Never ask the user to choose between dozens of redraw tiles and a smaller file merely because the returned LOOK MASTER is smaller than SOURCE MASTER.

## 2. Intent and Studio gate

A question about Photo Refiner, its architecture, settings, limits, or source code is not an edit request. Inspect or explain only.

Start a job only when the user explicitly asks to edit/refine one or more specific photographs.

When a usable source photograph is present, open `open_photo_refiner_settings` with the real source count plus subject-aware recommendations from `references/subject-routing.md` / `references/presets.yaml`.

Opening Studio is the final visible action of that turn. Do not print a parallel settings menu and do not auto-submit.

After Studio submits:

```bash
python3 "$SKILL_ROOT/scripts/init_job.py" <source...> --confirmation-file <confirmationPath>
```

Then immediately hand execution order to the controller:

```bash
python3 "$SKILL_ROOT/scripts/workflow_controller.py" <job.json>
```

## 3. Workflow Controller is authoritative

Do **not** reconstruct the pipeline from prose after each turn. After every state-changing action, approval, regeneration, plan creation, patch/tile completion, or delivery gate, call `workflow_controller.py` again and execute its `next_action`.

The controller returns exactly one semantic action, for example:

```json
{
  "phase": "hd_preparation",
  "next_action": "prepare_hd_working_canvas",
  "user_input_required": false,
  "visible_status": "正在完成原图尺寸智能恢复"
}
```

Semantic user events:

```bash
python3 "$SKILL_ROOT/scripts/workflow_controller.py" <job.json> --event approve
python3 "$SKILL_ROOT/scripts/workflow_controller.py" <job.json> --event continue
python3 "$SKILL_ROOT/scripts/workflow_controller.py" <job.json> --event redo
python3 "$SKILL_ROOT/scripts/workflow_controller.py" <job.json> --event adjust
```

Rules:

- `approve` / `continue` at a review checkpoint means bind the exact displayed bitmap through `update_job.py`; the controller never fabricates approval.
- `redo` regenerates from the last clean authority, never from the rejected output.
- `adjust` returns to Studio instead of stacking another edit on a rejected brief.
- Do not expose internal route names or generation counts in normal conversation; use the controller's `visible_status`.

## 4. Image authorities

Ordinary refinement has three authorities:

- **SOURCE MASTER** — original high-resolution photograph. Owns identity, anatomy, factual geometry, garment/object construction, authentic texture, and source-resolution high-frequency detail.
- **LOOK MASTER** — approved ChatGPT Images result. Owns color, lighting, tone, atmosphere, retouch character, and approved visual style.
- **DETAIL PATCH** — localized generated detail. May add registered mid/high-frequency information where useful but may not redefine SOURCE MASTER structure or LOOK MASTER low-frequency appearance.

A smaller LOOK MASTER does **not** erase the real high-resolution information already present in SOURCE MASTER.

Never continue from a rejected generated image.

## 5. Preparation and base generation

Normalize source color when needed:

```bash
python3 "$SKILL_ROOT/scripts/prepare_source.py" <source> <normalized.png>
```

Build the frozen edit brief:

```bash
python3 "$SKILL_ROOT/scripts/build_edit_prompt.py" <job.json>
```

Advance preparation state using `update_job.py`, then ask the controller for the next action. When it returns `generate_base`, generate the complete base edit with ChatGPT Images.

SOURCE MASTER remains authoritative for identity/geometry. The confirmed settings own appearance.

## 6. Review checkpoint

When the controller returns `await_base_review`, show the generated image and keep the decision simple:

- approve / continue;
- redo;
- adjust settings.

Do not ask the user to reason about HD strategy, patch count, tile count, or Pixel Budget.

For an approved base image, bind the exact file:

```bash
python3 "$SKILL_ROOT/scripts/update_job.py" <job.json> \
  --approve-base-preview \
  --artifact base_preview=<approved-image>
```

Then call the controller again.

## 7. HD delivery: source-backed photography first

When the controller returns `prepare_hd_working_canvas`:

```bash
python3 "$SKILL_ROOT/scripts/prepare_hd_working_canvas.py" <job.json> \
  --input <exact-look-master> \
  --output <job-dir>/intermediates/hd-working.png
```

Current internal routes:

- `native-detail` — LOOK MASTER already supports delivery.
- `source-backed-detail` — normal path for ordinary single-source + original framing + `source-width`; SOURCE MASTER supplies real fine detail and LOOK MASTER supplies approved appearance.
- `ultrasharp-detail` — non-source-backed canvas fits the pinned information-adding upscaler span.
- `full-canvas-tile-redraw` — genuine synthetic/transformed canvas whose final pixels cannot be backed by SOURCE MASTER.

These route names are implementation details. User-facing wording should be **原图尺寸智能恢复 / 正在恢复关键细节 / 正在完成成片**.

### Source-backed invariant

For an ordinary 4672×7008 source whose LOOK MASTER returned around 1024×1536, the normal target remains 4672×7008. Do not regenerate the entire photograph just to prove the dimensions. SOURCE MASTER already owns those source pixels.

Full-canvas redraw is reserved for creative reconstruction, synthetic panels, newly invented outpaint areas, changed framing that creates new pixels, or an explicit user request for a fully regenerated native-resolution creative canvas.

## 8. Detail planning

Never infer the ChatGPT client's actual patch return size from API documentation or planner defaults. Use an empirically observed returned bitmap size. On a fresh runtime, do one disposable calibration generation, materialize it, record `actual_size`, and never blend the calibration image.

Create the raw subject-aware plan:

```bash
python3 "$SKILL_ROOT/scripts/plan_detail_tiles.py" \
  --image <hd-working.png> \
  --vision-analysis <vision-analysis.json> \
  --delivery-canvas <WxH> \
  --observed-patch-size <actual-WxH> \
  --detail-budget <fast|balanced|max> \
  --output <job-dir>/detail-plan.raw.json
```

Budgets are ceilings, not quotas. Prefer zero/few broad high-value regions.

### Source-backed normalization

If `job.hd_working_canvas.route == source-backed-detail`:

```bash
python3 "$SKILL_ROOT/scripts/apply_source_backing.py" \
  <job.json> <job-dir>/detail-plan.raw.json \
  --output <job-dir>/detail-plan.source-backed.json
```

This converts raw `needs-tiling` pressure into audited SOURCE MASTER backing. It sets `user_confirmation_required = false`; any raw `consent_prompt` is diagnostic only and must not be quoted to the user.

### Optional relative depth prior

Depth is a hidden spatial guard, not scene truth and not a patch multiplier. Use it only for occlusion, hand/prop front-back ordering, depth-of-field, haze, overlapping subjects, or creative spatial reconstruction.

When needed:

```bash
python3 "$SKILL_ROOT/scripts/apply_depth_prior.py" \
  --plan <normalized-or-raw-plan.json> \
  --vision-analysis <vision-analysis.json> \
  --output <job-dir>/detail-plan.final.json
```

### Full-canvas redraw

Only when HD preparation actually returns `full-canvas-tile-redraw`:

```bash
python3 "$SKILL_ROOT/scripts/plan_tile_redraw.py" \
  --image <hd-working.png> \
  --observed-patch-size <actual-WxH> \
  --detail-plan <detail-plan.final-or-raw.json> \
  --full-canvas --sliver-margin 0 \
  --output <job-dir>/tile-plan.json
```

After creating any plan, call the controller again.

## 9. Generate, observe, register, blend

Only generate regions selected by the final plan.

For each selected patch/tile:

1. crop the exact planned target;
2. generate with ChatGPT Images using SOURCE MASTER for identity/structure and LOOK MASTER for appearance;
3. materialize the returned bitmap inside the job;
4. record actual dimensions/hash/plan SHA/index and Pixel Budget;
5. register and blend from the latest clean accepted composite.

Observation:

```bash
python3 "$SKILL_ROOT/scripts/record_patch_observation.py" <job.json> \
  --patch <returned.png> \
  --region-type <type> \
  --requested-size <WxH> \
  --plan <detail-plan.json> \
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
  --plan <detail-plan.json> \
  --planner-region-index <index>
```

Use `--tile-plan/--tile-index` only for genuine tile-redraw jobs.

After the selected regions are complete, call the controller; it will return `mark_details_processed` only when evidence is complete.

## 10. Delivery

When the controller returns `run_delivery_gate`:

```bash
python3 "$SKILL_ROOT/scripts/delivery_gate.py" <job.json> \
  --master <accepted-composite> \
  --final <delivered-file> \
  --plan <detail-plan.json>
```

Use `--tile-plan` for genuine full-canvas creative/synthetic redraws.

Delivery remains fail-closed for:

- bound authority path/size/hash;
- explicit SOURCE MASTER backing or other information-adding route;
- selected generated patch/tile evidence;
- accepted registration/blend receipts;
- final composite hash;
- required review checkpoints.

It must **not** fail ordinary source-width delivery merely because unselected regions would need many generated tiles. Those regions remain explicitly SOURCE MASTER-backed.

After the gate passes, call the controller; it will return `complete_job`.

## 11. Creative handoff

Normal photographic refinement is owned by this skill. Creative translation is owned by **`photo-refiner-creative`**.

When Studio confirms `creativeRecipe != none`, initialize the job and explicitly load the companion skill. For `hd-master` creative chains, the controller separates:

1. photographic HD master;
2. creative draft;
3. creative review;
4. final creative delivery redraw.

Do not collapse these checkpoints or run ordinary photographic patches over original-assembly artwork.

## 12. Batch

Batch jobs use one approved master look for consistency, but each frame keeps its own SOURCE MASTER authority. Do not treat a batch as one synthetic multi-source canvas.

The current single-image source-backed implementation must not be generalized by simply checking `len(sources) > 1`; per-frame source backing is the intended batch model.

## 13. Platform rules

- Chat, Work, Voice and Codex are surfaces, not separate image pipelines.
- Use Work for long multi-file/batch execution and reference gathering; do not build another background-task system.
- Voice maps natural language to the same semantic controller events (`continue`, `redo`, `adjust`).
- MCP/Studio owns structured settings and confirmation. Local scripts own deterministic file processing/evidence.
- As ChatGPT Images improves, generate fewer patches and rely more on full-image quality gates.

## 14. Anti-duplication

Do not build a second image-generation backend, browser, voice system, task scheduler, or selection editor where ChatGPT already supplies the capability.

Photo Refiner differentiates on photographic authority, source-backed original-resolution delivery, spatial safety, patch economics, deterministic workflow control, reproducible evidence, and review/retry discipline.
