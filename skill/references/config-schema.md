# Configuration schema

Persist resolved values in `job.json`. This contract keeps the SOURCE / LOOK / DETAIL refinement model and adds an explicitly selected creative-translation branch. The release string below is the Skill's product version and must match `SKILL_VERSION` in `scripts/job_contract.py`, which is the only place it is written down.

```yaml
version: 2
release_version: "2.4"
execution_mode: photo-refinement   # photo-refinement | creative-translation
creative_recipe: null              # resolved catalog record when creative translation is selected
creative_output: null              # creative translation only: {mode: direct-effect | original-assembly, label_zh, original_assembly}
workflow: single                 # single | batch
ui_mode: simple                  # simple | pro; UI presentation only
working_color_space: sRGB        # the working and delivery space for every job
authority_model:
  source_master:                 # original high-resolution photograph
    - identity
    - anatomy
    - factual_geometry
    - construction
    - authentic_material_reference
  look_master:                   # approved Image 2.5 base
    - approved_color
    - lighting
    - tone
    - atmosphere
    - visual_style
  detail_patch:
    - registered_mid_frequency_detail
    - registered_high_frequency_detail
source_records:                  # immutable source binding
  - path: "/absolute/source.jpg"
    size: 123456
    sha256: "sha256..."
preset: natural-cinematic        # subject-recommended named preset | custom
retouch:
  style_strength: 45             # UI/audit value; mapped to semantic execution level before generation
resolved_prompt:
  preset: natural-cinematic
  label: "Natural Cinematic"
  summary: "..."
  prompt: "..."
  avoid: "..."
  default_strength: 45
  preset_version: 2
  prompt_hash: "sha256..."
confirmed_at: "ISO-8601 timestamp"
status: initialized              # initialized | prepared | base_generated | details_processed | creative_generated | completed | failed
                             # creative_generated appears only on hd-master creative chains
aspect_ratio: original           # original | 16:9 | 3:2 | 4:5 | 9:16 | custom
framing: preserve               # preserve | crop | outpaint | contain
resolution: source-width        # 4k | source-width | WIDTHxHEIGHT (preview remains accepted for legacy jobs only)
delivery_mode: preview-first    # preview-first | one-click
hd_working_canvas_policy:
  mode: automatic
  script: scripts/prepare_hd_working_canvas.py
  model_native_information_scale: 4
  max_interpolation_tail: 1.05
  routes: [native-detail, ultrasharp-detail, full-canvas-tile-redraw]
hd_working_canvas: null          # written by prepare_hd_working_canvas.py
upscale_passes: []               # trusted scale comes from information_to, not file size alone
base_preview:
  required: true                 # single preview-first or any preview-first creative translation
  approved: false                # when true, accepted base becomes LOOK MASTER
output_format: jpg              # jpg | png | both
batch:
  consistency: balanced         # strict | balanced | creative
  master_frame: auto            # auto | absolute path
  shared_identity: true
  shared_scene: true
  shared_prompt: true
  master_frame_approved: false  # null for single or creative translation; normal batches require approval
detail:
  mode: adaptive                # base-only | face | adaptive | explicit
  generation_budget: balanced   # fast | balanced | max
  soft_generated_patch_budget: 3 # normal envelope; never a quota
  hard_generated_patch_ceiling: 6 # high-value overflow limit
  max_generated_patches: 6       # compatibility alias of hard ceiling
  adaptive_overflow: true
  planner: adaptive-value-merge-v2.4  # coarse planner that prefers merging over splitting
  mask_mode: lightweight        # coarse blend mask; not fine semantic segmentation
  regions: []                   # required when mode is explicit
  patch_scope: head-and-face    # head-and-face | face-only | custom
  head_patch: true
  pixel_budget_thresholds:
    face: 0.85
    hand: 0.75
    head: 0.65
    costume: 0.50
    prop: 0.50
    architecture: 0.50
    background: 0.30
    generic: 0.50
quality_gate:
  registration_min_ratio: 0.75
  registration_min_inliers: 40
  registration_model_by_region:
    face: similarity
    head: affine
    hand: affine
    costume: homography
    prop: homography
    architecture: homography
    background: homography
    generic: homography
  identity_structure_review_required: true
  landmark_identity_gate:
    mode: optional-when-landmarks-available
    max_normalized_rmse: 0.055
    max_point_error: 0.10
  max_retries: 2
output:
  separate_job_folder: true
  keep_intermediates: false
artifacts: []
history:
  - status: initialized
    at: "ISO-8601 timestamp"
```

