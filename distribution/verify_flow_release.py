#!/usr/bin/env python3
from __future__ import annotations

import compileall
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skill"
PLUGIN = REPO_ROOT / "plugin"
DIST = REPO_ROOT / "distribution"


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("$", " ".join(command))
    result = subprocess.run(command, cwd=REPO_ROOT, env=env, text=True)
    if result.returncode:
        raise SystemExit(result.returncode)


def identity_checks() -> None:
    manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    if manifest.get("name") != "photo-refiner-flow-studio":
        raise SystemExit("Plugin name is not photo-refiner-flow-studio")

    mcp = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))
    if list(mcp.get("mcpServers", {})) != ["photoRefinerFlowStudio"]:
        raise SystemExit("MCP server id is not photoRefinerFlowStudio")

    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    if "name: photo-refiner-flow" not in skill_text:
        raise SystemExit("Skill id is not photo-refiner-flow")

    installer = (DIST / "install_photo_refiner_flow.py").read_text(encoding="utf-8")
    for required in ['PLUGIN_NAME = "photo-refiner-flow-studio"', 'SKILL_NAME = "photo-refiner-flow"']:
        if required not in installer:
            raise SystemExit(f"Installer identity missing: {required}")


def compile_python() -> None:
    roots = [SKILL / "scripts", SKILL / "tests", DIST]
    for root in roots:
        if not compileall.compile_dir(root, quiet=1, force=True):
            raise SystemExit(f"Python compile failed under {root}")


def run_tests() -> None:
    run([sys.executable, "-m", "unittest", "discover", "-s", "skill/tests"])
    run(["node", "plugin/tests/plugin_smoke.cjs"])


def verify_bundle() -> None:
    with tempfile.TemporaryDirectory(prefix="photo-refiner-flow-verify-") as td:
        out = Path(td) / "photo-refiner-flow-share.zip"
        run([sys.executable, "distribution/build_flow_bundle.py", "--output", str(out)])
        with zipfile.ZipFile(out) as archive:
            names = set(archive.namelist())
        required = {
            "photo-refiner-flow/SKILL.md",
            "photo-refiner-flow-studio/.codex-plugin/plugin.json",
            "photo-refiner-flow-studio/.mcp.json",
            "install_photo_refiner_flow.py",
            "INSTALL.md",
            "CODEX_INSTALL_PROMPT.txt",
        }
        missing = required - names
        if missing:
            raise SystemExit("Flow bundle is incomplete: " + ", ".join(sorted(missing)))
        forbidden_prefixes = ("photo-refiner/", "photo-refiner-studio/")
        if any(name.startswith(forbidden_prefixes) for name in names):
            raise SystemExit("Flow bundle accidentally contains original Photo Refiner install paths")


def main() -> None:
    identity_checks()
    compile_python()
    run_tests()
    verify_bundle()
    print("Photo Refiner Flow verification: PASS")


if __name__ == "__main__":
    main()
