# Photo Refiner Studio

Private source repository for the Photo Refiner Codex skill and its interactive MCP settings plugin.

## Layout

- `skill/` — Photo Refiner v2.2 skill, references, scripts, and tests.
- `plugin/` — stable interactive settings panel and MCP server.
- `check_dependencies.py` — canonical project-root dependency-check entrypoint.

## Dependency check

Run from the repository root:

```bash
python3 check_dependencies.py
```

It verifies Pillow + ImageCms/LittleCMS, NumPy, PyYAML, OpenCV, and SIFT support. It does not install packages.

## Validation

```bash
python3 check_dependencies.py
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skill
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugin
python3 -m unittest discover -s skill/tests
HOME="$(mktemp -d)" node plugin/tests/plugin_smoke.cjs
```

The plugin/MCP/widget loading chain is intentionally frozen to the last known working implementation. v2.2 algorithm changes live under `skill/` and must not rewrite the panel loading architecture.