Infer `workflow` from input count. In batch mode resolve `batch.consistency`; it is irrelevant for a single image.

Interactive runs must show the resolved values before writing `job.json` or generating anything. A user reply such as `按默认开始` confirms the displayed values; otherwise apply only the requested changes and show the compact summary again.

The selected preset is a **subject-aware recommendation**, not a global fixed style. `references/presets.yaml` provides `default_strength` for the starting slider value. The numeric slider remains useful for UI and audit, but `build_edit_prompt.py` converts it to the semantic execution levels `minimal`, `subtle`, `visible`, `strong`, or `transformative` before generation.

For a single image, `preview-first` generates and shows the Image 2.5 base effect image, then stops. After explicit approval it becomes LOOK MASTER. Continue to localized recovery only after approval recorded in `base_preview.approved`. `one-click` proceeds directly through the quality-gated path for ordinary jobs. `hd-master` creative chains require `preview-first` and reject one-click because the HD master and creative draft are both explicit checkpoints. Batches use the approved master frame as the corresponding style checkpoint.

Pass `--confirmed` only after confirmation. Named presets must exist in `presets.yaml`; `custom` requires a non-empty custom prompt. When a non-original aspect ratio is selected, framing must be `crop`, `outpaint`, or `contain`.

`source-width` preserves the original source width while calculating height from the selected aspect ratio. It does not mean stretching a low-resolution preview without detail passes. Every planned detail tile must satisfy its effective pixel budget before generation.

For `master_frame: auto`, choose a source with a sharp face, usable exposure, clear key props and minimal occlusion. Other frames use the approved master look as a style reference, not as their sole edit target.

For `execution_mode: creative-translation`, `creative_recipe` is selected after the normal style preset and freezes the selected catalog id, title, source-count contract, source commit, recipe root, and output structure. The selected normal preset remains frozen in `resolved_prompt` as the upstream visual direction. `creative_assembly_mode` is `direct-effect` by default or `original-assembly` only when explicitly selected. Direct-effect produces one complete creative effect image without an unchanged source-evidence comparison area or any deterministic panel assembly; original-assembly preserves the original recipe's evidence/generated-panel layout and deterministic compositor. A single-source `direct-effect` job whose recipe permits recovery records `detail.mode: creative-safe-adaptive`, whose operative ceilings come from the coverage stage table below rather than one flat number; `original-assembly` and multi-source layouts record `not-applicable` and must never receive photographic patches over the translated artwork. Multi-photo creative recipes still approve the generated/assembled effect preview through `--approve-base-preview`; they never use the normal batch master-frame gate. `creative_output.aspect_ratio_source` is `panel` for single-source direct-effect jobs — `effective_aspect_ratio` is then the confirmed panel ratio, where `original` follows the source photograph's own ratio — and `recipe` for original-assembly or multi-photo jobs, which keep `effective_aspect_ratio` equal to the recipe's documented output ratio. `creative_output.upstream_binding` is `direction-only` by default (and for original-assembly or multi-source jobs even when the HD toggle is on): the single-pass creative brief treats the frozen preset as look direction only and the recipe as the sole structural authority. When the user opts into the two-stage flow — offered conversationally for single-source direct-effect jobs in preview-first mode, or via `--creative-from-base`; a legacy `creativeFromBase` confirmation field is still honored — it is `look-master`: stage 1 renders the frozen preset as an ordinary style brief plus a stage note and requires explicit approval of that main image, and stage 2 translates creatively with the approved main image as look reference while identity stays anchored to the source photograph. `hd-master` (the 高清创意链 toggle, `creativeHdChain` / `--creative-hd-chain`) is the full chain: stage 1 renders and recovers the main image to a high-definition master with the ordinary detail profile, `creative_preview.required` gates the creative draft through `--approve-creative-preview`, and stage 4 is the style-faithful tiled redraw (per-tile composition registration against the draft, multiband overlap blending) to native resolution. The state machine inserts `creative_generated` between `details_processed` and `completed` for these jobs only.

