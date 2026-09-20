---
name: 011-starryear-absurd-triptych
description: Transform one user photograph into a vertical three-part artwork made from three horizontal 16:9 panels, with a source-faithful cropped evidence image in the middle and two source-derived absurd stages above and below. Use for S011、竖版荒诞三联、原图在中间、三张横版16:9拼成16:27. Do not use for ordinary filters, unrelated fantasy scenes, dense collage, or layouts that redraw the evidence image.
metadata:
  author: "Starryear年"
  version: "0.1.1-test-candidate"
  license: "Starryear Personal and Non-commercial Use License"
---

# S011 Starryear-Absurd-Triptych丨星年·荒诞三联

Create one vertically stacked triptych from exactly one authorized photograph: `Scale Slip → Evidence → Impossible Return`. The top and bottom are separately generated horizontal 16:9 scenes derived only from the photograph. The middle uses the unchanged source pixels, cropped only as needed to a horizontal 16:9 frame. Stack the three equal 16:9 panels vertically to produce one exact 16:27 artwork.

## Workflow

1. Inspect the source once. Lock the decisive subjects, meaningful count, identity cues, gesture, contact relation, scale references, light, palette, and quietest source color.
2. Read the Chinese full prompt by default, or the English prompt when requested. Internally form one absurd sentence using only source-derived nouns and one impossible verb.
3. Generate the top horizontal 16:9 panel as a sparse scale slip with 45–70% perceptual negative space and one clearly grounded impossible relation.
4. Keep the middle evidence image pixel-authentic. Permit only EXIF orientation correction, proportional scaling, and the conservative center crop required to fill a horizontal 16:9 frame. Never redraw, retouch, recolor, outpaint, remove, or replace anything.
5. Generate the bottom horizontal 16:9 panel as the closure of the same sentence: reverse the carrying relation or form one readable causal loop. Do not add a new symbol or subplot.
6. Assemble deterministically at one shared width with no gaps: top generated panel, middle 16:9 cropped evidence, bottom generated panel. The three equal-height panels produce an exact 16:27 canvas. Use no divider or outer frame.
7. Return one RGB/sRGB PNG. Review once; regenerate only one clearly failed generated panel once.

## Guardrails

- Both generated panels must trace all important forms and colors to the source; invent relations, not unrelated objects.
- Each generated panel is horizontal 16:9, contains at most three actor groups, one focal relation, one low contact cue, and broad quiet negative space.
- Protect faces, species, meaningful counts, clothing, object identity, and recognizable silhouettes when they carry recognition.
- Prefer matte practical-set or restrained puppet-theatre realism. Avoid dense scenery, generic beige, dirty paper, heavy grain, plastic gloss, dramatic glow, floating stickers, body distortion, horror, text, logos, and watermarks.
- The middle evidence must be a horizontal 16:9 crop made only from original source pixels. Do not regenerate, outpaint, or pad it.

## Reference Prompt

Read the appropriate full prompt before producing the image:

- Chinese: [references/011-starryear-absurd-triptych-prompt.zh-CN.md](references/011-starryear-absurd-triptych-prompt.zh-CN.md)
- English: [references/011-starryear-absurd-triptych-prompt.en.md](references/011-starryear-absurd-triptych-prompt.en.md)

Use [scripts/assemble_triptych.py](scripts/assemble_triptych.py) for deterministic stacking after the two generated panels are ready.

Keep [assets/examples](assets/examples) empty during drafting and testing. After Starryear年 explicitly accepts the tested Skill, add only final images supplied or approved by the user; treat them as examples only and never reuse their subjects, colors, or composition unless the user supplies that exact image.
