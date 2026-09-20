# Photo Refiner Flow 独立安装

Photo Refiner Flow 是节点版技能，**不会删除或覆盖原来的 Photo Refiner**。

发行包包含：

- `photo-refiner-flow/`：Photo Refiner Flow Skill；
- `photo-refiner-flow-studio/`：Flow 节点画布 MCP Apps 插件。

安装后可以同时存在：

```text
~/.codex/skills/photo-refiner/
~/.codex/skills/photo-refiner-flow/

~/plugins/photo-refiner-studio/
~/plugins/photo-refiner-flow-studio/
```

状态目录也完全分离：

```text
~/.codex/photo-refiner/
~/.codex/photo-refiner-flow/
```

## 安装

```bash
python3 install_photo_refiner_flow.py
```

先检查目标而不写入：

```bash
python3 install_photo_refiner_flow.py --dry-run
```

安装器只会替换**旧的 Photo Refiner Flow 安装**，不会操作原版 Photo Refiner。

安装完成后完全退出并重新打开 Codex / ChatGPT 客户端，然后新建会话引用：

```text
@Photo Refiner Flow
```

或直接说：

```text
用 Photo Refiner Flow 打开节点画布
```
