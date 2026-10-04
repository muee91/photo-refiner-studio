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

- `skills/photo-refiner/` — photographic refinement, deterministic workflow control, review checkpoints, source-backed original-resolution delivery, optional depth guards, patch/tile evidence, delivery gates.
- `skills/photo-refiner-creative/` — Starryear recipe interpretation and creative-stage authority. Loaded only after explicit recipe selection.
- `mcp/` + `assets/` — Photo Refiner Studio settings/confirmation UI.
- `config/` — compiled Studio preset and creative catalogs.
- `catalog/` — developer-only original recipe preview sources used to rebuild `config/`; not installed in the runtime plugin.

ChatGPT Images is the renderer. Photo Refiner owns what each generation is allowed to change, what the next deterministic workflow action is, and whether returned pixels honestly support delivery.

## Workflow model

The language model does not infer the pipeline from prose after every turn. After job initialization and after every state-changing action, use:

```bash
python3 skills/photo-refiner/scripts/workflow_controller.py <job.json>
```

It returns one semantic `next_action` and a user-safe `visible_status`. Review events are `approve`, `continue`, `redo`, and `adjust`; approval still binds the exact displayed bitmap through `update_job.py`.

Ordinary single-source + original-framing + `source-width` photography uses SOURCE MASTER-backed original-resolution delivery by default. Raw patch/tile economics are internal diagnostics and are not shown as user choices.

## Plugin format

- root `plugin.json` — Agent Plugins 1.0.0 portable identity;
- root `mcp.json` — portable stdio Studio server;
- root `skills/` — auto-discovered plugin skills;
- `.codex-plugin/plugin.json` — OpenAI-specific listing/presentation overlay only. It does not define a second component graph.

The host provides `${PLUGIN_ROOT}` and `${PLUGIN_DATA}`. `mcp.json` scopes the Studio process' HOME to `${PLUGIN_DATA}`, so preferences, confirmations, and user preview overrides live in plugin-owned persistent state rather than a legacy install location.

## Versioning

Two independent axes:

- **Plugin package**: `1.2.0` — deterministic workflow controller + current Studio/MCP package.
- **Photo-processing contract**: `2.4` — `skills/photo-refiner/scripts/job_contract.py`.

Do not renumber the photo contract merely because the plugin package changes.

## Validation

Run from repository root:

```bash
python3 -m unittest discover -s skills/photo-refiner/tests
python3 tests/creative_contract.py
python3 tests/route_contract.py
node tests/plugin_contract.cjs
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
