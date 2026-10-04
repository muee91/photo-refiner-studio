# Optional depth prior

Depth is an **advisory geometric prior**, never scene truth and never a reason to add generations by itself.

Photo Refiner uses depth only when it materially helps preserve spatial structure: foreground occlusion, depth-of-field, atmospheric perspective, complex overlapping subjects, or creative spatial reconstruction. Ordinary color/tone work, simple portraits, and routine face recovery should not run an extra depth stage.

## Default policy

```text
mode: auto
default: off unless a trigger is visible
new patch quota: 0
raw dense map retention: off
truth authority: SOURCE MASTER, not depth
```

Depth may influence:

- front/back ordering constraints for a patch prompt;
- whether a broad region is safe to merge across a spatial boundary;
- whether hand/prop/foreground overlap requires explicit visual review;
- depth-of-field or atmospheric-perspective instructions when the user asked for them.

Depth must **not**:

- replace SOURCE MASTER geometry;
- invent metric distance from monocular imagery;
- force a new patch merely because a depth discontinuity exists;
- turn a reflection, mirror, water surface, transparent object, sky, or long-lens compression into a hard geometry claim;
- create dozens of masks or micro-regions.

## Auto triggers

Enable the prior when one or more are present:

- a foreground object crosses the person or another important subject;
- hands/props sit clearly in front of or behind the torso;
- the requested edit changes depth-of-field or background blur;
- mist, haze, aerial perspective, or layered landscape depth is part of the requested look;
- a creative translation needs to retain clear foreground/midground/background ordering;
- the scene contains multiple overlapping subjects where accidental layer swaps would be damaging.

Otherwise omit `depth_prior` from the Vision handoff.

## Vision handoff

The optional object belongs inside `vision-analysis.json`:

```json
{
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

`source` may be `vision-relative`, `dense-map`, or `external`. `vision-relative` means the active multimodal model inferred coarse ordering directly from the photograph. It is intentionally cheap and is the default implementation. A future dense-depth backend can emit the same contract without changing the planner or patch pipeline.

`confidence` and `subject_depth_uniformity` use 0–1. `occlusion_risk` is `low | medium | high`. `background_separation` is `weak | medium | strong | unknown`.

A discontinuity relation may be:

- `foreground-over-subject`
- `self-occlusion`
- `subject-over-background`
- `unknown`

The discontinuity `box` uses the same `coordinate_space` as the rest of the Vision handoff.

## Apply after detail planning

Depth does not replace `plan_detail_tiles.py`. When `depth_prior` exists, post-process the normal detail plan:

```bash
python3 "$SKILL_ROOT/scripts/apply_depth_prior.py" \
  --plan <detail-plan.json> \
  --vision-analysis <vision-analysis.json> \
  --output <detail-plan.depth.json>
```

The output keeps the same crops, region count, Pixel Budget and generation ceiling. It only adds per-region `depth_guard` metadata and a plan-level `depth_prior` summary. Downstream observation/blend tools accept the annotated plan because its existing region contract is unchanged.

Use the **annotated plan** consistently for patch observation and audited blending so the plan SHA remains stable across the evidence chain.

## Merge guidance

- High/medium occlusion risk + a discontinuity intersecting a planned crop: `do-not-merge-across-depth-boundary`.
- Low occlusion risk + `subject_depth_uniformity >= 0.82`: `broad-merge-safe` is only a hint; it does not force a merge.
- Otherwise: `neutral`.

This keeps depth useful without increasing the normal 0–3 patch envelope merely because a new model signal exists.

## Quality review

When a region carries an active `depth_guard`, visually reject a result that:

- moves a foreground object behind the subject;
- reveals anatomy/garment surfaces that were genuinely occluded;
- erases a legitimate foreground crossing;
- changes hand/prop front-back ordering;
- creates a local blur transition inconsistent with the requested focus plane.

Depth disagreement is a warning, not proof. When depth conflicts with visible SOURCE MASTER evidence, the source photograph wins.
