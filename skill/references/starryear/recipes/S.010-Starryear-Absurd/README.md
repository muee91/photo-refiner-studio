<div align="center">

# 🎭 【S.016】Starryear-Dislocated丨星年·错位电影

**让不可能发生在原图上下，让真实证据留在中间。**

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

S011 将一张照片组织为竖向三联：上方生成“尺度滑移”，中间保留未经重绘的原图证据，下方生成同一荒诞命题的“不可能回返”。三格均为横向 16:9，中间原图只裁切不重绘，最终无缝拼成一张 16:27 作品。

- ✅ 从同一张照片发展两个稀疏、可追溯、连续递进的荒诞场景
- ✅ 无论原图横竖，中间只用真实像素裁切为横向 16:9，确定性拼接并保护原图内容
- ❌ 不制作三种滤镜、无关奇观、密集拼贴或重绘证据图

> 📝 The Skill includes the complete prompt in both **Chinese** and **English**.

---

## 🖼️ 示例作品

> 测试通过后补充。当前 `assets/examples/` 保持为空，不放置参考图、测试图或临时生成图。

---

## 📋 目录

- [使用方法](#-使用方法)
- [可自由调整的部分](#-可自由调整的部分)
- [核心原则](#-核心原则)
- [内容结构](#-内容结构)
- [许可证](#-许可证)

---

## 🚀 使用方法

### 方式一：作为 Codex Skill 使用

1. 将整个 `011-starryear-absurd-triptych` 文件夹复制到 Codex skills 目录，例如 `~/.codex/skills/`。
2. 开启新的 Codex 对话并上传一张照片。
3. 提出需求：

   > 使用 `011-starryear-absurd-triptych`，把这张照片做成原图在中间的竖版荒诞三联。

4. Skill 会生成上下两张横向 16:9 画面，把未重绘的原图裁切为横向 16:9 放在中间，并拼成一张 16:27 成品。

### 方式二：作为提示词直接使用

| 语言 | 文件 |
| :---: | :--- |
| 🇨🇳 中文 | [references/011-starryear-absurd-triptych-prompt.zh-CN.md](references/011-starryear-absurd-triptych-prompt.zh-CN.md) |
| 🇬🇧 English | [references/011-starryear-absurd-triptych-prompt.en.md](references/011-starryear-absurd-triptych-prompt.en.md) |

---

## 🎛️ 可自由调整的部分

| 参数 | 说明 |
| :--- | :--- |
| **荒诞句** | 可改变不可能动词，但名词与关键物件必须来自原图 |
| **背景源色** | 从原图选择低饱和安静色，不使用无来源模板色 |
| **输出宽度** | 至少 1536 px，推荐 2048 px 或更大；总高度固定为宽度的 27/16 |

---

## 💡 核心原则

1. **证据不重绘** — 中间格只允许方向修正、等比缩放与横向 16:9 保守裁切。
2. **上下同一句话** — 两张生成格都是横向 16:9，并以同一主体、同一不可能法则完成起势与闭环。

---

## 📁 内容结构

```text
011-starryear-absurd-triptych/
├── README.md
├── LICENSE.md
├── SKILL.md
├── agents/openai.yaml
├── scripts/assemble_triptych.py
├── references/
│   ├── 011-starryear-absurd-triptych-prompt.zh-CN.md
│   └── 011-starryear-absurd-triptych-prompt.en.md
└── assets/examples/
```

> ⚠️ 初版测试包中的 `assets/examples/` 必须为空。仅在 Starryear年 确认测试通过后，加入其提供或明确认可的最终成品图；不得放入参考图、测试图或临时输出。

---

## 📄 许可证

本项目采用 [LICENSE.md](./LICENSE.md) 中规定的使用条款。

---

<div align="center">

**如果这个项目对你有帮助，欢迎 Star ⭐ 支持！**

</div>
