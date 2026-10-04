#!/usr/bin/env python3
"""Static architecture gate for the portable Photo Refiner Studio plugin."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def skill_runtime_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if "tests" in rel.parts or "__pycache__" in rel.parts or path.suffix == ".pyc":
            continue
        yield path


def main() -> int:
    manifest = load(ROOT / "plugin.json")
    overlay = load(ROOT / ".codex-plugin" / "plugin.json")
    mcp = load(ROOT / "mcp.json")

    require(manifest.get("$schema") == PLUGIN_SCHEMA, "root plugin.json must be Agent Plugins 1.0.0")
    require(manifest.get("name") == "photo-refiner-studio", "portable plugin name drifted")
    require(isinstance(manifest.get("version"), str) and SEMVER.fullmatch(manifest["version"]), "plugin version is not semver")
    require(overlay.get("name") == manifest["name"], "OpenAI overlay name must match portable identity")
    require(overlay.get("version") == manifest["version"], "OpenAI overlay version must match portable identity")
    require("interface" in overlay, "OpenAI overlay must provide Studio listing metadata")
    require("skills" not in overlay and "mcpServers" not in overlay, "overlay must not define a second component graph")

    require(mcp.get("$schema") == MCP_SCHEMA, "root mcp.json must use portable Agent Plugins schema")
    servers = mcp.get("mcpServers")
    require(isinstance(servers, dict) and set(servers) == {"photoRefinerStudio"}, "portable MCP graph drifted")
    server = servers["photoRefinerStudio"]
    require(server.get("type") == "stdio", "Studio MCP must use portable stdio")
    require(server.get("command") == "node", "Studio MCP command must be one executable token")
    require(server.get("args") == ["${PLUGIN_ROOT}/mcp/server.cjs", "--stdio"], "Studio args must be PLUGIN_ROOT-relative")
    require(server.get("cwd") == "${PLUGIN_ROOT}", "Studio cwd must be PLUGIN_ROOT")
    require((server.get("env") or {}).get("HOME") == "${PLUGIN_DATA}", "Studio persistent state must be scoped to PLUGIN_DATA")

    require(not (ROOT / "skill").exists(), "legacy root skill/ must not return")
    require(not (ROOT / "plugin").exists(), "legacy nested plugin/ must not return")
    require(not (ROOT / ".mcp.json").exists(), "legacy .mcp.json must not return")
    require(not (ROOT / "check_dependencies.py").exists(), "duplicate root dependency checker must not return")

    core = ROOT / "skills" / "photo-refiner"
    creative = ROOT / "skills" / "photo-refiner-creative"
    for skill in (core, creative):
        require((skill / "SKILL.md").is_file(), f"missing {skill.relative_to(ROOT)}/SKILL.md")
        files = list(skill_runtime_files(skill))
        require(len(files) <= 100, f"{skill.name} exceeds Agent Plugins 100-file skill limit: {len(files)}")
        total = sum(item.stat().st_size for item in files)
        require(total <= 5 * 1024 * 1024, f"{skill.name} exceeds Agent Plugins 5 MiB resource limit")
        for item in files:
            size = item.stat().st_size
            if item.name == "SKILL.md":
                require(size <= 256 * 1024, f"{skill.name}/SKILL.md exceeds 256 KiB")
            else:
                require(size <= 1024 * 1024, f"{item.relative_to(ROOT)} exceeds 1 MiB")

    require((core / "references" / "starryear" / "catalog.json").is_file(), "core deterministic catalog is missing")
    require(not (core / "references" / "starryear" / "recipes").exists(), "creative recipe payload leaked back into core skill")
    require((creative / "references" / "starryear" / "recipes").is_dir(), "creative recipe payload is missing")

    controller = core / "scripts" / "workflow_controller.py"
    require(controller.is_file(), "deterministic workflow controller is missing from runtime skill")
    controller_text = controller.read_text(encoding="utf-8")
    for event in ("approve", "continue", "redo", "adjust"):
        require(f'"{event}"' in controller_text, f"workflow controller is missing semantic event {event}")

    ci = ROOT / ".github" / "workflows" / "ci.yml"
    require(ci.is_file(), "main validation CI is missing")
    ci_text = ci.read_text(encoding="utf-8")
    require("upload-artifact" not in ci_text, "CI must not upload artifacts")
    require("tests/route_contract.py" in ci_text, "CI must run the HD route contract")

    contract = (core / "scripts" / "job_contract.py").read_text(encoding="utf-8")
    match = re.search(r'^SKILL_VERSION = "([^"]+)"', contract, re.M)
    require(bool(match), "core job contract has no SKILL_VERSION")
    require((core / "SKILL.md").read_text(encoding="utf-8").splitlines()[5] == f"# Photo Refiner v{match.group(1)}", "core skill heading/version drifted")

    print(f"portable layout OK: plugin {manifest['version']}, core contract {match.group(1)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
