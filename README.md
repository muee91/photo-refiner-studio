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

- `skills/photo-refiner/` — photographic refinement, review checkpoints, honest HD recovery, optional depth guards, patch/tile evidence, delivery gates.
- `skills/photo-refiner-creative/` — Starryear recipe interpretation and creative-stage authority. Loaded only after explicit recipe selection.
- `mcp/` + `assets/` — Photo Refiner Studio settings/confirmation UI.
- `config/` — compiled Studio preset and creative catalogs.
- `catalog/` — developer-only original recipe preview sources used to rebuild `config/`; not installed in the runtime plugin.

ChatGPT Images is the renderer. Photo Refiner owns what each generation is allowed to change and whether its returned pixels honestly support delivery.

## Plugin format

- root `plugin.json` — Agent Plugins 1.0.0 portable identity;
- root `mcp.json` — portable stdio Studio server;
- root `skills/` — auto-discovered plugin skills;
- `.codex-plugin/plugin.json` — OpenAI-specific listing/presentation overlay only. It does not define a second component graph.

The host provides `${PLUGIN_ROOT}` and `${PLUGIN_DATA}`. `mcp.json` scopes the Studio process' HOME to `${PLUGIN_DATA}`, so preferences, confirmations, and user preview overrides live in plugin-owned persistent state rather than the user's legacy install location.

## Versioning

Two independent axes:

- **Plugin package**: `1.0.0` — packaging/UI/MCP architecture.
- **Photo-processing contract**: `2.4` — `skills/photo-refiner/scripts/job_contract.py`.

Do not renumber the photo contract merely because the plugin package changes.

## Validation

Run from repository root:

```bash
python3 -m unittest discover -s skills/photo-refiner/tests
python3 tests/creative_contract.py
node tests/plugin_contract.cjs
node tests/widget_contract.cjs
python3 tests/portable_layout.py
python3 distribution/build_plugin.py --check
```

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

For a clean upgrade from the old two-directory layout, read `distribution/INSTALL.md`. See `ARCHITECTURE.md` for the design contract.
