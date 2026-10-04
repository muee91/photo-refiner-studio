#!/usr/bin/env python3
"""Cross-layer regression checks for the user-facing HD workflow contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "skills" / "photo-refiner" / "SKILL.md").read_text(encoding="utf-8")
SCHEMA = (ROOT / "skills" / "photo-refiner" / "references" / "config-schema.md").read_text(encoding="utf-8")
CONTROLLER = (ROOT / "skills" / "photo-refiner" / "scripts" / "workflow_controller.py").read_text(encoding="utf-8")
PREP = (ROOT / "skills" / "photo-refiner" / "scripts" / "prepare_hd_working_canvas.py").read_text(encoding="utf-8")

ROUTES = [
    "native-detail",
    "source-backed-detail",
    "ultrasharp-detail",
    "full-canvas-tile-redraw",
]

for route in ROUTES:
    for label, content in (("SKILL", SKILL), ("schema", SCHEMA), ("controller", CONTROLLER), ("HD router", PREP)):
        if route not in content:
            raise SystemExit(f"{label} is missing canonical HD route {route}")

# Ordinary source-width photography must suppress raw tiling consent as a data
# contract, not merely contain a particular English/Chinese sentence shape.
if "source-backed" not in SKILL.lower() or "source-backed" not in SCHEMA.lower():
    raise SystemExit("source-backed original-resolution delivery is missing from the documented contract")
if "consent_prompt" not in SKILL or "user_confirmation_required = false" not in SKILL or "quoted to the user" not in SKILL:
    raise SystemExit("SKILL no longer suppresses raw source-backed consent prompts")
if "user_confirmation_required: false" not in SCHEMA:
    raise SystemExit("schema no longer records source-backed tiling as non-interactive")
if "estimated_generation_calls: 0" not in SCHEMA:
    raise SystemExit("schema no longer normalizes source-backed full-frame generation pressure")
if "not a user decision" not in SCHEMA.lower() and "not user choices" not in SCHEMA.lower():
    raise SystemExit("schema no longer states that raw patch/tile economics stay internal")

# Controller owns semantic review events rather than inventing approval.
for event in ("approve", "continue", "redo", "adjust"):
    if f'"{event}"' not in CONTROLLER:
        raise SystemExit(f"workflow controller is missing semantic event {event}")

if "user_facing_policy" not in CONTROLLER or "hide-internal-route-and-patch-economics" not in CONTROLLER:
    raise SystemExit("workflow controller no longer normalizes the hidden-engineering policy")
if "apply_source_backing" not in CONTROLLER:
    raise SystemExit("workflow controller no longer normalizes source-backed raw plans before execution")

print("HD route contract OK")
