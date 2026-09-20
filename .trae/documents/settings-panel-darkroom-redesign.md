# Photo Refiner Studio 设置面板 · 暗房工作室风界面重构

## 摘要

将插件设置面板 [settings.html](file:///Users/muee/Documents/Codex workspace/photo-refiner-studio/plugin/assets/settings.html) 彻底重做为「暗房工作室」风格:深近黑底 + 颗粒/暗角质感、品牌青绿 `#1C8878` 强调色、更大的显示级排版、缩略图主导的配方网格。信息架构保留「三站 + 专业抽屉」骨架(集成安全),视觉、布局、组件层级全部重做。

## 现状分析

### 涉及文件

| 文件 | 角色 | 是否改动 |
|---|---|---|
| `plugin/assets/settings.html` | 面板唯一源文件(单文件 HTML,内联 CSS+JS,369 行) | **重做** |
| `plugin/mcp/server.cjs` | 读取该 HTML,替换 `__PHOTO_REFINER_INITIAL_PAYLOAD__` 令牌后经 MCP 分发 | 不改 |
| `plugin/.codex-plugin/plugin.json` | 版本号构成 Widget URI(`ui://widget/photo-refiner-settings/<version>.html`),用于缓存失效 | 版本号 0.5.0 → 0.6.0 |
| `plugin/tests/plugin_smoke.cjs` | 冒烟测试,锁定大量 HTML 文案/ID/类名/JS 标记 | 仅当下方枚举的文案变动时同步 |
| `plugin/assets/settings-preview.png` | plugin.json 引用的商店预览图,内容是**已淘汰的旧版浅色 UI** | 重新截图 |
| `skill/`、`plugin/config/`、`distribution/` | 逻辑/配置/安装器,与 UI 无关 | 不改 |

### 当前面板结构(信息架构)

1. 品牌行(PR 标 + Photo Refiner Studio + V0.5)
2. 推荐区 `#recommendation`(按照片给出创作方向,默认隐藏)
3. 手风琴三行(同时只展开一个,`data-pick` 切换):
   - `#rowLook` 风格:模式卡 ×3、预设网格 `#presetList`、强度滑杆、自定义提示词工作台
   - `#rowCreative` 创意:Starryear 配方缩略图网格 `#recipeGrid`(15 个配方)
   - `#rowShip` 出片:执行方式、分辨率、本次将执行
4. 流内 `#planText` 行(与底部栏 plan-chip **重复**,且与底栏元素共用重复 id `planText`)
5. `#proDrawer` 专业参数抽屉(8 个 tab:构图/色彩/人像/身材/服装/背景/细节/提示词库)
6. 底部固定胶囊操作条:状态 + plan-chip + 确认开跑

### 硬约束(冒烟测试锁定,违反即失败)

- **行顺序**:`rowLook` < `rowCreative` < `rowShip` 在 HTML 中出现顺序不变
- **类名/属性**:`proposal`、`data-pick`、`recipe-grid`、`preset-list` 必须存在
- **文案**(正则匹配):建议方案|proposal、Starryear 二次创作、高清出图是灵魂、专业参数、本次将执行：、提示词工作台、提示词库、自定义宽高、先选择风格和强度、先看效果图(推荐)、确认并开始、确认开跑、单张直接效果图(默认,不拼接)、待补效果图、先出主图、输出画幅继承画幅设置、头部 + 人脸、内置可直接使用、根据照片的建议、已应用到本次设置
- **JS 标记**:`watchRealPayload`、`__prcBound`、`sharedWorkflowWith`、`bridgeRequest`、`window.openai.callTool({name:params.name,arguments:params.arguments})`、`addEventListener('change',handleFieldChange)`、未收到初始设置、不要再次打开设置面板、PHOTO_REFINER_PANEL_SUBMITTED、direction.preset、labelZh||p.label
- **ID 完整性**:主脚本中所有字面量 `getElementById('...')` 必须有对应 `id="..."`:`photoRefinerInitialPayload`、`recommendation`、`recommendationText`、`directionList`、`preset`、`presetList`、`customFields`、`customPrompt`、`customAvoid`、`strengthPill`、`styleStrengthHint`、`recipeGrid`、`creativeMeta`、`creativeOutputWrap`、`creativeOutputHint`、`creativeWarning`、`creativeSummary`、`summaryText`、`lookSummary`、`shipSummary`、`proDrawer`、`resCustom`、`resW`、`resH`、`resApply`、`libraryList`、`status`、`submit`、`detailRegions`、`planText` 相关节点、`globalControls`、`portraitControls`、`bodyControls`、`clothingControls`、`backgroundControls`、`lookPick/creativePick/shipPick`、`lookToggle/creativeToggle/shipToggle`
- **数据绑定**:所有 `data-path` 属性与 `bind()`/`setDeep()`/`getDeep()` 数据流不动;`.mode-card`、`.opt-card[data-delivery]`、`#resSeg .chip`、`.chip[data-frag]`、`#proTabs button`、`.tab-panel` 选择器契约不动
- **宿主 CSP**:`widgetCSP.resource_domains` 为空 → 所有视觉资源必须内联或 data-uri,禁止外部字体/图片
- **单文件约束**:CSS/JS 继续全部内联在 settings.html

## 设计定义(决策已定,执行时不得再猜)

### 设计 token

```css
--bg:#070908;            /* 暗房近黑,微绿底 */
--ink:#EEF0EA;           /* 暖白 */
--muted:#9AA29B;
--faint:#6B736C;
--line:rgba(255,255,255,.10);
--line-soft:rgba(255,255,255,.06);
--glass:rgba(255,255,255,.04);
--glass-2:rgba(255,255,255,.07);
--pick:rgba(6,10,8,.55);
--teal:#1C8878;                    /* 品牌青绿 */
--teal-strong:#3FC3AC;             /* 文字/描边亮态 */
--teal-dim:rgba(28,136,120,.16);   /* 选中底色 */
--teal-line:rgba(63,195,172,.45);  /* 选中描边 */
--danger:#E5705F;
```

### 背景(替换现有 aurora 网格)

固定层 `.darkroom`(aria-hidden,沿用原 `.aurora` 位置),三层叠加:
1. 顶部左侧青绿辉光 `radial-gradient(720px 420px at 15% -8%, rgba(28,136,120,.13), transparent 62%)`
2. 底部极弱暖调安全灯 hint `radial-gradient(680px 420px at 85% 110%, rgba(214,138,74,.05), transparent 60%)`
3. 颗粒:内联 SVG `feTurbulence` data-uri 平铺,`opacity:.035`,`pointer-events:none`
4. 暗角:`radial-gradient(120% 90% at 50% 40%, transparent 55%, rgba(0,0,0,.38))`
5. **去掉**现有的方格网格线(科技感,与暗房气质冲突)

### 排版

- 品牌行:主标题 17px/700(现为 14px/650),副标保留 mono 10px;PR 标记块改青绿描边
- 站标题:`mono 编号 01/02/03`(青绿、letter-spacing .16em)+ 中文标题 15px/680 + 英文 mono 小标签(LOOK / CREATE / DELIVER)
- 正文保持 13.5px;`prefers-reduced-motion` 保留

### 组件重做要点

| 组件 | 重做内容 |
|---|---|
| 站卡片(原 .row) | 圆角 18→20px,深色玻璃 + 顶部 1px 高光;头部信息层级:编号+标题在上,当前选择摘要做成**青绿描边胶囊**置于右侧,替换现有小灰字+「更换」按钮的平淡组合(按钮保留,样式改胶囊) |
| 模式卡 .mode-card | 三卡等宽不变;选中态:青绿描边 + teal-dim 底 + `0 0 0 1px teal-line` 微光 |
| 预设 .preset-row | 两列不变;加强 hover/选中对比,标题 12px/650 |
| 强度滑杆 | `accent-color` 改青绿;数值 pill 改 mono 14px、深绿底 `#0E1512` + teal-line 描边 |
| 配方卡 .recipe-card | **缩略图加高 92→120px**,网格 `minmax(150px,1fr)`→`minmax(168px,1fr)`;配方编号做成缩略图左上角 mono 角标(黑底 50% 遮罩);选中态 teal 描边 + 外发光 `0 0 0 1px teal-line, 0 8px 24px rgba(28,136,120,.18)` |
| chips/筛选 | 选中态蓝色→青绿系 |
| 专业抽屉 | 改为第四张站卡片样式(编号 04 PRO);tabs 改分段控件:容器黑底 30% 圆角 999,选中 tab teal-dim |
| 底部操作条 | 浮动胶囊不变;提交按钮渐变改 `linear-gradient(180deg,#35B79C,#1C8878)`,文字色 `#04120E` |
| focus-visible / 滚动条 | 焦点环改青绿;为 `.library-list`、配方网格等滚动区加细暗色滚动条样式 |

### 结构改动(有限、枚举如下,除此之外不动)

1. **移除流内重复 plan-line**(第 253 行 `.plan-line`):底栏 plan-chip 已承担同一职责;同时消除重复 `id="planText"`。底栏 plan-chip 改 `id="planChip"`,`updateSummary()` 中 `querySelectorAll('#planText,#planStage')` 改为 `querySelectorAll('#planStage,#planChip')`。“本次将执行：”文案由 `executionPlan()` 产出,不受影响。
2. 品牌行副标 `V0.5` → `V0.6`。
3. `<meta name="theme-color">` 与 favicon data-uri 中 `#4da3ff`/`#0b0d12` 更新为新底色与青绿。
4. 手风琴交互(setPick/PICKS/row-btn)**保留**——宿主集成 JS 脆弱,交互骨架不动;本次彻底重做的范围落在视觉系统、布局层级、组件质感与上述 3 点结构修正。

## 逐文件改动

### 1. `plugin/assets/settings.html`(重做)

- 重写 `<style>` 全部规则(按上方 token 与组件规范);类名契约(`proposal`、`recipe-grid`、`preset-list`、`row-*`、`mode-card` 等)全部保留
- HTML 骨架:保留三行 + 抽屉 + 底栏的 ID 与 data-path 绑定;站头部按新层级重排;删除流内 plan-line
- JS:仅 2 处同步——`updateSummary()` 选择器(见上)、以及若站头部 DOM 顺序调整涉及的纯展示选择器;功能函数(load/bind/submit/bridge/watchRealPayload/syncGates 等)一字不动
- 所有锁定文案原样保留

### 2. `plugin/.codex-plugin/plugin.json`

- `version`: `0.5.0+codex.20260921010000` → `0.6.0+codex.<执行时时间戳>`(Widget URI 随版本失效,强制宿主加载新面板)

### 3. `plugin/tests/plugin_smoke.cjs`

- 目标零改动:文案与标记全部保留。执行后若某断言失败,仅在该处同步(并在完成汇报中说明)

### 4. `plugin/assets/settings-preview.png`(重新生成)

- 用一段临时 Node 脚本对 server.cjs 发 `resources/read`,把渲染后(令牌已替换为 fallback payload)的 HTML 写到临时文件
- 用 Playwright/agent-browser 以约 1280×900 视口截图,覆盖 `plugin/assets/settings-preview.png`
- 若截图工具链不可用:保留旧图并在汇报中明确标注,不阻塞主改动

## 假设与决策

- **保留手风琴骨架**:「彻底重做」授权结构与交互改动,但面板 JS 与宿主(window.openai/postMessage 桥)集成脆弱,且聊天内嵌 Widget 纵向空间宝贵;价值集中在视觉层。全展开/标签导航方案已评估并否决(高度失控/隐藏内容)。
- **文案零改动**:降低测试风险,所有产品文案沿用。
- **强调色全局替换蓝色系**:`--blue*` 变量整体映射到青绿系,不留蓝色残留。
- **性能**:颗粒层仅一层低透明度 data-uri,不影响 backdrop-filter 性能。

## 验证方法

```bash
# 1. 冒烟测试(核心门槛)
HOME="$(mktemp -d)" node plugin/tests/plugin_smoke.cjs
# 2. 插件校验
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugin
# 3. 视觉确认:临时渲染 HTML 截图,人工核对暗房风/青绿/缩略图加高/无蓝色残留
```

## 风险说明

- **宿主缓存**:Widget 按版本 URI 缓存,已用版本号 bump 规避;若宿主仍展示旧面板,重开对话即可。
- **ID 遗漏风险**:站头部重排时若误删被 JS 引用的 id,面板会停在「正在加载」——冒烟测试的 ID 完整性循环可拦截,必须在汇报前跑通。
- **截图步骤依赖外部环境**:失败不阻塞主交付,单独标注。
