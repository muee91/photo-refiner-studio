# Photo Refiner Studio

Private source repository for the Photo Refiner Codex skill and its interactive MCP settings plugin.

## Layout

- `skill/` — reusable `photo-refiner` skill, references, scripts, and tests.
- `plugin/` — `photo-refiner-studio` plugin, settings panel, MCP server, presets, and smoke test.

## Validation

版本号的唯一来源是 `skill/scripts/job_contract.py` 里的 `SKILL_VERSION`；
`plugin/.codex-plugin/plugin.json` 只保留不带构建戳的基版本，`+codex.<时间戳>` 由打包脚本写入。

```bash
python3 distribution/build_bundle.py --dry-run   # 校验各处版本是否一致
python3 distribution/build_bundle.py --zip       # 产出 dist/ 下的可安装包
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skill
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugin
python3 -m unittest discover -s skill/tests
HOME="$(mktemp -d)" node plugin/tests/plugin_smoke.cjs
```

The repository intentionally excludes user preferences, confirmation records, generated jobs, outputs, caches, and source photographs.
