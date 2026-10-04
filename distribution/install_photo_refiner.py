#!/usr/bin/env python3
"""Install the bundled Photo Refiner Skill and Studio plugin.

The share bundle places this file beside ``photo-refiner/`` and
``photo-refiner-studio/``. Existing Photo Refiner installations are removed
from their exact known locations before the new files are installed. Other
skills, plugins, photos, and user data are not targeted.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
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


def manifest_version(plugin_source: Path) -> str:
    try:
        manifest = json.loads((plugin_source / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        version = str(manifest["version"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        fail(f"插件 manifest 无效：{exc}")
    if not version:
        fail("插件 manifest 缺少 version")
    return version


def remove_old_install(path: Path, dry_run: bool) -> None:
    if not path.exists():
        return
    print(f"永久删除旧版：{path}")
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
    filtered = [item for item in plugins if not isinstance(item, dict) or item.get("name") != PLUGIN_NAME]
    filtered.append(entry)
    data["plugins"] = filtered

    print(f"更新个人 Marketplace：{path}")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def enable_plugin(plugin_id: str, dry_run: bool) -> None:
    """Register the local plugin with Codex so new app sessions expose its MCP tools."""
    command = shutil.which("codex")
    print(f"启用 Codex 插件：codex plugin add {plugin_id}")
    if dry_run:
        return
    if not command:
        fail("找不到 codex CLI，无法把 Photo Refiner 加入 Codex 工具注册表")

    added = subprocess.run(
        [command, "plugin", "add", plugin_id, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if added.returncode:
        detail = (added.stderr or added.stdout).strip()
        fail(f"Codex 插件启用失败：{detail or f'退出码 {added.returncode}'}")

    listed = subprocess.run(
        [command, "plugin", "list", "--marketplace", "personal", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode:
        detail = (listed.stderr or listed.stdout).strip()
        fail(f"无法验证 Codex 插件状态：{detail or f'退出码 {listed.returncode}'}")
    try:
        entries = json.loads(listed.stdout)
    except json.JSONDecodeError as exc:
        fail(f"Codex 插件状态不是有效 JSON：{exc}")
    installed = next(
        (item for item in entries.get("installed", []) if item.get("pluginId") == plugin_id),
        None,
    )
    if not installed or installed.get("enabled") is not True:
        fail(f"Codex 插件未处于已安装且启用状态：{plugin_id}")
    print(f"Codex 插件已启用：{plugin_id} @ {installed.get('version', 'unknown')}")


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

    print(f"Photo Refiner 安装包版本：{version}")
    if args.dry_run:
        print("试运行模式：不会修改文件。")
    else:
        print("旧版 Photo Refiner 将被永久删除，不创建备份。")

    remove_old_install(skill_target, args.dry_run)
    remove_old_install(plugin_target, args.dry_run)
    remove_old_install(cache_root, args.dry_run)
    copy_tree(skill_source, skill_target, args.dry_run)
    copy_tree(plugin_source, plugin_target, args.dry_run)
    copy_tree(plugin_source, cache_target, args.dry_run)
    update_marketplace(marketplace, args.dry_run)
    enable_plugin(f"{PLUGIN_NAME}@personal", args.dry_run)

    if not args.dry_run and not args.skip_dependency_check:
        run_dependency_check(skill_target)

    print("安装完成。旧版已删除。请完全退出并重新打开 Codex，然后新建任务以加载 Skill 和 MCP 插件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
