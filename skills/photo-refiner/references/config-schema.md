# Photo Refiner job contract

`job.json` is the execution ledger. It records what the user confirmed, which
files became authorities, what the ChatGPT client actually returned, and whether
the delivered master can be reproduced from accepted evidence.

This document describes the **current** v2.4 contract. Internal planner/tile
costs are diagnostics. They are not user choices unless the requested canvas
cannot be backed by the real source photograph and an actual creative/synthetic
redraw is required.

## Core manifest

```yaml
version: 2
release_version: "2.4"
status: initialized              # initialized | prepared | base_generated | details_processed | creative_generated | completed | failed
execution_mode: photo-refinement # photo-refinement | creative-translation
workflow: single                 # single | batch
ui_mode: simple                  # simple | pro
working_color_space: sRGB

sources:
  - /absolute/source.jpg
source_records:
  - path: /absolute/source.jpg
    size: 123456
    sha256: ...

preset: natural-cinematic
resolved_prompt:
  preset: natural-cinematic
  label: Natural Cinematic
  summary: ...
  prompt: ...
  avoid: ...
  prompt_modifier_ids: []
  default_strength: 45
  preset_version: 2
  prompt_hash: ...

aspect_ratio: original
framing: preserve               # preserve | crop | outpaint | contain
resolution: source-width        # preview | 4k | source-width | WIDTHxHEIGHT
delivery_mode: preview-first    # preview-first | one-click
output_format: jpg              # jpg | png | both
```

## Authority model

Ordinary refinement:

```yaml
authority_model:
  source_master:
    - identity
    - anatomy
    - factual_geometry
    - construction
    - authentic_material_reference
    - source_resolution_high_frequency_detail
  look_master:
    - approved_color
    - lighting
    - tone
    - atmosphere
    - visual_style
  detail_patch:
    - registered_mid_frequency_detail
    - registered_high_frequency_detail
```

A smaller LOOK MASTER does not erase the real high-resolution information in
SOURCE MASTER.

## Review checkpoints

```yaml
base_preview:
  required: true
  approved: false
creative_preview:
  required: false
  approved: false
approved_preview: null           # exact approved path/size/hash when approval happens
```

Approval is evidence, not a boolean convenience. `update_job.py` requires the
exact approved image artifact and stores its measured hash and dimensions.

## HD working-canvas contract

There are four current routes:

```yaml
hd_working_canvas_policy:
  mode: automatic
  script: scripts/prepare_hd_working_canvas.py
  routes:
    - native-detail
    - source-backed-detail
    - ultrasharp-detail
    - full-canvas-tile-redraw
  user_facing_policy: hide-internal-route-and-patch-economics
```

### `native-detail`

LOOK MASTER already supports the delivery canvas within the honest resize tail.

### `source-backed-detail`

Default for ordinary **single-source + original framing + source-width**
photography when LOOK MASTER is smaller than the original. SOURCE MASTER supplies
real high-frequency source detail; LOOK MASTER supplies approved appearance.
Only valuable local regions are generated afterwards.

This route means original resolution is the normal delivery target, not an
expensive option. Raw planner estimates such as `22 tiles` must never be exposed
as a user confirmation for ordinary source-backed photography.

Example:

```yaml
hd_working_canvas:
  schema_version: 2
  route: source-backed-detail
  input: .../look-master.png
  input_size: [1024, 1536]
  input_sha256: ...
  delivery_canvas: [4672, 7008]
  source_backed: true
  source_detail_result:
    method: source-luminance-highpass
    source_master: /absolute/source.jpg
    source_master_sha256: ...
    look_master: .../look-master.png
    look_master_sha256: ...
  output: .../intermediates/hd-working.png
  output_size: [4672, 7008]
  output_sha256: ...
  requires_full_canvas_redraw: false
```

### `ultrasharp-detail`

Used only when SOURCE MASTER cannot honestly back the canvas and the requested
canvas fits the pinned 4X-UltraSharp information span. `information_to`, not the
file's final `to` size, is the trusted information boundary.

