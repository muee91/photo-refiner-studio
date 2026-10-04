# Photo Refiner Studio architecture

Photo Refiner Studio is one **portable Agent Plugin**. Chat, Work, Voice and Codex are entry surfaces for one product; they do not own separate photo pipelines.

The architecture follows one rule:

> ChatGPT provides general reasoning, multimodal understanding and image rendering. Photo Refiner adds photographic authority, deterministic workflow control, source-backed original-resolution delivery, durable review/resume state, per-frame batch isolation, spatial safety and auditable evidence.

## 1. Product layers

```text
Chat / Work / Voice / Codex
          │
          ▼
Photo Refiner Studio (intent + settings)
          │
          ├──────────────┐
          ▼              ▼
Settings MCP       Workflow MCP
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       Review / Resume UI      Workflow Controller
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
                ChatGPT Images / vision      deterministic scripts
                         │                         │
                         └────────────┬────────────┘
                                      ▼
                                   job.json
                                      │
                                      ▼
                               auditable delivery
```

The model does not reconstruct the state machine from prose after each turn. Conversation memory is never the authoritative workflow store.

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
│  ├─ server.cjs       # settings/confirmation
│  └─ workflow.cjs     # review/recent jobs/resume
├─ assets/
│  ├─ settings.html
│  ├─ review.html
│  └─ recent-jobs.html
├─ config/
├─ catalog/
├─ scripts/
├─ tests/
├─ .github/workflows/
└─ distribution/
```

`plugin.json` is the portable identity. `.codex-plugin/plugin.json` is the OpenAI presentation overlay, not a second product. Both package versions must remain aligned.

Current plugin package: **1.3.0**. Current photo-processing contract: **2.4**.

## 3. Responsibility split

### Settings Studio / `photoRefinerStudio`

Owns photographer intent and frozen confirmation:

- preset/look and strength;
- creative recipe when wanted;
- delivery/review mode;
- delivery target;
- professional controls on demand;
- persistent preferences/catalogs.

It must not expose patch counts, Pixel Budget math, HD route names, registration models or blend receipts as ordinary user decisions.

### Workflow MCP / `photoRefinerWorkflow`

Owns durable workflow UX, not photo-processing logic:

- register newly initialized parent jobs;
- open button-based review cards;
- turn explicit review buttons into semantic controller events;
- keep a small recent-job index under plugin-owned persistent state;
- resume by re-reading live `job.json` and asking the controller for the unique next action.

The recent-job index is only a discovery index. It must never become a second state machine.

### Workflow Controller

`skills/photo-refiner/scripts/workflow_controller.py` owns execution order.

After initialization and every state-changing action, call the controller. It returns one semantic `next_action` plus a user-safe `visible_status`.

Semantic events remain:

- `approve` / `continue`;
- `redo`;
- `adjust`.

Visual clients should normally submit these through the Review Widget. Voice may map natural language to the same events. The controller never invents approval.

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
- SHA256 execution receipts;
- per-frame batch job materialization and synchronization.

## 4. Photographic authority

Ordinary single-image refinement has three authorities:

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

## 6. Review UI, not chat commands

Preferred loop:

```text
full base edit
→ show exact bitmap
→ Review Widget: continue / redo / adjust
→ exact bitmap approval is recorded
→ HD route
→ only necessary local recovery
→ delivery gate
```

The user should not need to type magic commands such as “继续” or “重做主图”. A review button is an explicit action and maps to the same controller semantics.

Never repair a globally failed base by stacking patches onto it. `redo` starts from the previous clean authority.

## 7. Durable Resume

`job.json` is durable workflow truth.

The workflow MCP stores only a small recent-job registry pointing at parent `job.json` files. Resume performs:

```text
recent-job index
→ choose job
→ read live job.json
→ Workflow Controller inspect
→ unique next action
```

It must not:

- recreate settings already frozen;
- regenerate a completed stage merely because the chat is new;
- reconstruct progress from conversation history;
- register every batch child as a separate recent job.

Completed jobs may be reopened for inspection without silently returning to generation.

## 8. Batch authority: shared style, isolated facts

Ordinary batches are a parent + child-frame graph.

```text
Batch parent
├─ frozen settings / resolved prompt
├─ approved style master
│    owns: color / light / tone / atmosphere / retouch character / grain
│    does NOT own: identity / pose / anatomy / geometry / garment facts / frame texture
├─ Frame 01 child
│    └─ SOURCE 01 → LOOK 01 → own HD/patch/gate
├─ Frame 02 child
│    └─ SOURCE 02 → LOOK 02 → own HD/patch/gate
└─ ...
```

`bind_batch_master.py` freezes the approved style master as appearance-only authority. `batch_frames.py --materialize` creates one single-image child job per source. Each child reuses the mature single-image pipeline rather than inventing a second batch renderer.

A failed child is retried as a new child attempt. It must never borrow another frame's face, pose, garment geometry or patch evidence.

The parent reaches `completed` only after every child has independently passed its own delivery gate.

## 9. Perception adapters

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

## 10. Evidence ledger

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

Batch child jobs additionally record parent path, frame index, source authority, shared style authority and attempt number.

A plan is not execution evidence. Requested resolution is not returned resolution. File size is not proof of new information.

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

- core unit tests, including workflow/batch authority;
- creative contract;
- HD route contract;
- settings MCP contract;
- workflow MCP review/resume contract;
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
- a second workflow state machine outside `job.json` + Workflow Controller.

Photo Refiner differentiates on photographic authority, source-backed original-resolution delivery, per-frame batch isolation, durable review/resume state, spatial safety, patch economics, deterministic workflow control, auditable execution and review/retry discipline.
