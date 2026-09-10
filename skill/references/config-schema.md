# Configuration schema

Persist resolved values in `job.json`.

```yaml
workflow: single                 # single | batch
ui_mode: simple                  # simple | pro; UI presentation only
source_records:                  # immutable source binding
  - path: "/absolute/source.jpg"
    size: 123456
    sha256: "sha256..."
preset: eastern-twilight        # named preset | custom
retouch:
  style_strength: 80            # 0–24 minimal | 25–49 subtle | 50–74 visible | 75–89 strong cinematic | 90–100 bold
resolved_prompt:
  preset: eastern-twilight
  label: "Eastern Twilight"
  summary: "..."
  prompt: "..."
  avoid: "..."
  preset_version: 1
  prompt_hash: "sha256..."
confirmed_at: "ISO-8601 timestamp"
status: initialized              # initialized | prepared | base_generated | details_processed | completed | failed
aspect_ratio: original          # original | 16:9 | 3:2 | 4:5 | 9:16 | custom
framing: preserve               # preserve | crop | outpaint | contain
resolution: source-width        # 4k | source-width | WIDTHxHEIGHT (preview remains accepted for legacy jobs only)
delivery_mode: preview-first    # preview-first | one-click
base_preview:
  required: true                 # single preview-first only; batches use master-frame approval
  approved: false               # required before high-resolution recovery when preview-first
output_format: jpg              # jpg | png | both
batch:
  consistency: balanced         # strict | balanced | creative
  master_frame: auto            # auto | absolute path
  shared_identity: true
  shared_scene: true
  shared_prompt: true
  master_frame_approved: false  # null for single; must become true before continuing a batch
detail:
  mode: adaptive                # base-only | face | adaptive | explicit
  regions: []                   # required when mode is explicit
  patch_scope: head-and-face    # head-and-face | face-only | custom
  head_patch: true              # default separate head/hair patch before face patch
  face: high
  hands: high
  costume: high
  props: medium
quality_gate:
  registration_min_ratio: 0.75
  registration_min_inliers: 40
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

Interactive runs must show the resolved values and the selected preset's full prompt in an expandable preview before writing `job.json` or generating anything. A user reply such as `按默认开始` confirms the displayed values; otherwise apply only the requested changes and show the compact summary again.

For a single image, `preview-first` generates and shows the Image 2.5 base effect image, then stops. It is a style/composition approval artifact, never the high-resolution deliverable. Continue to localized recovery only after explicit approval recorded in `base_preview.approved`. `one-click` proceeds directly through the quality-gated recovery path. Batches retain their existing master-frame approval as the corresponding style checkpoint.

Pass `--confirmed` only after that confirmation. Named presets must exist in `presets.yaml`; `custom` requires a non-empty custom prompt. When a non-original aspect ratio is selected, framing must be `crop`, `outpaint`, or `contain`.

`source-width` preserves the original source width while calculating height from the selected aspect ratio. It does not mean stretching a low-resolution preview without detail passes.

For `master_frame: auto`, choose a source with a sharp face, usable exposure, clear key props, and minimal occlusion. Generate and inspect it first. Other frames use the approved result as a style reference, not as their sole edit target.
