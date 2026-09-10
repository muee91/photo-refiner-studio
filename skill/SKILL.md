---
name: photo-refiner
description: Refine one or many photographs with configurable looks, custom prompts, aspect ratios, output sizes, high-detail subject or texture tiles, registration, and seam-aware blending. Use for photorealistic retouching, scene-detail recovery, or batch look matching across portraits, clothing, landscapes, and other photographic subjects; do not use for illustrations or unrestricted scene redesign.
---

# Photo Refiner

Create a polished bitmap deliverable while preserving the source composition, subject identity, scene structure, important textures, and source ownership. Use the built-in image generation tool for generative edits and the bundled scripts for deterministic preparation, registration, blending, and output sizing. Cinematic looks such as `eastern-twilight` are optional presets, not a requirement; the same workflow applies to natural landscapes, architecture, clothing, objects, and portraits.

## Initialize the job

Do not start image generation or create the job manifest until the user has seen and confirmed an initialization summary. Even when the request includes a prompt, present the resolved settings first and wait for confirmation (the user may reply `按默认开始` to accept all defaults).

First establish that this turn contains at least one usable source photograph: an attached photograph or an existing local image path supplied by the user. A folder path or the workspace directory is not a source photograph; resolve it to exact image files before initializing. If there is no source photograph yet, ask the user to attach a photo or provide its absolute path and stop. Do not inspect for the settings panel, open the panel, print the text settings menu, create a job, or infer a source count of zero. A screenshot of Skill documentation is not a source photograph for a refinement job. If a pasted path contains `\\_`, try the unescaped spelling only when that exact path exists; never invent a renamed folder.

After a source photograph is established, inspect the available tool registry for `mcp__photoRefinerStudio__open_photo_refiner_settings` or any tool whose final name is `open_photo_refiner_settings`. When found, calling it is mandatory: pass the positive known source count, stop after the tool result, and let the user edit and submit the native Photo Refiner Studio panel. Do not print a parallel text menu. Resume only after the panel produces a `confirmationPath`, then initialize with `scripts/init_job.py <sources...> --confirmation-file <confirmationPath>`. Do not ask the same questions again and do not call `submit_photo_refiner_settings` on the user's behalf.

Do not infer that the panel tool is unavailable merely because it was not automatically suggested. Text fallback is permitted only after the registry check finds no matching tool or an attempted call returns an explicit unavailable or startup error. When the plugin is installed but a desktop task cannot see the tool, tell the user to restart Codex and start a fresh task; do not silently substitute the text menu.

Before the first job in an environment, run `scripts/check_dependencies.py`. If Pillow, NumPy, PyYAML, OpenCV, or SIFT support is missing, report the missing runtime capability and stop before creating a job; do not silently install packages without authorization.

If the host exposes a native structured-form interaction, use one form for this intake: single-select controls for workflow, preset, aspect ratio, resolution, detail mode, consistency, and output format; a text area for a custom prompt; and a toggle or single-select for keeping intermediates. The form must include a visible `custom` preset choice that reveals or accepts the custom prompt. Do not emit invented HTML or claim that a Markdown `<details>` block is a real control when the host does not support it. If no native form is available, use the compact text menu below and accept edits such as `2=自然电影，4=4k，提示词=...`.

Keep this intake compact so it does not flood the conversation:

1. Show a numbered settings menu with the current value and a short plain-language explanation.
2. Read preset names and `summary_zh` directly from `references/presets.yaml`; do not invent or cache a separate list. Show one-line summaries only in the menu.
3. In text fallback, never emit raw HTML such as `<details>`. Show only `完整提示词：回复“查看提示词”` and provide the selected preset's full `prompt` and `avoid` in a separate reply on request. For `custom`, echo the custom prompt only when the user asks to review it.
4. Ask the user to confirm or change any of: panel mode (simple/pro), workflow, preset/custom prompt, aspect ratio, framing behavior, resolution, execution mode, batch consistency, detail mode, output format, and whether to keep intermediates.
5. Only after confirmation, resolve the values below, run `scripts/init_job.py`, and begin image work. Record exactly those confirmed values in `job.json`.

Suggested compact intake:

```text
开始前请确认设置（回复“按默认开始”或直接修改编号）：
1. 工作流：single / batch（按输入数量推断）
2. 风格：<preset name> — <one-line summary>
3. 画幅：original
4. 构图：preserve（改变比例时需选择 crop / outpaint / contain）
5. 分辨率：source-width
6. 细节：adaptive
7. 批量一致性：balanced（仅 batch 生效）
8. 输出：PNG；保留中间文件：否
```

When a user changes one item, repeat only the changed item and the final compact summary; do not resend unrelated full prompts.

