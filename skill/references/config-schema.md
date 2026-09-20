# Configuration schema

Persist resolved values in `job.json`. Version 2.3 retains the v2.2 SOURCE/LOOK/DETAIL refinement model and adds an explicitly selected creative-translation branch.

```yaml
version: 2
release_version: "2.3"
execution_mode: photo-refinement   # photo-refinement | creative-translation
creative_recipe: null              # resolved catalog record when creative translation is selected
creative_output: null              # creative translation only: {mode: direct-effect | original-assembly, label_zh, original_assembly}
workflow: single                 # single | batch
ui_mode: simple                  # simple | pro; UI presentation only
working_color_space: sRGB        # v2.2 working/delivery space
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
status: initialized              # initialized | prepared | base_generated | details_processed | completed | failed
aspect_ratio: original           # original | 16:9 | 3:2 | 4:5 | 9:16 | custom
framing: preserve               # preserve | crop | outpaint | contain
resolution: source-width        # 4k | source-width | WIDTHxHEIGHT (preview remains accepted for legacy jobs only)
delivery_mode: preview-first    # preview-first | one-click
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
  planner: adaptive-value-merge-v2.2  # coarse planner that prefers merging over splitting
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

For a single image, `preview-first` generates and shows the Image 2.5 base effect image, then stops. After explicit approval it becomes LOOK MASTER. Continue to localized recovery only after approval recorded in `base_preview.approved`. `one-click` proceeds directly through the quality-gated path. Batches use the approved master frame as the corresponding style checkpoint.

Pass `--confirmed` only after confirmation. Named presets must exist in `presets.yaml`; `custom` requires a non-empty custom prompt. When a non-original aspect ratio is selected, framing must be `crop`, `outpaint`, or `contain`.

`source-width` preserves the original source width while calculating height from the selected aspect ratio. It does not mean stretching a low-resolution preview without detail passes. Every planned detail tile must satisfy its effective pixel budget before generation.

For `master_frame: auto`, choose a source with a sharp face, usable exposure, clear key props and minimal occlusion. Other frames use the approved master look as a style reference, not as their sole edit target.

For `execution_mode: creative-translation`, `creative_recipe` is selected after the normal style preset and freezes the selected catalog id, title, source-count contract, source commit, recipe root, and output structure. The selected normal preset remains frozen in `resolved_prompt` as the upstream visual direction. `creative_assembly_mode` is `direct-effect` by default or `original-assembly` only when explicitly selected. Direct-effect produces one complete creative effect image without an unchanged source-evidence comparison area or any deterministic panel assembly; original-assembly preserves the original recipe's evidence/generated-panel layout and deterministic compositor. Both modes record ordinary local detail recovery as `not-applicable` and must not run face/head/costume patches over the creative artwork. Multi-photo creative recipes still approve the generated/assembled effect preview through `--approve-base-preview`; they never use the normal batch master-frame gate. `creative_output.aspect_ratio_source` is `panel` for single-source direct-effect jobs — `effective_aspect_ratio` is then the confirmed panel ratio, where `original` follows the source photograph's own ratio — and `recipe` for original-assembly or multi-photo jobs, which keep `effective_aspect_ratio` equal to the recipe's documented output ratio. `creative_output.upstream_binding` is `direction-only` by default: the single-pass creative brief treats the frozen preset as look direction only and the recipe as the sole structural authority. When the user opts into the two-stage flow — offered conversationally for single-source direct-effect jobs in preview-first mode, or via `--creative-from-base`; a legacy `creativeFromBase` confirmation field is still honored — it is `look-master`: stage 1 renders the frozen preset as an ordinary style brief plus a stage note and requires explicit approval of that main image, and stage 2 translates creatively with the approved main image as look reference while identity stays anchored to the source photograph.

## v2.2 planning rules

- `fast`: soft 1 / hard 1
- `balanced`: soft 3 / hard 6
- `max`: soft 5 / hard 8
- The soft value is the normal operating envelope, not a quota. The planner may select fewer or zero regions after value/scale filtering.
- Overflow beyond the soft value is allowed only for remaining high-value regions that still justify the latency; the hard ceiling is absolute unless the user explicitly overrides it.
- Portrait defaults still prefer the coarse order `costume -> head -> face`, with hand/prop tiles added only when the budget and visual value justify them.
- `mask_mode: lightweight` means coarse mask guidance for blending only; it must not be interpreted as a requirement to generate more sub-patches.
