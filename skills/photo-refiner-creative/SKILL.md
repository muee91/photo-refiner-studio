---
name: photo-refiner-creative
description: Execute an explicitly selected bundled Starryear creative translation recipe inside Photo Refiner Studio while preserving source identity, spatial structure, recipe fidelity, and the core Photo Refiner evidence/HD contract.
---

# Photo Refiner Creative

This is the companion creative skill for the **Photo Refiner Studio** plugin. It runs only after Studio or an explicit text fallback has selected a creative recipe. It is not a standalone generic image-style skill.

The core `photo-refiner` skill owns job initialization, source/LOOK authority, deterministic HD recovery, patch observation, registration/blending, and final delivery evidence. This skill owns recipe interpretation and creative-stage authority.

Resolve paths relative to this skill as `CREATIVE_SKILL_ROOT`. The sibling core skill is `../photo-refiner`; resolve it as `CORE_SKILL_ROOT` when a core script is required.

## 1. Entry contract

Enter only when the frozen job has:

```text
execution_mode: creative-translation
creative_recipe: <explicit recipe id>
```

Never infer a recipe from aesthetics alone. Never revive a previously selected recipe for a new job.

Read:

1. `references/starryear/catalog.md` and `references/starryear/catalog.json`;
2. the selected catalog entry;
3. the selected `recipePath/SKILL.md` completely;
4. every prompt/reference/script explicitly required by that recipe.

Validate source count before generation. If the recipe and frozen confirmation disagree, stop rather than silently adapting the recipe.

## 2. Recipe fidelity

A recipe is a creative transformation specification, not a normal color preset.

Do not flatten recipe semantics into the upstream Photo Refiner preset. The frozen normal preset remains an upstream visual direction; the recipe supplies theme, visual grammar, layout logic, source-derived motifs, and creative transformation.

Effect/preview images are **selection aids only**. Never copy their people, places, text, exact composition, or unrelated palette into the user's result. If a preview is missing, report that state honestly.

## 3. Creative execution modes

### `direct-effect` — default

Generate one complete creative effect image.

- Use the actual user source as identity/geometry reference.
- Use the frozen Photo Refiner look direction deliberately; do not reduce the recipe to a filter.
- Do not attach an unchanged source-evidence strip or place the original beside/below the artwork unless the recipe explicitly requires original assembly and that mode was selected.
- For single-source direct-effect, the confirmed panel aspect ratio owns the creative canvas. `original` means the source photograph's own aspect.

### `original-assembly` — explicit alternative

Follow the selected recipe literally.

- Preserve source-evidence areas with actual source pixels.
- Generate only translated/generated regions.
- Use the recipe compositor/layout rules.
- Do not run ordinary Photo Refiner local patches across mixed evidence/generated/layout boundaries.

Multi-source creative recipes keep the recipe's documented output structure.

## 4. Upstream binding

### `direction-only`

The creative pass starts from the source photograph plus the frozen normal preset direction.

### `look-master`

First produce and approve the normal Photo Refiner main image. The creative pass uses:

- SOURCE MASTER for identity, anatomy, factual geometry and source motifs;
- approved normal LOOK MASTER only as look reference;
- selected recipe for creative grammar.

### `hd-master`

This is the strictest chain and is always preview-first:

```text
source
-> normal Photo Refiner LOOK MASTER approval
-> core honest HD recovery
-> approved HD master
-> creative draft
-> creative draft approval
-> style-faithful tile redraw to delivery canvas
-> core delivery gate
```

The creative draft is not final delivery evidence. Final tiled redraw must use the core skill's tile observation + audited blend chain.

## 5. Creative authorities

For eligible single-source direct-effect work:

- **SOURCE MASTER** — identity, anatomy, factual geometry, garment/object construction, authentic source relationships.
- **CREATIVE LOOK MASTER** — approved complete creative image; owns color, lighting, tone, materials, visual grammar and approved transformations.
- **CREATIVE DETAIL PATCH** — registered local mid/high-frequency recovery only; may not turn the result back into ordinary photography or invent a second style.

For `hd-master`:

- stage 1: core SOURCE / LOOK / DETAIL authorities build the photographic HD master;
- stage 2: HD MASTER owns identity/structure/detail reference while CREATIVE DRAFT owns creative grammar;
- stage 3: CREATIVE DRAFT is style authority, HD MASTER is structure authority, tile redraw supplies delivery-resolution detail.

## 6. Preview and retry discipline

Default to preview-first.

For a direct-effect creative result, show the complete creative preview. If the job is preview-first, stop until the user approves it. For `hd-master`, approval of both the normal HD master and creative draft is mandatory; one-click is invalid.

Review before approval:

- identity and source relationships remain recognizable where the recipe intends them to remain;
- recipe visual grammar is actually present;
- there are no accidental extra people/limbs/objects;
- foreground/background ordering and important occlusions are preserved unless transformation explicitly changes them;
- text/logo elements are only present when the selected recipe requires them;
- the result is one coherent creative image rather than an unintended collage.

Retry only the failed generated unit:

- direct-effect: regenerate the complete creative image;
- original-assembly: regenerate only failed generated regions;
- hd-master tile redraw: retry only the failing tile from the clean prior composite.

Never build on a rejected creative composite.

## 7. Optional depth prior

When creative spatial reconstruction, overlapping subjects, foreground crossings, haze, or depth-of-field matter, use the core Vision `depth_prior` contract as an advisory spatial guard.

Depth may protect front/back ordering and prevent unsafe broad merges. It may not invent metric distance, override SOURCE MASTER, or increase patch quota by itself.

## 8. HD continuation for direct-effect

After a single-source direct-effect creative preview is approved, it becomes CREATIVE LOOK MASTER and returns to the core Photo Refiner HD pipeline:

```bash
python3 "$CORE_SKILL_ROOT/scripts/prepare_hd_working_canvas.py" <job.json> \
  --input <creative-look-master> \
  --output <job-dir>/intermediates/hd-working.png
```

Use the core planner with `creative-safe` recovery where eligible. The creative look owns low-frequency appearance; SOURCE MASTER remains identity/structure reference. Do not run the ordinary photographic recovery profile over creative artwork.

If the honest delivery target requires full-canvas redraw, combine subject-aware planning with complete coverage exactly as specified by the core skill. The returned tile images must be observed, registered, blended and hash-chained before delivery.

## 9. Original-assembly / multi-source delivery

Do not use ordinary local recovery across assembled mixed-ownership canvases.

Instead:

- keep unchanged source-evidence panels at source-derived resolution;
- generate each translated panel at the highest honest client-returned resolution available;
- preserve ownership per panel;
- perform recipe-defined deterministic assembly at the final canvas;
- use the core delivery gate only when its evidence contract is applicable to the assembled output.

Never label a simple interpolation of generated panels as recovered detail.

## 10. Completion

Creative work is complete only when:

- the selected recipe and assembly mode match the frozen confirmation;
- required preview checkpoints are approved;
- the final creative image preserves its authority model;
- any eligible HD patch/tile work has real returned-image observations and audited blend receipts;
- the core `delivery_gate.py` passes where required;
- `job.json` records the exact final master and evidence chain.
