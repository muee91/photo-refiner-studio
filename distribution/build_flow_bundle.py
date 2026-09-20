#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_SOURCE = REPO_ROOT / "skill"
PLUGIN_SOURCE = REPO_ROOT / "plugin"
DIST_SOURCE = REPO_ROOT / "distribution"

SKILL_NAME = "photo-refiner-flow"
PLUGIN_NAME = "photo-refiner-flow-studio"
INSTALLER = "install_photo_refiner_flow.py"
TOP_FILES = (INSTALLER, "INSTALL.md", "CODEX_INSTALL_PROMPT.txt")


def ignore(_, names: list[str]) -> set[str]:
    blocked = {"__pycache__", ".DS_Store", ".git", ".zcode"}
    return {name for name in names if name in blocked or name.endswith((".pyc", ".pyo"))}


def copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, ignore=ignore, symlinks=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a coexistence-safe Photo Refiner Flow share bundle")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "dist" / "photo-refiner-flow-share.zip")
    args = parser.parse_args()

    for required in [SKILL_SOURCE / "SKILL.md", PLUGIN_SOURCE / ".codex-plugin" / "plugin.json", DIST_SOURCE / INSTALLER]:
        if not required.is_file():
            raise SystemExit(f"Missing required bundle input: {required}")

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="photo-refiner-flow-bundle-") as td:
        stage = Path(td)
        copy_tree(SKILL_SOURCE, stage / SKILL_NAME)
        copy_tree(PLUGIN_SOURCE, stage / PLUGIN_NAME)
        for name in TOP_FILES:
            shutil.copy2(DIST_SOURCE / name, stage / name)

        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for item in sorted(stage.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(stage).as_posix())

    print(output)


if __name__ == "__main__":
    main()