- `workflow`: infer `single` or `batch` from the number of sources.
- `ui_mode`: default `simple`; keep the first interaction focused on preset, semantic strength, execution mode, resolution, the unified prompt library, and the live summary. The library shows built-in prompts beside user-authored prompts; built-ins are reusable but not editable or deletable, while custom prompts are editable and deletable. Subject recognition, face/hair/clothing priority, patch sizing, and resolution-aware detail allocation are internal defaults and must not become additional simple-mode decisions. Only show detailed color, portrait, body, clothing, background, detail, batch, and full-prompt controls when the user switches to `pro`. This changes presentation only and must not discard hidden values.
- `preset`: default `eastern-twilight`; show the preset summary before confirmation and allow `custom` with user prompt text.
- `style_strength`: default `80`. This is the strong-but-controlled cinematic default intended to reproduce the initial visible Eastern Twilight look. `0–24` is minimal polish, `25–49` subtle, `50–74` clearly visible, `75–89` strong cinematic, and `90–100` bold redesign with higher identity, texture, and scene-drift risk. Do not represent this value only as a number: apply the `style_execution_intent` emitted by `build_edit_prompt.py`.
- `aspect_ratio`: default `original`; support `16:9`, `3:2`, `4:5`, `9:16`, or custom.
- `framing`: default `preserve`; when changing aspect ratio require `crop`, `outpaint`, or `contain` rather than silently stretching.
- `resolution`: default `source-width`; simple mode exposes only `source-width` (原图尺寸) and `4k`. `preview` remains accepted only for legacy confirmed jobs.
- `delivery_mode`: default `preview-first`; for a single image, generate the Image 2.5 base effect image and wait for the user to approve it before high-resolution detail recovery. `one-click` skips this stop and completes the quality-gated recovery path in one run. Batch jobs retain master-frame approval as their style checkpoint. The base effect image is never presented as native-resolution final output.
- `batch.consistency`: default `balanced`; support `strict`, `balanced`, or `creative`.
- `detail.mode`: default `adaptive`; support `base-only`, `face`, or explicit tiles.
- `detail.patch_scope`: default `head-and-face`, interpreted as a person-priority plan for portrait and classical-costume photography. Create separate regions for costume/body structure, head/hair/ornaments, and the tighter complete-face tile including chin. `face-only` is an advanced opt-out; `custom` requires the user to specify the regions. Never let a face crop be the only source of hair or costume detail.
- `output_format`: default `jpg`; optionally deliver PNG or both in professional mode.

Read [references/config-schema.md](references/config-schema.md) for full settings. Read [references/presets.yaml](references/presets.yaml) and [references/prompts.md](references/prompts.md) when composing prompts.

### Subject-aware recommendation before intake

After a source photograph is established, inspect the visible image before opening the settings panel. Read [references/subject-routing.md](references/subject-routing.md), classify the broad subject and lighting cues, then recommend one starting preset plus two or three creative directions. Directions may be combinations not present in the preset catalog, such as “雨后宫墙 + 低饱和朱砂反光”, “时间凝滞的丝绸空气”, or “月下水面倒影与人物轮廓互相呼应”. For an ancient-costume or classical portrait, mention that costume structure, hair/ornaments, and face are prioritized. Pass the short recommendation, suggested preset, and editable direction cards to `open_photo_refiner_settings`; do not start generation or create a job during this analysis. The user can choose a direction or write freely in the panel, so recommendations are guidance rather than an automatic override.

Run `scripts/init_job.py --confirmed` so every run gets a separate directory and manifest. Pass exact image-file paths, never a photo folder or the current workspace directory; the initializer rejects directories with a diagnostic instead of allowing a low-level `ENOENT/stat` failure. Never scatter generated files beside a photo collection. Never move, overwrite, or delete source photographs. Every deterministic image script must use a distinct output path inside the job directory.

For an interactive intake, use only the validated confirmation file emitted by Photo Refiner Studio. For text fallback, pass the preset explicitly (for example, `--preset eastern-twilight --confirmed`); never rely on a script default. If the user chooses `custom`, pass `--custom-prompt` and optional `--custom-avoid`. `init_job.py` rejects unknown presets and snapshots the resolved prompt, avoid text, preset version, and hash. Before every image-generation call, read `resolved_prompt.prompt`, `resolved_prompt.avoid`, and `retouch` from the confirmed `job.json`; never send only the preset name. Generate the deterministic final edit brief with `scripts/build_edit_prompt.py`. If the confirmation or frozen prompt is absent, stop and return to intake rather than generating.

## Base pass

1. Normalize every local source with `scripts/prepare_source.py`, then inspect it with `view_image` before editing.
2. Advance the job to `prepared` with `scripts/update_job.py`. Build the base prompt from the frozen resolved prompt plus explicit invariants. Treat the source as the edit target.
3. Generate the requested aspect ratio while preserving identity, gaze, pose, hands, clothing construction, and key props unless explicitly changed. At the default Eastern Twilight strength of `80`, the base pass must visibly establish cyan-green shadow separation, restrained warm sky light, humid haze, lifted blacks, and gentle halation; a near-identical retouch is not an accepted base result.
4. Save the base in the job directory. For a single `preview-first` job, show this base effect image and stop at `base_generated`; do not upscale, crop, regenerate face/clothing tiles, or blend until the user explicitly approves it. Record that approval with `scripts/update_job.py <job.json> --approve-base-preview`. For batch, retain the existing master-frame approval gate instead.
5. For `one-click`, or after a recorded base-preview approval, upscale the accepted base deterministically to the working canvas before detail passes.