## Delivery contract: two canvases

The manifest separates the space patches are composited in from the space the file is
delivered in, because conflating them is what let a 1024x1536 master ship as a
4672x7008 "high resolution" file.

```yaml
approved_preview:                 # written by --approve-base-preview / --approve-creative-preview
  kind: base_preview              # base_preview | look_master | creative_preview
  path: .../approved-preview.png
  size: [1024, 1536]
  sha256: ...                     # an approval without an --artifact is refused
hd_working_canvas:                # written for preview-first and one-click jobs
  input: .../look-master.png
  input_size: [1024, 1536]
  input_sha256: ...
  delivery_canvas: [4672, 7008]
  route: full-canvas-tile-redraw  # native-detail | ultrasharp-detail | full-canvas-tile-redraw
  output: .../hd-working.png
  output_size: [4672, 7008]
  output_sha256: ...
  requires_full_canvas_redraw: true
upscale_passes:                   # appended by upscale_image.py --job
  - engine: 4x-ultrasharp-ncnn
    adds_information: true
    from: [1024, 1536]
    to: [6144, 9216]              # compatibility file size may exceed native model scale
    native_information_scale: 4
    information_to: [4096, 6144]  # only this boundary raises delivery geometry
    interpolated_tail: [2048, 3072]
delivery_gate:                    # written by delivery_gate.py; mandatory before status completed
  verdict: pass                   # pass | fail  (geometry AND budget must both pass)
  master: {path: ..., size: [...], sha256: ...}
  final:  {path: ..., size: [4672, 7008], sha256: ...}
  delivery_scale: 1.14
  geometry:
    verdict: pass
    reference_size: [1024, 1536]
    reference_source: approved_preview   # or hd_working_canvas_input for one-click
    reference_evidence_ok: true
    upscale_raise_factor: 4.0
    information_canvas: [4096, 6144]
    effective_canvas: [4096, 6144]
    geometry_override: null              # full-canvas-tile-redraw when every final area was redrawn
    effective_scale: 1.14
    max_honest_upscale: 1.05
  budget:
    verdict: pass                 # fail on dropped regions, needs-tiling, or a failed patch recheck
    planned_regions: 5
    dropped_regions: []
    failed_observations: []
  diff:
    path: .../preview_vs_final_diff.png
    compared_at_size: [4672, 7008]
    changed_pixel_share: 0.031
  required_action: "..."          # what to do instead of shipping this

detail_plan:                      # plan_detail_tiles.py reports the same contract
  working_canvas: [1024, 1536]
  delivery_canvas: [4672, 7008]
  delivery_scale: 4.5625
  delivery_feasibility:
    verdict: needs-tiling         # native | needs-tiling
    requested_delivery_width: 4672
    max_honest_delivery_width: 3151
  tiling_requirement:
    tile_size: [1254, 1254]
    tile_count: 20
    estimated_generation_calls: 20
    consent_prompt: "..."         # quote this to the user before spending 20 generations
  regions_dropped_for_budget: []
```

`update_job.py` re-measures the gate's bound files, so changing either after the gate
ran makes the verdict stale and blocks `completed`. Approval flags now require the
image they approve as an `--artifact`, which is what makes the geometry verdict
meaningful: it compares the delivery against the picture the user actually saw.
Budget evidence is also mandatory. Every current-version job first runs
`prepare_hd_working_canvas.py`, which binds the exact generated/approved master and
selects `native-detail`, `ultrasharp-detail`, or `full-canvas-tile-redraw`.
Recovery-enabled ordinary / creative-safe jobs normally gate with
`--plan <detail-plan.json>`. When the router returns
`full-canvas-tile-redraw`, adaptive/face/explicit recovery first plans the subject
on the delivery-size scaffold with `plan_detail_tiles.py`, then builds the final
tile plan with **both** `--detail-plan <detail-plan.json>` and
`--full-canvas --sliver-margin 0`. This preserves stricter face/head/hand Pixel
Budgets while generic tiles fill the rest of the frame. The delivery then gates with
that `--tile-plan`. An `hd-master` final creative redraw also gates with
`--tile-plan`.

