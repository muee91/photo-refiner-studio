# Photo Refiner Studio architecture — 2026

This document records the intended architecture for the ChatGPT-native Photo Refiner project after the 2026 ChatGPT platform changes.

The core principle is unchanged:

> ChatGPT Images owns image generation/editing. Photo Refiner owns intent, planning, evidence, quality gates, deterministic local operations, and review checkpoints.

Do not rebuild capabilities the ChatGPT client already provides well.

## 1. Product surfaces

Photo Refiner is one workflow exposed through multiple ChatGPT surfaces, not separate products.

- **Chat** — fastest interactive photo conversation, single-image review, iterative feedback.
- **Work** — longer multi-step jobs, local-file access on desktop, browser/app work, batch/research-heavy workflows, finished deliverables.
- **Codex** — repository maintenance, tests, scripts, plugin packaging, local developer workflows.
- **Voice** — optional control surface for opening the workflow, reviewing checkpoints, changing settings, and directing Work/Codex; never a separate image pipeline.

Surface selection must not change the image-authority model or quality contract.

## 2. Universal plugin package

Target package shape:

```text
photo-refiner-studio/
├─ plugin.json                  # target Agent Plugins manifest
├─ skills/
│  └─ photo-refiner/            # reusable workflow instructions/resources
├─ mcp.json                     # Studio/settings tools when MCP is needed
├─ plugin/                      # current compatibility package/UI/server
├─ skill/                       # current source-of-truth skill during migration
├─ hooks/                       # optional runtime hooks only when genuinely useful
└─ distribution/
```

The current `.codex-plugin/plugin.json` remains a compatibility path. Do not remove it until the target root manifest has been validated in the actual ChatGPT/Codex environments used by the project.

A plugin is the product identity. Skills and MCP are implementation capabilities inside that plugin, not competing architectures.

## 3. Orchestration layer

The Skill is the workflow router. It decides:

1. whether the user is asking for editing or only asking about the tool;
2. source/subject routing;
3. Studio confirmation and frozen configuration;
4. normal vs creative translation;
5. preview/review checkpoints;
6. HD working-canvas route;
7. detail/tile generation plan;
8. quality/retry/delivery state.

The Skill should remain declarative where possible. Stable numeric and file-integrity rules belong in scripts, not prose.

## 4. Generation provider layer

**ChatGPT Images is the default rendering provider.**

Photo Refiner must not assume API image limits are the ChatGPT client's limits. Runtime observations remain the authority for returned patch dimensions.

The provider owns:

- complete base image edits;
- localized patch/tile generation;
- creative translations;
- image-model fidelity improvements that arrive in ChatGPT over time.

The project owns:

- prompt authority separation (SOURCE / LOOK / DETAIL);
- crop occupancy and Pixel Budget;
- returned-image observation;
- registration and deterministic blending;
- delivery proof.

As the built-in image model improves, prefer **fewer broader edits plus quality checkpoints** rather than increasing patch count.

## 5. Optional perception priors

Perception signals are adapters, not authorities.

### Vision regions

Required only when planning needs subject/face/hand/prop structure.

### Relative depth prior

Optional and auto-triggered only for occlusion, depth-of-field, atmospheric perspective, overlapping subjects, or creative spatial reconstruction.

Default implementation is a coarse `vision-relative` prior from the active multimodal model. A future dense-depth backend can emit the same stable contract.

Depth never:

- becomes metric truth;
- increases patch quota by itself;
- overrides SOURCE MASTER;
- creates a mandatory heavy-model dependency.

### Facial landmarks

Optional strict identity gate when reliable landmarks are already available.

These priors should converge into stable JSON contracts before the deterministic planner/gates consume them.

## 6. Deterministic execution layer

Keep deterministic scripts for tasks where evidence and repeatability matter:

- job/confirmation contract;
- HD working-canvas routing;
- Pixel Budget;
- detail/tile planning;
- returned patch observation;
- depth-plan annotation;
- registration;
- multiband blend;
- delivery gate;
- file/hash receipts.

This layer should not call an image-generation API merely to duplicate ChatGPT's built-in generator.

## 7. Evidence ledger

`job.json` remains the source of execution truth.

It should answer:

- what the user confirmed;
- which image became SOURCE / LOOK / CREATIVE LOOK authority;
- which generated bitmap was actually returned;
- which plan/hash a patch belongs to;
- whether each patch/tile passed its budget;
- how it was registered/blended;
- which exact composite became the delivered master.

A plan is not execution evidence. A requested resolution is not returned resolution. A large file is not proof of recovered information.

## 8. Studio UI

Studio should remain a **small decision surface**, not expose every backend capability.

Keep visible:

- look/preset and strength;
- creative recipe when wanted;
- preview vs one-click where safe;
- delivery target;
- professional controls only on demand.

Keep hidden/automatic:

- depth prior;
- patch count selection;
- observed client patch cap;
- Pixel Budget math;
- HD route selection;
- registration model;
- blend receipts;
- retry mechanics.

Review checkpoints are more valuable than adding more tuning controls.

## 9. MCP and hosting boundary

MCP is useful for the Studio/settings interaction and external actions. It should not become the sole runtime for local image files.

A hosted MCP/plugin can expose UI, configuration, catalogs, or cloud-safe tools. Local photo processing still requires a runtime with access to the source files and deterministic scripts.

Therefore keep an explicit split:

```text
cloud-safe plugin capability
  settings / catalogs / lightweight tools

local runtime capability
  source files / crops / upscaler / registration / blend / evidence
```

Do not assume installing a web-hosted plugin deploys local scripts.

## 10. Work and Cloud Browser

Use Work when a task benefits from long-running multi-step execution, local desktop files, or browser/app operations. Do not move the core edit pipeline into browser automation.

Cloud Browser is useful for reference/research/asset retrieval or supported signed-in web workflows; it is not a replacement for the local evidence pipeline.

## 11. Hooks and events

Lifecycle hooks are appropriate only for deterministic developer/runtime setup, such as dependency checks or validation in an execution environment that actually has the scripts.

MCP event subscriptions are not currently core to photo refinement. Reconsider only for future watched folders, review queues, remote batch jobs, or asynchronous asset pipelines.

## 12. Migration priorities

### P0 — keep now

- ChatGPT Images as renderer.
- Skill as orchestrator.
- Studio plugin as confirmation UI.
- deterministic HD/patch/evidence pipeline.
- review checkpoints from the latest main branch.
- optional depth prior as a hidden spatial guard.

### P1 — architecture update

- add/validate a root Agent Plugins `plugin.json` while retaining `.codex-plugin/plugin.json` compatibility;
- package Skill + MCP under one universal plugin identity;
- formalize capability discovery so Chat, Work and Codex can choose the same workflow without surface-specific forks;
- keep local vs cloud runtime capabilities explicit.

### P2 — only when evidence justifies it

- dense depth backend;
- plugin lifecycle hooks;
- hosted MCP/Sites deployment;
- MCP events / watched-folder automation;
- specialized segmentation backends.

None of P2 should become a mandatory dependency for ordinary single-image refinement.

## 13. Anti-duplication rules

Do not build:

- an in-project browser;
- a separate voice stack;
- a second image-generation service by default;
- a custom task scheduler for ChatGPT Work jobs;
- a custom selection editor merely because ChatGPT Images already offers region editing;
- a dense-depth model in the default path without measured quality benefit;
- a second settings product beside the plugin UI.

The project should specialize in what ChatGPT does **not** provide automatically: photographic authority, high-resolution honesty, patch economics, spatial safety, reproducible evidence, and review/retry discipline.
