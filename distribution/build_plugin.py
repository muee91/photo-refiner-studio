#!/usr/bin/env python3
"""Validate and package the portable Photo Refiner Studio Agent Plugin."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
RUNTIME_PATHS = (
    "plugin.json",
    "mcp.json",
    ".codex-plugin",
    "assets",
    "config",
    "mcp",
    "skills",
)


def fail(message: str) -> None:
    raise SystemExit(f"build failed: {message}")


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read JSON {path.relative_to(REPO)}: {exc}")
    if not isinstance(value, dict):
        fail(f"{path.relative_to(REPO)} must contain one JSON object")
    return value


def runtime_skill_files(skill_root: Path):
    for path in sorted(skill_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(skill_root)
        if "tests" in rel.parts or "__pycache__" in rel.parts or path.suffix == ".pyc" or path.name == ".DS_Store":
            continue
        yield path


def check_skill_import_limits(skill_root: Path) -> None:
    files = list(runtime_skill_files(skill_root))
    if len(files) > 100:
        fail(f"{skill_root.name} has {len(files)} runtime files; Agent Plugins limit is 100")
    total = 0
    for path in files:
        size = path.stat().st_size
        total += size
        if path.name == "SKILL.md" and size > 256 * 1024:
            fail(f"{skill_root.name}/SKILL.md exceeds 256 KiB")
        if path.name != "SKILL.md" and size > 1024 * 1024:
            fail(f"{path.relative_to(REPO)} exceeds 1 MiB")
    if total > 5 * 1024 * 1024:
        fail(f"{skill_root.name} runtime resources exceed 5 MiB")


def validate_stdio_server(server: dict, script: str, label: str) -> None:
    if server.get("type") != "stdio" or server.get("command") != "node":
        fail(f"{label} must be a portable stdio Node server")
    if server.get("args") != [f"${{PLUGIN_ROOT}}/mcp/{script}", "--stdio"]:
        fail(f"{label} args must resolve mcp/{script} from PLUGIN_ROOT")
    if server.get("cwd") != "${PLUGIN_ROOT}":
        fail(f"{label} cwd must be PLUGIN_ROOT")
    if (server.get("env") or {}).get("HOME") != "${PLUGIN_DATA}":
        fail(f"{label} persistent state must be scoped to PLUGIN_DATA")


def check_portable_layout() -> tuple[str, str]:
    manifest = load_json(REPO / "plugin.json")
    if manifest.get("$schema") != PLUGIN_SCHEMA:
        fail("plugin.json must target Agent Plugins 1.0.0")
    name = manifest.get("name")
    version = manifest.get("version")
    if name != "photo-refiner-studio":
        fail(f"unexpected plugin name: {name!r}")
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        fail(f"plugin version must be semver, got {version!r}")

    overlay = load_json(REPO / ".codex-plugin" / "plugin.json")
    if overlay.get("name") != name or overlay.get("version") != version:
        fail("OpenAI overlay name/version must match root plugin.json")
    if "mcpServers" in overlay or "skills" in overlay:
        fail("OpenAI overlay must not declare alternate portable components")

    mcp = load_json(REPO / "mcp.json")
    if mcp.get("$schema") != MCP_SCHEMA:
        fail("mcp.json must target Agent Plugins 1.0.0")
    servers = mcp.get("mcpServers")
    if not isinstance(servers, dict) or set(servers) != {"photoRefinerStudio", "photoRefinerWorkflow"}:
        fail("mcp.json must contain settings + workflow MCP servers")
    validate_stdio_server(servers["photoRefinerStudio"], "server.cjs", "photoRefinerStudio")
    validate_stdio_server(servers["photoRefinerWorkflow"], "workflow.cjs", "photoRefinerWorkflow")

    for legacy in (REPO / "plugin", REPO / "skill", REPO / ".mcp.json", REPO / "check_dependencies.py"):
        if legacy.exists():
            fail(f"legacy layout still exists: {legacy.relative_to(REPO)}")

    for skill_name in ("photo-refiner", "photo-refiner-creative"):
        skill_root = REPO / "skills" / skill_name
        if not (skill_root / "SKILL.md").is_file():
            fail(f"missing skills/{skill_name}/SKILL.md")
        check_skill_import_limits(skill_root)

    core = REPO / "skills" / "photo-refiner"
    creative = REPO / "skills" / "photo-refiner-creative"
    if (core / "references" / "starryear" / "recipes").exists():
        fail("creative recipe payload leaked into core skill")
    if not (creative / "references" / "starryear" / "recipes").is_dir():
        fail("creative recipe payload is missing")
    if (creative / "references" / "starryear" / "previews").exists():
        fail("Studio preview images must not be duplicated inside the creative skill")

    for required in (
        REPO / "mcp" / "workflow.cjs",
        REPO / "assets" / "review.html",
        REPO / "assets" / "recent-jobs.html",
        core / "scripts" / "workflow_controller.py",
        core / "scripts" / "batch_frames.py",
        core / "scripts" / "bind_batch_master.py",
    ):
        if not required.is_file():
            fail(f"missing workflow runtime file: {required.relative_to(REPO)}")

    contract = (core / "scripts" / "job_contract.py").read_text(encoding="utf-8")
    match = re.search(r'^SKILL_VERSION = "([^"]+)"', contract, re.M)
    if not match:
        fail("photo-refiner job_contract.py has no SKILL_VERSION")
    skill_version = match.group(1)
    lines = (core / "SKILL.md").read_text(encoding="utf-8").splitlines()
    if len(lines) < 6 or lines[5] != f"# Photo Refiner v{skill_version}":
        fail("core SKILL.md heading does not match job_contract.SKILL_VERSION")

    return version, skill_version


def excluded(path: Path) -> bool:
    rel = path.relative_to(REPO)
    if "__pycache__" in rel.parts or path.suffix == ".pyc" or path.name == ".DS_Store":
        return True
    if "skills" in rel.parts and "tests" in rel.parts:
        return True
    return False


def copy_runtime(source: Path, destination: Path) -> None:
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return
    if not source.is_dir():
        fail(f"missing runtime path: {source.relative_to(REPO)}")
    for item in sorted(source.rglob("*")):
        if not item.is_file() or excluded(item):
            continue
        target = destination / item.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def make_zip(plugin_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(plugin_dir.rglob("*")):
            if item.is_file():
                archive.write(item, Path(plugin_dir.name) / item.relative_to(plugin_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate/build Photo Refiner Studio portable plugin")
    parser.add_argument("--out", type=Path, default=REPO / "dist", help="output directory")
    parser.add_argument("--check", action="store_true", help="validate only")
    parser.add_argument("--zip", action="store_true", help="also produce a ZIP")
    args = parser.parse_args()

    plugin_version, skill_version = check_portable_layout()
    print(f"portable layout OK: plugin {plugin_version}, photo contract {skill_version}")
    if args.check:
        return 0

    out = args.out.expanduser().resolve()
    plugin_dir = out / f"photo-refiner-studio-{plugin_version}"
    if plugin_dir.exists():
        shutil.rmtree(plugin_dir)
    plugin_dir.mkdir(parents=True)

    for rel in RUNTIME_PATHS:
        copy_runtime(REPO / rel, plugin_dir / rel)

    print(f"built: {plugin_dir}")
    if args.zip:
        zip_path = out / f"photo-refiner-studio-{plugin_version}.zip"
        zip_path.unlink(missing_ok=True)
        make_zip(plugin_dir, zip_path)
        print(f"zip:   {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
