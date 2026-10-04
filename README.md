# Photo Refiner Studio

Private source repository for the Photo Refiner ChatGPT/Codex skill and its interactive MCP settings plugin.

## Layout

- `skill/` — reusable `photo-refiner` skill, references, deterministic scripts, and tests.
- `plugin/` — `photo-refiner-studio` plugin, settings panel, MCP server, presets, and smoke test.
- `ARCHITECTURE.md` — current ChatGPT-native architecture, local/cloud boundary, and plugin migration priorities.

The current pipeline treats ChatGPT Images as the rendering provider and keeps photographic authority, HD honesty, Pixel Budget, returned-patch observation, registration/blending, review checkpoints, and delivery evidence inside Photo Refiner.

Optional perception helpers such as relative depth remain hidden/advisory. See `skill/references/depth-prior.md`; depth must not increase the default patch quota by itself.

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

`python3 -m unittest discover -s skill/tests` now includes the optional depth-prior contract tests as well as the existing HD/tile/delivery regressions.

The repository intentionally excludes user preferences, confirmation records, generated jobs, outputs, caches, dense depth maps, and source photographs.
