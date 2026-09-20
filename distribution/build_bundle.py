#!/usr/bin/env python3
"""Build an installable Photo Refiner distribution bundle from the repository.

The installer expects a bundle laid out as `photo-refiner/` plus
`photo-refiner-studio/`, and the plugin cache is keyed by the plugin version. Both
facts used to be handled by hand, which made releases unreproducible and let the
version strings in the docs drift away from the code. This script checks the
version agreement, lays out the bundle, and applies the `+codex.<stamp>` build
suffix so the repository keeps only the plain base version.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL_VERSION_PATTERN = re.compile(r"^\d+\.\d+$")
BASE_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def fail(message: str) -> None:
    raise SystemExit(f"打包失败：{message}")


def read_skill_version() -> str:
    """The product version lives in one place: scripts/job_contract.py."""
    module = REPO / "skill" / "scripts" / "job_contract.py"
    match = re.search(r'^SKILL_VERSION = "([^"]+)"', module.read_text(encoding="utf-8"), re.M)
    if not match:
        fail("job_contract.py 里没有 SKILL_VERSION")
    version = match.group(1)
    if not SKILL_VERSION_PATTERN.fullmatch(version):
        fail(f"SKILL_VERSION 应为 MAJOR.MINOR，实为 {version!r}")
    return version


def check_version_agreement(version: str) -> list[str]:
    """Fail the build when any declared version disagrees with the constant."""
    problems = []
    heading = (REPO / "skill" / "SKILL.md").read_text(encoding="utf-8").splitlines()[5]
    if heading != f"# Photo Refiner v{version}":
        problems.append(f"skill/SKILL.md 标题是 {heading!r}，应为 {f'# Photo Refiner v{version}'}")

    schema = (REPO / "skill" / "references" / "config-schema.md").read_text(encoding="utf-8")
    if f'release_version: "{version}"' not in schema:
        problems.append(f"config-schema.md 的 release_version 不是 {version!r}")

    manifest = json.loads((REPO / "plugin" / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    base = manifest["version"]
    if not BASE_VERSION_PATTERN.fullmatch(base):
        problems.append(f"plugin.json 的 version 应为不带构建戳的 MAJOR.MINOR.PATCH，实为 {base!r}")
    prose = json.dumps(manifest, ensure_ascii=False)
    if re.search(r"Photo Refiner v\d", prose):
        problems.append("plugin.json 文案里重复了 Skill 版本号，会随版本漂移")
    return problems


def excluded(path: Path) -> bool:
    return any(part == "__pycache__" for part in path.parts) or path.name == ".DS_Store" or path.suffix == ".pyc"


def copy_tree(source: Path, target: Path) -> int:
    if not source.is_dir():
        fail(f"缺少源目录 {source}")
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in sorted(source.rglob("*")):
        if not item.is_file() or excluded(item):
            continue
        destination = target / item.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
        count += 1
    return count


def stamp_plugin_version(plugin_dir: Path, stamp: str) -> str:
    manifest_path = plugin_dir / ".codex-plugin" / "plugin.json"
    text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(text)
    stamped = f"{manifest['version']}+codex.{stamp}"
    manifest_path.write_text(text.replace(f'"version": "{manifest["version"]}"', f'"version": "{stamped}"', 1), encoding="utf-8")
    return stamped


def make_zip(bundle: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(bundle.rglob("*")):
            if item.is_file():
                archive.write(item, item.relative_to(bundle.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description="生成可安装的 Photo Refiner 发行包")
    parser.add_argument("--out", type=Path, default=REPO / "dist", help="输出目录（默认 ./dist）")
    parser.add_argument("--stamp", help="构建戳，默认取当前时间 YYYYmmddHHMMSS")
    parser.add_argument("--zip", action="store_true", help="同时生成可拖入聊天的 ZIP")
    parser.add_argument("--dry-run", action="store_true", help="只做版本校验，不写文件")
    args = parser.parse_args()

    version = read_skill_version()
    problems = check_version_agreement(version)
    if problems:
        for problem in problems:
            print(f"  版本不一致：{problem}")
        fail("请先统一版本声明再打包")
    print(f"版本校验通过：Skill v{version}")

    if args.dry_run:
        print("试运行：未写出文件。")
        return 0

    stamp = args.stamp or datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    bundle = args.out.expanduser() / f"photo-refiner-{version}+codex.{stamp}"
    if bundle.exists():
        fail(f"输出目录已存在：{bundle}")
    (bundle / "photo-refiner").mkdir(parents=True)
    skills = copy_tree(REPO / "skill", bundle / "photo-refiner")
    plugins = copy_tree(REPO / "plugin", bundle / "photo-refiner-studio")
    shutil.copy2(REPO / "distribution" / "install_photo_refiner.py", bundle / "install_photo_refiner.py")
    for doc in ("INSTALL.md", "CODEX_INSTALL_PROMPT.txt"):
        source = REPO / "distribution" / doc
        if source.is_file():
            shutil.copy2(source, bundle / doc)
    stamped = stamp_plugin_version(bundle / "photo-refiner-studio", stamp)

    print(f"打包完成：{bundle}")
    print(f"  Skill   {skills} 个文件 -> photo-refiner/")
    print(f"  Plugin  {plugins} 个文件 -> photo-refiner-studio/  (version {stamped})")
    print("  安装：把该目录交给 Codex 执行 install_photo_refiner.py，或整体拖入聊天框。")
    if args.zip:
        zip_path = bundle.parent / (bundle.name + ".zip")
        make_zip(bundle, zip_path)
        print(f"  ZIP：{zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