### `full-canvas-tile-redraw`

Reserved for transformed/synthetic canvases whose final pixels cannot be backed
by SOURCE MASTER, such as creative full-frame reconstruction, generated panels,
or newly invented outpaint areas.

The ordinary source-width photo path must not enter this route merely because a
single generated patch cannot cover a large subject footprint.

## Source-backed plan normalization

`plan_detail_tiles.py` may conservatively emit a raw `needs-tiling` verdict. For
`source-backed-detail`, immediately normalize it with `apply_source_backing.py`.

```yaml
delivery_feasibility:
  verdict: source-backed
  requested_delivery_width: 4672
  max_honest_delivery_width: 4672

tiling_requirement:
  required: false
  estimated_generation_calls: 0
  user_confirmation_required: false

source_backing:
  enabled: true
  mode: source-master-high-frequency
  source_backed_regions:
    - region_type: costume
      action: retain-source-master-detail
```

A source-backed region does **not** consume generated patch quota.

## Detail contract

```yaml
detail:
  mode: adaptive                # base-only | face | adaptive | explicit
  generation_budget: balanced  # fast | balanced | max
  soft_generated_patch_budget: 3
  hard_generated_patch_ceiling: 6
  adaptive_overflow: true
  planner: adaptive-value-merge-v2.4
  mask_mode: lightweight
  regions: []
  pixel_budget_thresholds:
    face: 0.85
    hand: 0.75
    head: 0.65
    costume: 0.50
    prop: 0.50
    architecture: 0.50
    background: 0.30
    generic: 0.50
```

Budgets are ceilings, not quotas. Prefer zero/few broad high-value regions.

## Patch/tile evidence

Each generated local result must be materialized and measured. Never infer actual
return dimensions from API documentation or a planner request.

```yaml
patch_observations:
  - evidence_kind: detail-patch
    evidence_plan_sha256: ...
    planner_region_index: 0
    patch_path: ...
    patch_sha256: ...
    requested_size: [1024, 1024]
    actual_size: [1024, 1024]
    budget_recheck:
      accepted: true

detail_blend_receipts:
  - kind: detail-patch
    detail_plan_sha256: ...
    planner_region_index: 0
    input_base_sha256: ...
    patch_sha256: ...
    output_sha256: ...
    registration:
      accepted: true
```

Tile-redraw jobs use the same evidence model with `tile_index`,
`tile_plan_sha256`, and `tile_blend_receipts`.

## Delivery gate

```yaml
delivery_gate:
  verdict: pass
  master: {path: ..., size: [...], sha256: ...}
  final: {path: ..., size: [...], sha256: ...}
  geometry:
    verdict: pass
  budget:
    verdict: pass
  required_action: ""
```

The gate is fail-closed for selected generated patches/tiles, authority hashes,
registration/blend receipts, and the final master. It must **not** fail ordinary
source-width delivery because unselected regions would require many generated
tiles; those regions remain explicitly SOURCE MASTER-backed.

## Workflow controller

`workflow_controller.py` is the deterministic next-action layer. The model should
not reconstruct the state machine from prose on each turn.

The controller reads `job.json` and durable job artifacts and returns exactly one
semantic action, for example:

```json
{
  "phase": "hd_preparation",
  "next_action": "prepare_hd_working_canvas",
  "user_input_required": false,
  "visible_status": "正在完成原图尺寸智能恢复"
}
```

User-visible review events are semantic:

- `approve` / `continue`
- `redo`
- `adjust`

The controller never invents approval. `approve` still requires binding the exact
approved bitmap through `update_job.py`.

Internal implementation details such as patch caps, Pixel Budget values, tiling
counts, registration models, and blend receipts stay hidden unless the user asks
for technical details.

## Batch note

A normal batch has one approved master look, but every frame still owns its own
SOURCE MASTER. Future batch source-backing should therefore be per-frame rather
than treating all sources as one multi-source synthetic canvas.
