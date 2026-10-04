# Photo Refiner Studio architecture

This repository is one **portable Agent Plugin**, not a Skill plus a separate plugin glued together.

The architecture follows one rule:

> ChatGPT provides the general agent surfaces and image renderer. Photo Refiner adds photographic authority, HD honesty, spatial safety, evidence, and review discipline.

## 1. Product boundary

One installed product: **Photo Refiner Studio**.

Supported surfaces are entry points, not separate implementations:

- **Chat** — single-image iteration and fast review.
- **Work** — long-running multi-file work, browser/reference gathering, connected apps, finished deliverables.
- **Voice** — control surface for the same plugin actions and review checkpoints.
- **Codex** — repository/runtime maintenance, local scripts, testing, packaging.

Do not fork the photo pipeline by surface.

## 2. Portable plugin layout

```text
photo-refiner-studio/
├─ plugin.json
├─ mcp.json
├─ .codex-plugin/plugin.json
├─ skills/
│  ├─ photo-refiner/
│  └─ photo-refiner-creative/
├─ mcp/
├─ assets/
├─ config/
├─ scripts/
├─ tests/
└─ distribution/
```

### Canonical identity

`plugin.json` is the Agent Plugins 1.0.0 portable identity.

### OpenAI presentation overlay

`.codex-plugin/plugin.json` is intentionally retained as the supported OpenAI-specific presentation overlay. It is not a second product and does not declare alternate Skill/MCP component paths. Root identity and root portable component discovery remain canonical.

### MCP

`mcp.json` is the portable MCP configuration. The bundled Studio server uses stdio and plugin-scoped `${PLUGIN_ROOT}` / `${PLUGIN_DATA}` semantics.

No legacy `.mcp.json` exists.

## 3. Skill split

### `photo-refiner`

Owns:

- edit intent gate;
- Studio confirmation;
- SOURCE / LOOK / DETAIL authority;
- base quality checkpoint;
- honest HD working canvas;
- empirical patch-cap calibration;
- Pixel Budget;
- optional relative-depth prior;
- detail/tile plans;
- actual returned-patch observations;
- registration / blending receipts;
- delivery gate;
- batch consistency and retry state.

This is the primary skill for ordinary photographic work.

### `photo-refiner-creative`

Owns:

- Starryear recipe resources;
- direct-effect vs original-assembly semantics;
- recipe source-count rules;
- creative preview checkpoint;
- creative authority model;
- direction-only / look-master / hd-master creative stages.

It is loaded only after the user explicitly selects a creative recipe. This keeps the core skill small and prevents creative catalog growth from bloating ordinary photo refinement.

## 4. Generation provider

**ChatGPT Images is the default renderer.**

Photo Refiner does not call an image-generation API simply to recreate ChatGPT's built-in image path.

The renderer owns:

- complete base edits;
- localized patch/tile generation;
- creative translations;
- future built-in fidelity improvements.

Photo Refiner owns:

- what each generated image is allowed to change;
- which image is the current authority;
- whether generation is needed at all;
- whether the returned bitmap contains enough useful detail for delivery.

## 5. Deterministic local core

The deterministic layer remains local/file-aware because it must inspect the real source and returned files:

- source normalization;
- job/confirmation contract;
- HD working-canvas routing;
- 4X-UltraSharp integrity and information boundary;
- Pixel Budget;
- depth-plan annotation;
- detail/tile planning;
- actual patch observation;
- registration;
- multiband blending;
- delivery gate;
- SHA256 execution receipts.

This layer belongs under the core skill's `scripts/`, not behind a second image service.

## 6. Evidence ledger

`job.json` is the execution source of truth.

It must answer:

- what the user confirmed;
- which source files and hashes were used;
- which bitmap became LOOK / CREATIVE LOOK / HD authority;
- the actual dimensions returned by the ChatGPT client;
- which plan/hash each patch or tile belongs to;
- whether each region passed its Pixel Budget;
- how patches were registered and blended;
- which exact composite became the delivered master;
- which review checkpoints were approved.

A plan is not execution evidence. Requested resolution is not returned resolution. File size is not proof of new information.

## 7. Review-first quality model

As ChatGPT Images improves, Photo Refiner should generate **fewer** local patches, not more.

