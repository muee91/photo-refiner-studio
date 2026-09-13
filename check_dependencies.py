#!/usr/bin/env python3
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "skill" / "scripts" / "check_dependencies.py"

if not TARGET.is_file():
    raise SystemExit(f"Dependency checker is missing: {TARGET}")

runpy.run_path(str(TARGET), run_name="__main__")
