# Photo Refiner 一次性安装

发行包由 `python3 distribution/build_bundle.py` 从仓库生成（`--zip` 可一并产出可拖入聊天
的 ZIP，`--dry-run` 只校验版本一致性）。不要手工复制目录：脚本会核对 `SKILL_VERSION`、
`SKILL.md` 标题与 `config-schema.md` 是否一致，并写入带构建戳的插件版本。

这个发行包包含两部分：

- `photo-refiner/`：Photo Refiner v2.4 Skill，包含 15 个原版 Starryear 创意转译工作流与选择器缩略图；
- `photo-refiner-studio/`：负责弹出设置面板和保存确认结果的 MCP 插件。

## 拖入聊天框后的单行指令

将本 ZIP 直接拖入 Codex 聊天框，然后发送下面这句话即可：

> 安装我刚上传的 Photo Refiner 压缩包：自动解压并运行包内 `install_photo_refiner.py`，永久删除旧版 Photo Refiner Skill、插件和缓存，再安装新版并完成依赖、Skill 和 MCP smoke test；不要只给我安装步骤，直接执行并报告结果。

## 用 Codex 安装

把 ZIP 解压后，将解压目录作为工作目录交给 Codex，并让 Codex 执行：

```bash
python3 install_photo_refiner.py
```

也可以先检查安装目标，不写入任何文件：

```bash
python3 install_photo_refiner.py --dry-run
```

安装器会：

1. 永久删除旧版 Photo Refiner Skill、插件源和插件缓存；
2. 安装新版 Skill 到 `~/.codex/skills/photo-refiner/`；
3. 安装插件源到 `~/plugins/photo-refiner-studio/`；
4. 写入新版插件缓存并更新 `~/.agents/plugins/marketplace.json`；
5. 调用 codex plugin add photo-refiner-studio@personal，把插件标记为已安装并启用；
6. 检查 Pillow/ImageCms、NumPy、PyYAML、OpenCV 和 SIFT 支持。
旧版不会保留备份，也无法通过安装器恢复。安装结束后完全退出 Codex，再重新打开并新建任务。

## 手动安装

不建议手动拆开安装。若必须手动操作，至少要同时保留 `photo-refiner/` 和
`photo-refiner-studio/`，否则 Skill 能被发现但设置面板无法打开。
