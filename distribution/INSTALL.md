# Clean reinstall — Photo Refiner Studio 1.x

Photo Refiner Studio 1.x is a breaking packaging redesign. Do **not** install it on top of the old two-directory `photo-refiner` + `photo-refiner-studio` layout.

## 1. Remove the old installation

Uninstall the existing Photo Refiner / Photo Refiner Studio plugin from the ChatGPT/Codex Plugin Directory or remove the old local marketplace entry you previously used.

If you manually copied old folders, remove those old copies before reinstalling. The new package is one plugin root.

Old preference/confirmation state under `~/.codex/photo-refiner` is not part of the 1.x runtime. New Studio state is host-scoped under `${PLUGIN_DATA}`.

## 2. Validate the new repository

From the repository root:

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

## 3. Build one portable package

```bash
python3 distribution/build_plugin.py --zip
```

Output:

```text
dist/
├─ photo-refiner-studio-1.0.0/
└─ photo-refiner-studio-1.0.0.zip
```

The ZIP contains one plugin root with `plugin.json`, `mcp.json`, both skills, Studio MCP/UI, presets, and compiled creative catalogs. Repository tests, raw preview sources, and maintenance scripts are intentionally excluded.

## 4. Install

Install the repository root or generated ZIP through the Plugin Directory / local plugin source used by your ChatGPT or Codex environment.

The root `plugin.json` is the portable identity. The bundled `mcp.json` declares the local stdio Studio server. No separate Skill installation is required.

After installing or updating, start a **new chat/session** so the host reloads skills, MCP tools, UI resources, and versioned widget metadata.

## 5. First functional test

Use a normal source photo and ask:

> 用 Photo Refiner 修这张照片

Expected behavior:

1. Photo Refiner Studio opens;
2. Studio submission returns a schema-4 confirmation;
3. normal jobs route through the `photo-refiner` skill;
4. creative recipes remain opt-in;
5. selecting a recipe activates the companion `photo-refiner-creative` skill;
6. HD recovery uses actual client-returned patch observations and fail-closed delivery evidence;
7. depth remains an automatic advisory spatial guard, not a mandatory heavy-model stage.

## Upgrade rule going forward

- bump root/overlay **Plugin version** for package/UI/MCP changes;
- bump **Photo-processing contract version** only when deterministic image-processing rules change;
- never reintroduce separate `skill/` and `plugin/` install roots;
- keep creative recipe growth isolated from the ordinary core skill.
