# Photo Refiner Studio

Private source repository for the Photo Refiner Codex skill and its interactive MCP settings plugin.

## Layout

- `skill/` — reusable `photo-refiner` skill, references, scripts, and tests.
- `plugin/` — `photo-refiner-studio` plugin, settings panel, MCP server, presets, and smoke test.

## Validation

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skill
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugin
python3 -m unittest discover -s skill/tests
HOME="$(mktemp -d)" node plugin/tests/plugin_smoke.cjs
```

The repository intentionally excludes user preferences, confirmation records, generated jobs, outputs, caches, and source photographs.
