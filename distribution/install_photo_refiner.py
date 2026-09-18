#!/usr/bin/env python3
"""Install the bundled Photo Refiner Skill and Studio plugin.

The share bundle places this file beside ``photo-refiner/`` and
``photo-refiner-studio/``. Existing installations are moved to a timestamped
backup under ``$CODEX_HOME/photo-refiner-backups`` before the new files are
installed. No existing user data is permanently deleted.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PLUGIN_NAME = "photo-refiner-studio"
SKILL_NAME = "photo-refiner"


def fail(message: str) -> None:
    raise SystemExit(f"安装失败：{message}")


def bundle_root() -> Path:
    root = Path(__file__).resolve().parent
    if (root / SKILL_NAME / "SKILL.md").is_file() and (root / PLUGIN_NAME / ".codex-plugin" / "plugin.json").is_file():
        return root
    fail("安装脚本必须位于解压后的发行包根目录")


def unique_backup_root(codex_home: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = codex_home / "photo-refiner-backups" / stamp
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = codex_home / "photo-refiner-backups" / f"{stamp}-{suffix}"
        suffix += 1
    return candidate


def manifest_version(plugin_source: Path) -> str:
    try:
        manifest = json.loads((plugin_source / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        version = str(manifest["version"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        fail(f"插件 manifest 无效：{exc}")
    if not version:
        fail("插件 manifest 缺少 version")
    return version


def move_to_backup(path: Path, backup: Path, dry_run: bool) -> None:
    if not path.exists():
        return
    print(f"备份旧版：{path} -> {backup}")
    if not dry_run:
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(backup))


def copy_tree(source: Path, target: Path, dry_run: bool) -> None:
    print(f"安装：{source} -> {target}")
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, symlinks=False)


def update_marketplace(path: Path, backup: Path, dry_run: bool) -> None:
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
    filtered = [item for item in plugins if not isinstance(item, dict) or item.get("name") != PLUGIN_NAME]
    filtered.append(entry)
    data["plugins"] = filtered

    print(f"更新个人 Marketplace：{path}")
    if not dry_run:
        if path.exists():
            move_to_backup(path, backup, False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_dependency_check(skill_target: Path) -> None:
    checker = skill_target / "scripts" / "check_dependencies.py"
    result = subprocess.run([sys.executable, str(checker)], capture_output=True, text=True, check=False)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode:
        print("警告：运行环境缺少 Photo Refiner 的一个或多个 Python 依赖；请按上面的结果补齐。")


def main() -> int:
    parser = argparse.ArgumentParser(description="安装 Photo Refiner Skill 与 Studio 插件")
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
    backup_root = unique_backup_root(codex_home)

    print(f"Photo Refiner 安装包版本：{version}")
    if args.dry_run:
        print("试运行模式：不会修改文件。")
    elif not backup_root.exists():
        backup_root.mkdir(parents=True)
        print(f"旧版隔离备份目录：{backup_root}")

    move_to_backup(skill_target, backup_root / "skill", args.dry_run)
    move_to_backup(plugin_target, backup_root / "plugin-source", args.dry_run)
    move_to_backup(cache_root, backup_root / "plugin-cache", args.dry_run)
    copy_tree(skill_source, skill_target, args.dry_run)
    copy_tree(plugin_source, plugin_target, args.dry_run)
    copy_tree(plugin_source, cache_target, args.dry_run)
    update_marketplace(marketplace, backup_root / "marketplace.json", args.dry_run)

    if not args.dry_run and not args.skip_dependency_check:
        run_dependency_check(skill_target)

    print("安装完成。请完全退出并重新打开 Codex，然后新建任务以加载 Skill 和 MCP 插件。")
    print(f"旧版可从备份目录恢复：{backup_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
