# Subject-aware recommendation

Use this reference after a source photograph is established and before opening the settings panel. The goal is to recommend a useful starting look without adding more user decisions.

## What to inspect

- Subject type: portrait, classical/ancient-costume portrait, landscape, architecture, object, or mixed scene.
- Costume and cultural cues: hanfu, hair ornaments, jewelry, sleeves, embroidery, lanterns, pavilions, gardens, water, or period props.
- Existing light: daylight, golden hour, twilight, moonlight, lantern/practical light, studio light, or mixed light.
- Composition risk: face size, face occlusion, hands, flowing sleeves, fine embroidery, reflective props, and busy background.

## Routing defaults

- Classical-costume portrait with warm light or lanterns: recommend `warm-gold-ancient`.
- Classical-costume portrait with strong cyan/green shadows or twilight atmosphere: recommend `eastern-twilight`.
- Classical-costume portrait in cool night or moonlight: recommend `moonlit-cyan`.
- Classical-costume portrait when the user asks for dreamlike, suspended-time, otherworldly,
  poetic, or mildly surreal treatment: recommend `surreal-eastern`.
- Contemporary or editorial portrait with natural light: recommend `natural-cinematic`.
- Landscape: recommend `natural-landscape`, `golden-hour-landscape`, or `misty-mountains` according to the observed light and terrain.
- Architecture: recommend `clean-architecture`.

## Recommendation format

Show one concise reason before the settings panel, for example:

`识别为古风人物肖像：服饰、发饰和暖色实景光是主体重点，建议“Warm Gold Ancient”；默认会优先恢复服装结构、头发/发饰和人脸。`

Add two or three optional creative directions after the reason. Each direction should have a
short Chinese name, a one-sentence visual description, and an editable prompt draft. Directions
are not limited to named presets and should combine observed subject, light, setting, material,
and atmosphere. Prefer concrete visual ideas over abstract labels such as “高级感” or “大片感”.
Always keep an identity-preserving constraint in the draft unless the user explicitly asks for a
full redesign.

Do not claim certainty about cultural identity or historical accuracy. Say “看起来像” or “按画面特征判断” when appropriate. Do not silently change the user's confirmed preset; pass the recommendation as `suggestedPreset` and let the user change it in the panel. The recommended preset's `default_strength` is the preferred starting strength. If no reliable subject/light recommendation can be made, use `natural-cinematic` as the neutral fallback rather than defaulting to `eastern-twilight`.

## Surreal boundary

Treat “超现实” as a controlled atmosphere layer by default, not a request to replace the
person or rebuild the scene. Keep identity, anatomy, costume construction, props and major
geometry locked. Only recommend stronger surreal transformation when the user explicitly asks
for redesign, impossible architecture, altered scale, or fantasy-world reconstruction.
