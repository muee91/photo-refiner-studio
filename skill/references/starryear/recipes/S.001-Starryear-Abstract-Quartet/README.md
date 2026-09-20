<div align="center">

# ◼ 【001】Starryear-Abstract-Quarter

**保留顶部真实原图，让下面三幅在同一种克制块面语言中完成凝聚、漂移与释放。**

[![Codex Skill](https://img.shields.io/badge/Codex-Skill-000000?style=for-the-badge&logo=openai&logoColor=white)](#)
[![Usage](https://img.shields.io/badge/Usage-Personal%20%26%20Non--commercial-lightgrey?style=for-the-badge)](./LICENSE.md)
[![Language](https://img.shields.io/badge/🌐_中文-English-blue?style=for-the-badge)](#)

</div>

---

## ⚠️ 声明

> **仅限个人学习、非营利研究与非商业创作。**
> 任何商业使用均须事先取得 Starryear年 的书面许可。
>
> 分享作品时，欢迎标注来源并 **@Starryear年**。

---

## 📖 关于本项目

【001】Starryear-Abstract-Quarter 将一张照片编排为无缝竖向四联：第一联保留真实照片证据；第二联凝聚主导物象和空间骨架；第三联拆散并重排关系；第四联让一个强烈的源物象姿态进入不可能但自洽的释放状态。后三联共享简化平面块面、少量结构线、哑光触感、象牙留白与克制构图。辨识度不是错误：作品允许保留树干—根系、建筑轴线、身体姿态或道路方向等关键骨架，真正排除的是摄影式复刻、机械描摹与湿墨晕染。

- ✅ 保留真实照片作为不可重绘的证据联
- ✅ 从同一组来源事实生成凝聚母题、关系漂移与物理余像
- ✅ 允许“凝聚辨识—关系漂移—动作释放”的高—低—高辨识度节奏
- ✅ 当逆光穿透薄叶／薄膜成为画面核心时，可启用“透光有机模式”，以平整透明色面、几何结构线和少量间隔标记保留光感
- ❌ 不让下三联出现摄影碎片、机械描摹或跨度过大的不同画风
- ❌ 不采用湿水墨、墨池、洇边或大面积毛笔涂抹；允许少量干性印刷磨蚀与释放性短笔

> 📝 The Skill includes the complete prompt in both **Chinese** and **English**.

---

## 🖼️ 示例作品

以下两幅由 Starryear年 明确认可，作为视觉原则示例：它们只说明“来源骨架可以保留、辨识度可以有力、边缘可以适度释放”，不得复用其树木题材、色板或具体构图到其他照片。

- `assets/examples/approved-condensed-motif.png`：保留主导树干、根系放射、人物尺度与浅层空间的凝聚母题。
- `assets/examples/approved-physical-afterimage.png`：以断续放射和向上释放重写树干—根系动作的物理余像。

---

## 📋 目录

- [使用方法](#-使用方法)
- [可自由调整的部分](#️-可自由调整的部分)
- [核心原则](#-核心原则)
- [内容结构](#-内容结构)
- [许可证](#-许可证)

---

## 🚀 使用方法

### 方式一：作为 Codex Skill 使用

1. 将整个 `001-starryear-abstract-quarter` 文件夹复制到 Codex skills 目录，例如 `~/.codex/skills/`。
2. 开启新的 Codex 对话并上传一张照片。
3. 提出需求：

   > 使用 `001-starryear-abstract-quarter`，把这张照片制作成上方原图、下方三幅统一象牙留白风格但构成不同的抽象作品。

4. Skill 将分别生成凝聚母题、关系漂移和物理余像；辨识度按照片自适应形成凝聚、拆解与释放的节奏，最后再与真实原图裁切确定性拼接。

### 方式二：作为提示词直接使用

| 语言 | 文件 |
| :---: | :--- |
| 🇨🇳 中文 | [references/001-starryear-abstract-quarter-prompt.zh-CN.md](references/001-starryear-abstract-quarter-prompt.zh-CN.md) |
| 🇬🇧 English | [references/001-starryear-abstract-quarter-prompt.en.md](references/001-starryear-abstract-quarter-prompt.en.md) |

---

## 🎛️ 可自由调整的部分

| 参数 | 说明 |
| :--- | :--- |
| **输出尺寸** | 默认 1600 × 3200 px；可换成其他尺寸，但总画布必须为 1:2，四联必须等高且每联为 2:1。 |
| **凝聚母题尺度** | 后三联主体统一略微收小；第二联母题默认占宽 64%–84%、占高 47%–68%，整体重心位于画面中心，并与第三、第四联保持相近视觉尺度。 |
| **辨识度节奏** | 默认采用“主导骨架清晰 → 关系拆散 → 姿态重新释放”；第四联可恢复一个来源动作或方向性轮廓，但不恢复摄影细节。 |
| **关系漂移强度** | 第三联默认只做一次拆分重接、错位对齐、孔隙嵌套、减除或节奏位移，并保留空间节奏与一个间接身份锚点。 |
| **物理余像强度** | 第四联默认只设一个主导物理异想，可在悬浮、重力反转、液化、内外互换、向上释放或自我穿越之间按原图选择；允许来源物象的强烈姿态参与变化。 |
| **透光有机模式** | 仅在逆光穿透薄材质主导原图时启用；主体占幅可收至宽 58%–76%、高 40%–60%，采用平整透明色面与几何结构线，簇状标记保持极少，避免重新滑向水墨。 |
| **原图裁切** | 默认采用损失最小的 2:1 裁切；若关键主体会被破坏，可在用户同意后使用克制的边缘扩展。 |

---

## 💡 核心原则

1. **证据先于风格** — 第一联必须来自真实原图像素；后三联的重要形状、色彩与材质都能追溯到原图。
2. **同语法，辨识度有节奏** — 第三、第四联沿用第二联的象牙背景、来源色板、简化平面块面、结构线、哑光表面与相近尺度；辨识度可以高—低—高变化。
3. **凝聚—漂移—释放** — 第二联保留有力骨架，第三联拆解关系，第四联以更自由的方向性姿态重新唤回来源。
4. **转译先于消除** — 保存比例、方向、节奏、遮挡、密度与留白；允许识别来源，但不缩画、机械描摹或写实重绘。
5. **确定性合成** — 分别生成后三联，最后再与原图证据联拼接，禁止让生成模型一次性重绘整张四联。
6. **四项平衡** — 超现实来自自洽的不可能关系，抽象来自非写实转译，简约来自克制的元素与留白，艺术性来自构图张力、节奏和情绪判断。

---

## 📁 内容结构

```text
001-starryear-abstract-quarter/
├── README.md
├── LICENSE.md
├── SKILL.md
├── agents/openai.yaml
├── references/
│   ├── 001-starryear-abstract-quarter-prompt.zh-CN.md
│   └── 001-starryear-abstract-quarter-prompt.en.md
└── assets/examples/
```

> ⚠️ `assets/examples/` 只包含 Starryear年 已明确认可的示例。示例只用于说明方法边界，不得把其题材、色板或构图当作其他输入的模板。

---

## 📄 许可证

本项目采用 [LICENSE.md](./LICENSE.md) 中规定的使用条款。

---

<div align="center">

**如果这个项目对你有帮助，欢迎 Star ⭐ 支持！**

</div>
