<div align="center">

# 🖋️ 【S-005】Starryear-Ink 星年水墨

**让真实照片穿过立体翻页与湿润彩墨，释放成一张连续的纸本编辑艺术。**

![Codex Skill](https://img.shields.io/badge/Codex-Skill-000000?style=for-the-badge&logo=openai&logoColor=white)
[![Usage](https://img.shields.io/badge/Usage-Personal%20%26%20Non--commercial-lightgrey?style=for-the-badge)](./LICENSE.md)
![Language](https://img.shields.io/badge/🌐_中文-English-blue?style=for-the-badge)

</div>

---

## ⚠️ 声明

> **仅限个人学习、非营利研究与非商业创作。** 任何商业使用均须事先取得 Starryear年 的书面许可。分享作品时，欢迎标注来源并 **@Starryear年**。

## 📖 关于本项目

Starryear-Ink 把一张照片组织成单张 2:3 竖版纸本作品：顶部保留不可重绘的真实照片证据，中部让干性印刷记忆落在有纸厚、卷边、背面色与投影的立体翻页上，底部释放为仍在渗化、回流与积染的湿润彩墨余像。数量、节奏、轴线、留白与源色贯穿全图。

- ✅ 上部使用真实源图像素，仅允许裁切、缩放、定位与极轻整体调和
- ✅ 立体翻页与湿墨真正交互：墨迹跨页、入折谷、透纸背并在下一层重新渗出
- ❌ 不做整图水墨滤镜、干涩水彩花卉、平面数码飘带、人物残影或等分三联画

> 📝 本 Skill 包含语义对齐的完整中文与英文提示词。

## 🖼️ 示例作品

> 测试通过后补充。当前 `assets/examples/` 保持为空，不放置参考图、测试图或临时生成图。

## 📋 目录

- [使用方法](#-使用方法)
- [可自由调整的部分](#️-可自由调整的部分)
- [核心原则](#-核心原则)
- [内容结构](#-内容结构)
- [许可证](#-许可证)

## 🚀 使用方法

### 方式一：作为 Codex Skill 使用

1. 将整个 `starryear-ink` 文件夹复制到 Codex skills 目录，例如 `~/.codex/skills/`。
2. 新建 Codex 对话并上传一张自己的照片。
3. 输入：`使用 $starryear-ink，把这张照片做成星年水墨。`
4. Skill 输出一张 2:3 竖版成品，不输出分析或候选方案。

### 方式二：作为提示词直接使用

| 语言 | 文件 |
| :---: | :--- |
| 🇨🇳 中文 | [references/starryear-ink-prompt.zh-CN.md](references/starryear-ink-prompt.zh-CN.md) |
| 🇬🇧 English | [references/starryear-ink-prompt.en.md](references/starryear-ink-prompt.en.md) |

## 🎛️ 可自由调整的部分

| 参数 | 说明 |
| :--- | :--- |
| **照片占比** | 建议 26–35%，默认约 30%；不得牺牲关键证据。 |
| **文字** | 可用一条 5–16 词的场景清单，也可完全不写。 |
| **色彩释放** | 从原图抽取 2–3 个透明墨色家族，其中一个主导，其余辅助。 |
| **湿润度** | 默认约 65–75% 湿中湿、渗化、回流与积水边；余下保留飞白和干印刷骨架。 |
| **翻页立体度** | 可调卷边与页层数量，但必须保留纸厚、纤维边、背面色、遮挡和自然投影。 |
| **核心变形** | 从负形折纸、方向地形、倒影脱体、节奏跨物质中选一个；只保留一个主创意。 |

## 💡 核心原则

1. **证据不可重绘** — 上部必须是同一源文件的直接裁切，而不是 AI 近似重建。
2. **两次转译必须不同** — 中部是承载干性印刷碎片的立体翻页；底部以约七成湿润墨水释放，并在折边、页缝与纸背互相渗透。
3. **人物不得重复** — 人物只存在于上方原片；中下部禁止灰色衣料转印、矩形躯干色块或任何能拼成第二人形的残影。
4. **超现实来自原图** — 只改变真实证据的行为，不凭空加入山水、仙鹤、竹子、印章或宇宙意象。
5. **留白控制全局** — 暖象牙纸与呼吸感比装饰数量更重要。
6. **一图一个空间悖论** — 创意必须改变原图证据的空间行为，并在缩略图尺寸仍然成立。

## 📁 内容结构

```text
starryear-ink/
├── README.md
├── LICENSE.md
├── SKILL.md
├── agents/openai.yaml
├── references/
│   ├── starryear-ink-prompt.zh-CN.md
│   └── starryear-ink-prompt.en.md
└── assets/examples/
```

> ⚠️ 初版测试包中的 `assets/examples/` 必须为空。仅在 Starryear年 确认测试通过后，加入其提供或明确认可的最终成品图；不得放入参考图、测试图或临时输出。

## 📄 许可证

本项目采用 [LICENSE.md](./LICENSE.md) 中规定的使用条款。

---

<div align="center">

**如果这个项目对你有帮助，欢迎 Star ⭐ 支持！**

</div>
