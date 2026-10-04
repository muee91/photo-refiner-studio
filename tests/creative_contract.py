#!/usr/bin/env python3
"""Cross-skill creative catalog contract for Photo Refiner Studio 1.x."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "skills" / "photo-refiner"
CREATIVE = ROOT / "skills" / "photo-refiner-creative"
CORE_CATALOG = CORE / "references" / "starryear" / "catalog.json"
CREATIVE_CATALOG = CREATIVE / "references" / "starryear" / "catalog.json"
STUDIO_CATALOG = ROOT / "config" / "creative-recipes.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    core = json.loads(CORE_CATALOG.read_text(encoding="utf-8"))
    creative = json.loads(CREATIVE_CATALOG.read_text(encoding="utf-8"))
    studio = json.loads(STUDIO_CATALOG.read_text(encoding="utf-8"))

    require(core == creative, "core deterministic catalog and creative-skill catalog drifted")
    recipes = creative.get("recipes") or []
    require(len(recipes) == 15, f"expected 15 creative recipes, got {len(recipes)}")
    require(len({item["id"] for item in recipes}) == len(recipes), "creative recipe ids must be unique")

    studio_by_id = {item["id"]: item for item in (studio.get("recipes") or [])}
    require(set(studio_by_id) == {item["id"] for item in recipes}, "Studio compiled catalog ids drifted from recipe source catalog")

    missing_preview = []
    for recipe in recipes:
        source_count = recipe["sourceCount"]
        require(source_count["min"] >= 1, f"{recipe['id']} sourceCount.min must be >= 1")
        require(source_count["max"] >= source_count["min"], f"{recipe['id']} source count range is inverted")

        recipe_root = CREATIVE_CATALOG.parent / recipe["recipePath"]
        skill_path = recipe_root / "SKILL.md"
        require(skill_path.is_file(), f"missing creative recipe skill: {recipe['id']}")
        text = skill_path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if "://" in target or target.startswith("#") or target.rstrip("/") == "assets/examples":
                continue
            require((recipe_root / target).exists(), f"{recipe['id']}: missing linked resource {target}")

        preview = studio_by_id[recipe["id"]].get("preview") or {}
        if preview.get("status") != "available":
            missing_preview.append(recipe["id"])

    require(missing_preview == ["s013-vesak"], f"unexpected missing Studio previews: {missing_preview}")
    require(not (CREATIVE_CATALOG.parent / "previews").exists(), "creative Skill must not duplicate Studio preview images")

    # The core initializer must understand the frozen recipe id without loading
    # the full recipe payload; execution semantics belong to the companion skill.
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "source.jpg"
        Image.new("RGB", (320, 480), (80, 100, 120)).save(source)
        initialized = subprocess.run(
            [
                sys.executable,
                str(CORE / "scripts" / "init_job.py"),
                str(source),
                "--output-root", str(root / "jobs"),
                "--preset", "natural-cinematic",
                "--creative-recipe", "s001-abstract-quartet",
                "--creative-assembly-mode", "direct-effect",
                "--confirmed",
            ],
            capture_output=True,
            text=True,
        )
        require(initialized.returncode == 0, initialized.stdout + initialized.stderr)
        job_dir = Path(initialized.stdout.strip().splitlines()[-1])
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        require(job["execution_mode"] == "creative-translation", "initializer did not freeze creative mode")
        require(job["creative_recipe"]["id"] == "s001-abstract-quartet", "initializer lost selected recipe id")
        require(job["detail"]["mode"] == "creative-safe-adaptive", "eligible direct-effect job did not select creative-safe recovery")

        wrong_count = subprocess.run(
            [
                sys.executable,
                str(CORE / "scripts" / "init_job.py"),
                str(source),
                "--output-root", str(root / "bad-jobs"),
                "--preset", "natural-cinematic",
                "--creative-recipe", "s013-vesak",
                "--confirmed",
            ],
            capture_output=True,
            text=True,
        )
        require(wrong_count.returncode != 0, "multi-source recipe unexpectedly accepted one source")
        require("requires 3 source photographs" in wrong_count.stderr, "wrong source-count rejection lost its concrete reason")

    print("creative contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
