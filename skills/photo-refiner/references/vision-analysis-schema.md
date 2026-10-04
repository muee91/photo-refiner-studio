# Vision analysis handoff

`plan_detail_tiles.py` accepts a coarse result from the model's visual analysis
pass through `--vision-analysis`. This keeps detection and planning separate:
the Vision pass identifies meaningful regions, while the planner scores,
merges, and budgets them.

Example:

```json
{
  "schema_version": 1,
  "coordinate_space": "normalized",
  "subject_type": "classical-portrait",
  "portrait_extent": "full",
  "detail_complexity": "complex",
  "regions": {
    "subject": {"x": 0.22, "y": 0.10, "width": 0.56, "height": 0.82},
    "face": {"x": 0.40, "y": 0.18, "width": 0.18, "height": 0.15},
    "hands": [
      {"x": 0.28, "y": 0.68, "width": 0.12, "height": 0.14}
    ],
    "props": [
      {"x": 0.58, "y": 0.48, "width": 0.20, "height": 0.26}
    ]
  },
  "depth_prior": {
    "source": "vision-relative",
    "confidence": 0.82,
    "subject_depth_uniformity": 0.74,
    "occlusion_risk": "high",
    "background_separation": "strong",
    "intents": ["occlusion"],
    "discontinuities": [
      {
        "label": "foreground-railing",
        "relation": "foreground-over-subject",
        "strength": 0.91,
        "box": {"x": 0.18, "y": 0.58, "width": 0.64, "height": 0.12}
      }
    ]
  }
}
```

`coordinate_space` is required in generated results and may be `pixel` or
`normalized`. Normalized boxes use fractions of the source image. The required
`subject_type` values are `portrait`, `classical-portrait`, `landscape`,
`architecture`, and `generic`. `subject` and `face` are single boxes;
`hands` and `props` are arrays.

For portrait-like subjects, `portrait_extent` is optional and may be `close`,
`half`, `full`, or `complex-full`. If omitted, the planner infers it from
face-to-subject scale. `detail_complexity` is optional and may be `normal` or
`complex`; use `complex` only when clothing, props, or other large subject
surfaces genuinely justify a larger recovery budget. These hints are consumed
by the `creative-safe` recovery profile and do not force patch generation.

## Optional depth prior

`depth_prior` is optional. Omit it for routine color/tone work, simple portraits,
and ordinary face recovery. Add it only when relative depth materially helps:
foreground occlusion, depth-of-field, atmospheric perspective, overlapping
subjects, or creative spatial reconstruction.

The prior is **advisory**. SOURCE MASTER remains the authority for visible
geometry and occlusion. Monocular depth must not be treated as metric distance or
hard scene truth.

Fields:

- `source`: `vision-relative | dense-map | external`.
- `confidence`: 0–1.
- `subject_depth_uniformity`: optional 0–1 hint used only for merge safety.
- `occlusion_risk`: `low | medium | high`.
- `background_separation`: `weak | medium | strong | unknown`.
- `intents`: optional subset of `occlusion`, `depth-of-field`,
  `atmospheric-perspective`, `creative-spatial`.
- `discontinuities`: optional coarse boundaries. Each entry contains a label,
  `strength` 0–1, a box in the same `coordinate_space`, and one relation:
  `foreground-over-subject`, `self-occlusion`, `subject-over-background`, or
  `unknown`.

Do not emit dense per-pixel arrays in this JSON. If a future dense-depth backend
is used, keep its raw map separate and summarize only the stable spatial facts in
`depth_prior`.

`plan_detail_tiles.py` deliberately ignores extra fields, so depth does not alter
generation count by accident. When `depth_prior` is present, apply it **after**
normal detail planning:

```bash
python3 "$SKILL_ROOT/scripts/apply_depth_prior.py" \
  --plan <detail-plan.json> \
  --vision-analysis <vision-analysis.json> \
  --output <detail-plan.depth.json>
```

Use the annotated plan consistently for patch observation and audited blending so
its plan SHA remains stable through the evidence chain. The post-processor adds
only `depth_guard` metadata; it must not create new regions or raise generation
budgets.

See `depth-prior.md` for trigger, merge, prompt, and review rules.

Additional fields such as confidence or labels may be included by the Vision
backend and are ignored by the base planner.

Run normal planning with:

```bash
python3 "$SKILL_ROOT/scripts/plan_detail_tiles.py" \
  --image <source-or-look-master> \
  --vision-analysis <vision-analysis.json> \
  --detail-budget balanced
```

The existing `--subject-box`, `--face-box`, `--hand-box`, and `--prop-box`
flags remain supported for explicit/manual callers. A manually supplied value
takes precedence over the corresponding Vision field.
