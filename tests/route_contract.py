#!/usr/bin/env python3
"""Cross-layer regression checks for the user-facing HD workflow contract."""

from pathlib import Path
import re

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

# Ordinary source-width photography must explicitly suppress raw tiling consent.
for label, content in (("SKILL", SKILL), ("schema", SCHEMA)):
    if "source-backed" not in content.lower():
        raise SystemExit(f"{label} does not describe source-backed delivery")
    if not re.search(r"(must not|never|不得|不应|不能).{0,120}(tile|tiling|分块)", content, flags=re.I | re.S):
        raise SystemExit(f"{label} does not explicitly hide ordinary source-backed tiling decisions from users")

# Controller must own semantic review events rather than inventing approval.
for event in ("approve", "continue", "redo", "adjust"):
    if f'"{event}"' not in CONTROLLER:
        raise SystemExit(f"workflow controller is missing semantic event {event}")

if "user_facing_policy" not in CONTROLLER or "hide-internal-route-and-patch-economics" not in CONTROLLER:
    raise SystemExit("workflow controller no longer normalizes the hidden-engineering policy")

print("HD route contract OK")
