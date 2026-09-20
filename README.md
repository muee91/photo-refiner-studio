# Photo Refiner Flow

Private source repository branch for the independently installable **Photo Refiner Flow** node-workflow skill and MCP Apps UI.

Photo Refiner Flow is designed to coexist with the original **Photo Refiner**. It uses separate Skill/plugin identities, MCP tool names, and local state directories.

## Installed identities

- Skill: `photo-refiner-flow`
- Plugin: `photo-refiner-flow-studio`
- MCP server: `photoRefinerFlowStudio`
- State: `~/.codex/photo-refiner-flow/`

## Workflow

```text
Source → Look A → Effect B? → Approval → Recovery? → Delivery
```

## Repository layout

- `skill/` — Flow skill runtime, graph compiler, refinement scripts, references, and tests.
- `plugin/` — Flow MCP Apps plugin and embedded node canvas.
- `node-canvas/` — standalone development preview of the same canvas UI.
- `distribution/` — coexistence-safe installer and install instructions.

## Validation

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skill
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugin
python3 -m unittest discover -s skill/tests
HOME="$(mktemp -d)" node plugin/tests/plugin_smoke.cjs
```

The repository intentionally excludes user preferences, graph confirmations, generated jobs, outputs, caches, and source photographs.