The preferred loop is:

```text
full base edit
-> quality checkpoint
-> approve or regenerate base
-> HD route
-> only necessary high-value patches/tiles
-> delivery proof
```

Do not repair a globally failed base by stacking local patches onto it.

## 8. Perception adapters

Perception signals are advisory adapters, not authorities.

### Vision regions

Used only when subject-aware planning needs face/head/hand/garment/prop/architecture structure.

### Relative depth prior

Default implementation is coarse `vision-relative` depth from the active multimodal model. Enable only for occlusion, DOF, atmospheric perspective, overlapping subjects, or spatial creative reconstruction.

Depth may protect ordering and prevent unsafe broad merges. It may not:

- invent metric distance;
- override SOURCE MASTER;
- increase generation quota by itself;
- become a mandatory dense-depth dependency.

A future dense-depth backend must emit the same stable JSON contract so the planner does not care which perception provider produced it.

### Landmarks

Optional strict identity gate when reliable landmarks are already available.

## 9. Studio / MCP boundary

Studio is a small decision and confirmation surface.

Visible controls should remain limited to choices a photographer actually intends to make:

- look/preset and strength;
- creative recipe when wanted;
- preview/review mode;
- delivery target;
- professional controls on demand.

Keep automatic:

- patch count;
- empirical patch cap;
- Pixel Budget math;
- HD route;
- depth prior;
- registration model;
- blend receipts;
- retry bookkeeping.

The MCP server owns structured settings, confirmation, prompt library, recipe preview UI, and plugin-scoped preferences. It does not own the image-generation engine.

## 10. Persistent state

Portable hosts provide `${PLUGIN_DATA}`. `mcp.json` maps the Studio process' `HOME` into that persistent plugin-scoped directory so the existing settings server stores preferences, confirmations, and user preview overrides outside the immutable plugin package.

New architecture does not install state into the repository or depend on the user's old `~/.codex/photo-refiner` tree.

## 11. Work, Voice, and new ChatGPT capabilities

### Work

Use Work for long multi-step execution, many photos, reference research, browser/app work, and finished delivery. Do not create a custom background-task system for things Work already does.

### Voice

Voice can invoke plugins and can control the same semantic actions: open Studio, approve, redo, change look, retry, or continue. Do not build a separate voice stack.

### Cloud Browser / computer use

Useful for reference retrieval, customer briefs, assets, or web workflows. Not a replacement for source-file registration/blending/evidence.

### Plugin extensions

Sidebar apps, conversation panels, plugin settings, file viewers/editors, deep links, and richer forms are future UI opportunities. Adopt them only when they reduce workflow friction; do not move deterministic photo logic into UI components.

## 12. Cloud boundary

Current product remains local-file-first.

Cloud-safe capabilities:

- settings UI;
- preset/recipe catalogs;
- lightweight metadata;
- future hosted catalog/update services.

Local/file-aware capabilities:

- original photos;
- crops;
- upscaler;
- registration;
- blending;
- evidence ledger;
- final delivery files.

A future hosted MCP may complement the local stdio server, but must not silently replace local evidence with remote assumptions.

## 13. Versioning

Two independent version axes:

- **Plugin package version** — root `plugin.json` / OpenAI overlay, starting at `1.0.0` for the portable redesign.
- **Photo-processing contract version** — `skills/photo-refiner/scripts/job_contract.py`, currently `2.4`.

Do not force a plugin UI/package release to renumber the image-processing contract, and do not duplicate the Skill contract version in marketing copy.

## 14. Distribution

The repository root is directly installable as a plugin source.

`distribution/build_plugin.py` validates the portable layout and produces one installable runtime bundle. It excludes developer tests and repository-only maintenance files from the ZIP.

There is no separate Skill installer and no two-directory deployment.

## 15. Anti-duplication rules

Do not build:

- a second image-generation backend by default;
- a custom browser;
- a custom voice system;
- a custom task scheduler for Work jobs;
- a second settings product beside Studio;
- a dense-depth model in the default path without measured benefit;
- a custom selection editor just because ChatGPT Images already supports iterative edits.

The product differentiates on photographic authority, high-resolution honesty, spatial safety, patch economics, auditable execution, and review/retry discipline.
