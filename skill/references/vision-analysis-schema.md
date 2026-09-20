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
Additional fields such as confidence or labels may be included by the Vision
backend and are ignored by the planner.

Run it with:

```bash
python3 "$SKILL_ROOT/scripts/plan_detail_tiles.py" \
  --image <source-or-look-master> \
  --vision-analysis <vision-analysis.json> \
  --detail-budget balanced
```

The existing `--subject-box`, `--face-box`, `--hand-box`, and `--prop-box`
flags remain supported for explicit/manual callers. A manually supplied value
takes precedence over the corresponding Vision field.
