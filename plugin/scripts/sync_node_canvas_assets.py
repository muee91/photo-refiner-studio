#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "node-canvas"
TARGET = REPO_ROOT / "plugin" / "assets" / "node-canvas"
FILES = ("index.html", "styles.css", "app.js")


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        source = SOURCE / name
        target = TARGET / name
        if not source.is_file():
            raise SystemExit(f"Missing Node Canvas source asset: {source}")
        shutil.copyfile(source, target)
        print(f"{source.relative_to(REPO_ROOT)} -> {target.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