The supplied plan canvas must equal the actual delivered canvas. Every selected
ordinary / creative-safe region must have a live `detail-patch` observation bound
to the exact detail-plan SHA256 plus an ordered `register_blend.py` receipt chain
ending at the delivery master's SHA256. Tile routes require the same invariant per
tile using `tile-redraw` observations and the exact tile-plan SHA256. Current tile
plans also bind `canvas_path + canvas_sha256`; the first audited blend receipt must
start from that exact canvas and the final receipt must end at the delivery master.
Only a fully executed **subject-aware full-canvas** tile plan with zero holes and zero
delegated slivers may replace a global geometry failure. A feasible plan without
generated-and-blended execution evidence is a hard delivery failure. A legitimate
zero-region detail plan remains valid without patch calls when its prepared HD
working-canvas output remains intact.

For 4X-UltraSharp, `to` is a file dimension while `information_to` is the trusted
information boundary. Requests above the model-native 4× span may create a larger
file, but the excess is `interpolated_tail` and does not raise delivery geometry.
A later AI pass that begins from that interpolated file cannot chain unless its
`from` size equals the prior `information_to` canvas.

## Tile redraw plan (tile-plan.json)

`plan_tile_redraw.py` expands a `needs-tiling` verdict into concrete boxes. This is an
artifact file, not part of `job.json`.

```yaml
schema_version: 1
canvas: [4672, 7008]              # the canvas being redrawn, in its own pixels
canvas_path: .../hd-working.png   # exact redraw starting canvas
canvas_sha256: ...                # blend-chain first receipt must start from this hash
observed_patch_size: [1254, 1254]
tile_overlap: 0.15
tile_count: 11                     # after both drop rules; the real cost
deduplicated_tiles: 2              # fully covered by an equal or finer tile
sliver_tiles_dropped: 3            # added < --sliver_margin (default 0.05) of new area
coverage:
  target_area: ...
  covered_area: ...
  uncovered_area: ...              # includes delegated thin remainders
  sliver_area: ...                 # remainder intentionally left to the base canvas
  hole_area: 0                     # must be 0: anything else is a real gap
  largest_sliver_fraction: 0.024
estimated_generation_calls: 12
verdict: pass                      # fail (exit 2) on any gap or unfillable tile
tiles:
  - index: 0
    box: {x: 2150, y: 1740, width: 1342, height: 1475}
    region_type: face
    threshold: 0.85
    requested_size: [1141, 1254]   # ask the generator exactly this
    budget_ratio: 0.8502           # must be >= threshold by construction
    blend_order: 30
blend_sequence: [8, 9, ...]        # coarse first, face last
```

## Planning rules

- `fast`: soft 1 / hard 1
- `balanced`: soft 3 / hard 6
- `max`: soft 5 / hard 8
- creative-safe ceilings depend on the coverage the Vision pass reports and are carried as a table (`portrait_budget_policy`) rather than one flat number, because a single permissive `hard` value reads as permission to over-generate: close/half soft 2 hard 3, full 3/4, complex-full 4/5, non-portrait scene 2/3. `absolute_generated_patch_ceiling` is a runaway-time guard, never a per-region allowance.
- The soft value is the normal operating envelope, not a quota. The planner may select fewer or zero regions after value/scale filtering.
- Overflow beyond the soft value is allowed only for remaining high-value regions that still justify the latency; the hard ceiling is absolute unless the user explicitly overrides it.
- Portrait defaults still prefer the coarse order `costume -> head -> face`, with hand/prop tiles added only when the budget and visual value justify them.
- `mask_mode: lightweight` means coarse mask guidance for blending only; it must not be interpreted as a requirement to generate more sub-patches.
