# Photo Refiner Studio architecture

Photo Refiner Studio is one **portable Agent Plugin**. Chat, Work, Voice and Codex are entry surfaces for one product; they do not own separate photo pipelines.

The architecture follows one rule:

> ChatGPT provides general reasoning, multimodal understanding and image rendering. Photo Refiner adds photographic authority, deterministic workflow control, source-backed original-resolution delivery, spatial safety, evidence, and review discipline.

## 1. Product layers

```text
Chat / Work / Voice / Codex
          │
          ▼
Photo Refiner Studio (intent + settings)
          │
          ▼
Workflow Controller (one deterministic next action)
          │
          ├─ ChatGPT Images / multimodal perception
          │
          └─ deterministic local scripts
                    │
                    ▼
                 job.json
                    │
                    ▼
             auditable delivery
```

The model does not reconstruct the state machine from prose after each turn.

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
├─ catalog/
├─ scripts/
├─ tests/
├─ .github/workflows/
└─ distribution/
```

`plugin.json` is the portable identity. `.codex-plugin/plugin.json` is the OpenAI presentation overlay, not a second product. Both package versions must remain aligned.

Current plugin package: **1.2.0**. Current photo-processing contract: **2.4**.

## 3. Responsibility split

### Studio / MCP

Owns only photographer decisions and confirmation:

- preset/look and strength;
- creative recipe when wanted;
- review mode;
- delivery target;
- professional controls on demand;
- persistent preferences/catalogs.

Studio must not expose internal patch counts, Pixel Budget math, HD route names, registration models, or blend receipts as normal user decisions.

### Workflow Controller

`skills/photo-refiner/scripts/workflow_controller.py` owns execution order.

After initialization and after every state-changing action, call the controller. It returns one semantic `next_action` plus a user-safe `visible_status`.

Semantic user events are:

- `approve` / `continue`;
- `redo`;
- `adjust`.

The controller never invents approval; approval still binds the exact displayed bitmap through `update_job.py`.

### ChatGPT Images / perception

Owns:

- complete base edits;
- localized patch/tile generation;
- creative translations;
- coarse multimodal scene understanding;
- future renderer fidelity improvements.

Photo Refiner does not call another image-generation API merely to recreate ChatGPT's built-in renderer.

### Deterministic local core

Owns:

- source normalization;
- confirmation/job contracts;
- HD working-canvas routing;
- source-backed detail lifting;
- pinned 4X information boundary;
- Pixel Budget;
- optional depth-plan annotation;
- detail/tile planning;
- actual patch observation;
- registration;
- blending;
- delivery gate;
- SHA256 execution receipts.

## 4. Photographic authority

Ordinary refinement has three authorities:

- **SOURCE MASTER** — identity, anatomy, factual geometry, construction, authentic texture, source-resolution high-frequency detail.
- **LOOK MASTER** — approved color, lighting, tone, atmosphere and visual style.
- **DETAIL PATCH** — localized registered detail only.

A smaller LOOK MASTER does not erase the source photograph's real high-resolution information.

## 5. Original-resolution delivery

The normal HD routes are:

```text
native-detail
source-backed-detail
ultrasharp-detail
full-canvas-tile-redraw
```

### Source-backed is the default photographic path

For ordinary single-source, original-framing, `source-width` photography, SOURCE MASTER supplies source-resolution high-frequency detail while LOOK MASTER supplies the approved appearance.

Example:

```text
SOURCE MASTER 4672×7008
LOOK MASTER   1024×1536
        ↓
source-backed-detail
        ↓
4672×7008 working/delivery canvas
        ↓
only valuable local patches when needed
```

A raw planner estimate such as `22 tiles` is not a user decision for this path. `apply_source_backing.py` converts that pressure into explicit SOURCE MASTER retention.

### Full-canvas redraw is exceptional

Use it for canvases SOURCE MASTER cannot honestly back:

- creative full-frame reconstruction;
- generated/synthetic panels;
- newly invented outpaint regions;
- changed framing that creates new pixels;
- explicit fully regenerated native-resolution creative output.

## 6. Review-first, not patch-first

As ChatGPT Images improves, Photo Refiner should generate fewer patches.

Preferred loop:

```text
full base edit
→ review/quality checkpoint
→ approve or regenerate base
→ HD route
→ only necessary high-value local recovery
→ delivery gate
```

Never repair a globally failed base by stacking local patches onto it.

The user-facing review choices should remain semantic: continue, redo, adjust settings. Engineering recovery details stay hidden unless requested.

## 7. Perception adapters

Perception is advisory, never an authority.

### Vision regions

Used for subject-aware planning of face/head/hands/garments/props/architecture.

### Relative depth prior

Enable only for occlusion, hand/prop ordering, depth-of-field, haze, overlapping subjects, or spatial creative reconstruction.

Depth may protect ordering and prevent unsafe broad merges. It may not:

- invent metric distance;
- override SOURCE MASTER;
- increase patch quota by itself;
- become a mandatory dense-depth dependency.

## 8. Evidence ledger

`job.json` is the execution source of truth. It must answer:

- what the user confirmed;
- which source files/hashes were used;
- which bitmap became LOOK/CREATIVE/HD authority;
- what dimensions the ChatGPT client actually returned;
- which plan/hash each patch or tile belongs to;
- whether selected regions passed Pixel Budget;
- how accepted patches were registered/blended;
- which exact composite became delivery master;
- which review checkpoints were approved;
- what deterministic next action is valid.

A plan is not execution evidence. Requested resolution is not returned resolution. File size is not proof of new information.

## 9. Batch model

A batch owns one shared approved look, but every frame owns its own SOURCE MASTER.

Do not model a batch as one multi-source synthetic canvas. Mature batch source-backing is per-frame:

```text
Batch Job
├─ shared approved look
├─ Frame 01 → SOURCE MASTER 01 → own HD/evidence path
├─ Frame 02 → SOURCE MASTER 02 → own HD/evidence path
└─ ...
```

## 10. Resume model

`job.json` is durable enough to resume after a new conversation or surface change. The controller should inspect durable state and return the unique next action rather than relying on chat history.

A future recent-job index under `${PLUGIN_DATA}` may improve discovery, but it must point to durable jobs instead of becoming a second state machine.

## 11. Platform boundaries

### Work

Use Work for long multi-photo execution, reference research, connected apps and deliverables. Do not create a competing background-task system.

### Voice

Voice maps natural language to the same controller events. Do not build a separate voice stack.

### Browser/computer use

Useful for references, briefs, assets and web workflows. Not a replacement for local source-file evidence, registration or blending.

### Hosted services

Catalog/update metadata may move to hosted services later. Original photos, local crops, registration, blending and evidence remain file-aware unless a hosted design can prove equivalent integrity.

## 12. CI and release discipline

`main` is validated by `.github/workflows/ci.yml`:

- core unit tests;
- creative contract;
- HD route contract;
- MCP plugin contract;
- Widget contract;
- portable layout contract;
- build validation.

CI uploads **no artifacts**, avoiding artifact-quota churn.

Any Studio/UI/MCP behavior change that can affect client caching must bump the plugin package version in both manifests. The photo-processing contract version changes only when the image-processing contract changes.

## 13. Anti-duplication rules

Do not build:

- a second image-generation backend by default;
- a custom browser;
- a custom voice system;
- a custom task scheduler for Work;
- a second settings product beside Studio;
- a dense-depth dependency without measured benefit;
- a separate workflow state machine outside `job.json` + Workflow Controller.

Photo Refiner differentiates on photographic authority, source-backed original-resolution delivery, spatial safety, patch economics, deterministic workflow control, auditable execution and review/retry discipline.
