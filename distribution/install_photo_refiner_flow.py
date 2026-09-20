#!/usr/bin/env python3
"""Install Photo Refiner Flow beside the original Photo Refiner.

This installer only replaces exact Photo Refiner Flow locations. It never
removes the original photo-refiner Skill, photo-refiner-studio plugin, or
~/.codex/photo-refiner user state.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_NAME = "photo-refiner-flow-studio"
SKILL_NAME = "photo-refiner-flow"


def fail(message: str) -> None:
    raise SystemExit(f"安装失败：{message}")


def bundle_root() -> Path:
    root = Path(__file__).resolve().parent
    if (root / SKILL_NAME / "SKILL.md").is_file() and (root / PLUGIN_NAME / ".codex-plugin" / "plugin.json").is_file():
        return root
    fail("安装脚本必须位于 Photo Refiner Flow 解压包根目录")


def manifest_version(plugin_source: Path) -> str:
    try:
        manifest = json.loads((plugin_source / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        version = str(manifest["version"])
        name = str(manifest["name"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        fail(f"插件 manifest 无效：{exc}")
    if name != PLUGIN_NAME:
        fail(f"插件 manifest name 必须是 {PLUGIN_NAME}，当前为 {name}")
    if not version:
        fail("插件 manifest 缺少 version")
    return version


def remove_flow_install(path: Path, dry_run: bool) -> None:
    if not path.exists():
        return
    print(f"替换旧 Flow 安装：{path}")
    if not dry_run:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def copy_tree(source: Path, target: Path, dry_run: bool) -> None:
    print(f"安装：{source} -> {target}")
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, symlinks=False)


def update_marketplace(path: Path, dry_run: bool) -> None:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            fail(f"个人 Marketplace JSON 无法读取：{exc}")
        if data.get("name", "personal") != "personal":
            fail(f"{path} 不是 personal Marketplace，未修改它")
    else:
        data = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}

    plugins = data.setdefault("plugins", [])
    if not isinstance(plugins, list):
        fail(f"{path} 的 plugins 字段不是数组")

    entry = {
        "name": PLUGIN_NAME,
        "source": {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Creative",
    }
    plugins = [item for item in plugins if not isinstance(item, dict) or item.get("name") != PLUGIN_NAME]
    plugins.append(entry)
    data["plugins"] = plugins

    print(f"更新个人 Marketplace：{path}")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_dependency_check(skill_target: Path) -> None:
    checker = skill_target / "scripts" / "check_dependencies.py"
    result = subprocess.run([sys.executable, str(checker)], capture_output=True, text=True, check=False)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode:
        print("警告：运行环境缺少 Photo Refiner Flow 的一个或多个 Python 依赖；请按上面的结果补齐。")


def main() -> int:
    parser = argparse.ArgumentParser(description="独立安装 Photo Refiner Flow Skill 与 Flow Studio 插件")
    parser.add_argument("--dry-run", action="store_true", help="只显示将执行的动作，不写入文件")
    parser.add_argument("--skip-dependency-check", action="store_true", help="跳过依赖检查")
    args = parser.parse_args()

    root = bundle_root()
    skill_source = root / SKILL_NAME
    plugin_source = root / PLUGIN_NAME
    version = manifest_version(plugin_source)

    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    skill_target = codex_home / "skills" / SKILL_NAME
    plugin_target = Path.home() / "plugins" / PLUGIN_NAME
    cache_root = codex_home / "plugins" / "cache" / "personal" / PLUGIN_NAME
    cache_target = cache_root / version
    marketplace = Path.home() / ".agents" / "plugins" / "marketplace.json"

    print(f"Photo Refiner Flow 安装包版本：{version}")
    print("原版 Photo Refiner 不会被删除或覆盖。")
    if args.dry_run:
        print("试运行模式：不会修改文件。")

    remove_flow_install(skill_target, args.dry_run)
    remove_flow_install(plugin_target, args.dry_run)
    remove_flow_install(cache_root, args.dry_run)
    copy_tree(skill_source, skill_target, args.dry_run)
    copy_tree(plugin_source, plugin_target, args.dry_run)
    copy_tree(plugin_source, cache_target, args.dry_run)
    update_marketplace(marketplace, args.dry_run)

    if not args.dry_run and not args.skip_dependency_check:
        run_dependency_check(skill_target)

    print("安装完成。Photo Refiner 与 Photo Refiner Flow 可独立共存。请完全退出并重新打开客户端。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
