# Photo Refiner Studio

Photo Refiner Studio is one **portable Agent Plugin** for ChatGPT and Codex.

The repository root is the plugin root. There is no separate Skill install and no nested plugin product.

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
├─ catalog/          # developer preview sources; excluded from runtime package
├─ scripts/          # catalog/preset maintenance; excluded from runtime package
├─ tests/            # plugin/cross-skill contracts
└─ distribution/
```

## Responsibilities

- `skills/photo-refiner/` — photographic refinement, deterministic workflow control, source-backed original-resolution delivery, optional depth guards, per-frame batch authority, patch/tile evidence, delivery gates.
- `skills/photo-refiner-creative/` — Starryear recipe interpretation and creative-stage authority. Loaded only after explicit recipe selection.
- `mcp/server.cjs` + `assets/settings.html` — Studio settings and frozen confirmation.
- `mcp/workflow.cjs` + review/recent-job widgets — button-based review, durable recent jobs and resume.
- `config/` — compiled Studio preset and creative catalogs.
- `catalog/` — developer-only original recipe preview sources used to rebuild `config/`; not installed in the runtime plugin.

ChatGPT Images is the renderer. Photo Refiner owns what each generation may change, what the next deterministic workflow action is, how batch frames remain isolated, and whether returned pixels honestly support delivery.

## Workflow model

The language model does not infer the pipeline from prose after every turn. After job initialization and after every state-changing action, use:

```bash
python3 skills/photo-refiner/scripts/workflow_controller.py <job.json>
```

It returns one semantic `next_action` and a user-safe `visible_status`.

Normal visual review is **button-based**. When the controller reaches a review checkpoint, the exact displayed bitmap is passed to `open_photo_refiner_review`; the user chooses continue / redo / adjust through the Review Widget. Approval binds that exact bitmap through `update_job.py` before the controller proceeds.

Recent jobs are durable. Register a newly initialized parent job with `register_photo_refiner_job`. When the user asks to continue/reopen work, `open_photo_refiner_recent_jobs` reads the persistent job index and `resume_photo_refiner_job` re-inspects the live `job.json`; completed stages are not regenerated just because the conversation changed.

Ordinary single-source + original-framing + `source-width` photography uses SOURCE MASTER-backed original-resolution delivery by default. Raw patch/tile economics are internal diagnostics and are not shown as user choices.

## Batch model

Ordinary batches use a parent + child-frame architecture:

```text
Batch parent
├─ shared frozen settings
├─ approved style master (appearance only)
├─ Frame 01 child → own SOURCE / LOOK / patches / delivery gate
├─ Frame 02 child → own SOURCE / LOOK / patches / delivery gate
└─ ...
```

The batch style master may share color, light, tone, atmosphere, retouch character and grain. It may **not** share identity, pose, anatomy, factual geometry, garment construction or frame-specific texture. A failed frame is retried as a new child attempt without borrowing artifacts from another photograph.

## Plugin format

- root `plugin.json` — Agent Plugins 1.0.0 portable identity;
- root `mcp.json` — portable stdio servers for settings and durable workflow UX;
- root `skills/` — auto-discovered plugin skills;
- `.codex-plugin/plugin.json` — OpenAI-specific listing/presentation overlay only. It does not define a second component graph.

The host provides `${PLUGIN_ROOT}` and `${PLUGIN_DATA}`. Both MCP processes scope HOME to `${PLUGIN_DATA}`, so settings, confirmations, preview overrides and the recent-job index live in plugin-owned persistent state.

## Versioning

Two independent axes:

- **Plugin package**: `1.3.0` — button review + resume/recent jobs + per-frame batch authority.
- **Photo-processing contract**: `2.4` — `skills/photo-refiner/scripts/job_contract.py`.

Do not renumber the photo contract merely because the plugin package changes.

## Validation

Run from repository root:

```bash
python3 -m unittest discover -s skills/photo-refiner/tests
python3 tests/creative_contract.py
python3 tests/route_contract.py
node tests/plugin_contract.cjs
node tests/workflow_plugin_contract.cjs
node tests/widget_contract.cjs
python3 tests/portable_layout.py
python3 distribution/build_plugin.py --check
```

The repository also contains a no-artifact GitHub Actions workflow that runs the same validation family on pushes to `main` and pull requests. It does not upload build artifacts.

Optional OpenAI validators, when installed:

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/photo-refiner
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/photo-refiner-creative
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
```

## Catalog maintenance

```bash
python3 scripts/sync_presets.py
python3 scripts/sync_creative_recipes.py
```

`sync_creative_recipes.py` reads recipe rules from `photo-refiner-creative` and original preview sources from `catalog/starryear/previews/`, then compiles the compact/runtime preview catalogs under `config/`.

## Build

```bash
python3 distribution/build_plugin.py --zip
```

Output is one portable plugin directory and one optional ZIP. Developer tests, raw preview sources, and repository-maintenance scripts are excluded from the installable runtime.

For a clean upgrade from the old two-directory layout, read `distribution/INSTALL.md`. See `ARCHITECTURE.md` and `skills/photo-refiner/references/config-schema.md` for the design/runtime contracts.