After each accepted stage, use `scripts/update_job.py` to advance `initialized -> prepared -> base_generated -> details_processed -> completed` and record generated artifacts. A `base-only` job may advance from `base_generated` directly to `completed`. Record `failed` only for an actual terminal failure, not for a rejected optional tile when the clean base remains deliverable.

The built-in generator may return less than 4K and may not expose a seed. Do not call a resized file native 4K detail. High-resolution fidelity comes from focused detail passes and deterministic final sizing.

## Adaptive detail passes

Choose detail priorities from visible content. For portraits, prioritize face and hair ornaments, hands and held objects, clothing construction and embroidery, then important props. For landscapes, prioritize terrain boundaries, foliage, water, clouds, atmospheric layers, and architecture while preserving natural repetition and scene geometry. Do not run face-specific passes when no meaningful face is present.

For each region:

1. Extract an exact target crop from the clean working canvas with `scripts/crop_tile.py`. For the default head-and-face plan, use a large head tile plus a separate face tile. The face tile must use `--face-tight --face-safe` (or equivalent tight framing): the face should occupy roughly 60–80% of the patch height, while retaining forehead, cheeks, jawline, chin, and a narrow transition-skin margin. Do not spend most of the face tile on hair, flowers, jewelry, or background.
2. When available, extract a larger original-camera crop as the authoritative identity, anatomy, or material reference.
3. Generate a square registration-ready patch. The target controls geometry, scale, pose, lighting, and pixel placement. The original controls authentic identity or material detail.
4. Register and blend with `scripts/register_blend.py`. Never paste by guessed coordinates or manual facial affine points.
5. Apply broad tiles before specific tiles: costume/body structure first, head/hair and ornaments second, face last. For classical-costume photography, treat embroidery, collar, sleeves, waist, hem, drape, and fabric weave as identity-bearing subject detail, not background texture. The default plan must retain a small overlap between head and face for a soft transition, but the face tile must not cross-cut the main hair mass.

## Quality gate and retry

Read [references/quality-gates.md](references/quality-gates.md) before blending.

- Default gate: at least 40 RANSAC inliers and inlier ratio at least `0.75`.
- Reject double features, changed anatomy, broken embroidery, changed grip, duplicated cords, or visible seams even when numeric registration passes. Reject a face tile if the jawline or chin is missing, soft relative to the rest of the face, or lies on/near the crop edge; the face tile must include its full visible outline plus transition skin.
- When a two-reference face patch fails, retry once using the target crop alone with geometry-locked enhancement.
- When retry fails, do not blend. Preserve the clean base and report the rejected tile.
- Maximum two generation attempts per tile unless the user asks for more.

Numeric registration proves alignment, not identity preservation. Compare the face with the original and state any remaining identity drift.

## Batch consistency

For `batch`, select one approved master frame. Every image must refer to the same master frame, identity reference, prompt version, palette targets, and effect strengths. Never chain each result from the previous result.

Generate the proposed master first, show it to the user, and wait for explicit approval before processing the remaining images. Record that approval with `scripts/update_job.py --approve-master --master-frame <path>`. The state helper blocks a batch from advancing past `base_generated` until this approval is recorded.

- `strict`: deterministic grading first; minimal generative regions.
- `balanced`: shared master look with adaptive backgrounds and detail tiles; default.
- `creative`: lock identity and core palette while allowing environmental variation.

A shared prompt alone does not guarantee consistency because generation is stochastic.

## Deliver and report

Use `scripts/resize_output.py` for exact final dimensions. It rejects aspect-ratio mismatches by default. Use `--fit cover` or `--fit contain` only when the user confirmed that framing behavior; use `--fit stretch` only for an explicit request to distort. Perform generative outpainting before resizing. When OpenCV compositing stripped color metadata, pass the normalized source through `--icc-source` to restore its ICC profile. For 16:9 at an original width of 7008 pixels, use `7008x3942`; use `7008x4672` only for 3:2 or explicit outpainting.

In Codex Desktop, present each final bitmap inline before the written report with Markdown image syntax and its absolute local path, for example `![最终成片](/absolute/job/outputs/final.png)`. Do not make a clickable file URL the primary presentation. If there are multiple variants, render the selected final first and label alternatives clearly. Then report absolute paths, dimensions, formats and sizes; preset or custom prompt; registration metrics and retries; evidence type; and remaining identity, anatomy, texture, seam, or non-native-upscaling risks.
