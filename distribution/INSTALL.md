# Photo Refiner 一次性安装

这个发行包包含两部分：

- `photo-refiner/`：Photo Refiner Skill；
- `photo-refiner-studio/`：负责弹出设置面板和保存确认结果的 MCP 插件。

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

1. 将旧版 Skill、插件源、插件缓存和个人 Marketplace 条目移动到
   `~/.codex/photo-refiner-backups/<时间戳>/`；
2. 安装新版 Skill 到 `~/.codex/skills/photo-refiner/`；
3. 安装插件源到 `~/plugins/photo-refiner-studio/`；
4. 写入新版插件缓存并更新 `~/.agents/plugins/marketplace.json`；
5. 检查 Pillow/ImageCms、NumPy、PyYAML、OpenCV 和 SIFT 支持。

旧版不会被永久删除，备份目录可用于恢复。安装结束后完全退出 Codex，再重新打开并新建任务。

## 手动安装

不建议手动拆开安装。若必须手动操作，至少要同时保留 `photo-refiner/` 和
`photo-refiner-studio/`，否则 Skill 能被发现但设置面板无法打开。
