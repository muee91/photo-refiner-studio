# Prompt templates

## Base edit

```text
Use case: identity-preserve
Asset type: photograph base for high-resolution refinement
Input image: authoritative edit target
Primary request: apply <preset or custom prompt>
Composition/framing: <aspect ratio and crop behavior>
Constraints: preserve exact identity, gaze, pose, hands, anatomy, clothing construction, key props, and scene narrative
Preset avoid: <resolved_prompt.avoid>
Avoid: changed identity, changed pose, extra fingers, fused hands, malformed props, duplicated objects, plastic skin, text, logo, border, watermark
```

Always populate the template from the frozen `resolved_prompt` object in `job.json`. A preset id by itself is not a usable generation prompt.

## Two-reference detail tile

```text
Use case: compositing
Asset type: registration-ready high-resolution <region> patch
Input images: Image 1 is the authoritative original-camera reference for authentic <identity, anatomy, or material>. Image 2 is authoritative for exact crop, geometry, scale, pose, lighting, color grade, and pixel registration.
Primary request: re-render Image 2 at maximum photorealistic <region> detail while keeping its exact composition and major edges.
Constraints: one coherent region; preserve target position and silhouette; registration-ready
Avoid: doubled edges, changed anatomy, broken patterns, altered crop, pasted seams, ghosting
```

## Geometry-locked retry

Use only after a two-reference patch fails the registration gate.

```text
Use case: identity-preserve
Asset type: geometry-locked detail enhancement patch
Input image: sole authoritative edit target
Primary request: enhance only existing micro-detail and apparent resolution. Preserve every structural feature and exact pixel position.
Composition/framing: identical crop, scale, pose, geometry, and background; no zoom, shift, rotation, or recrop
Avoid: reinterpretation, double features, shifted edges, altered anatomy, excessive sharpening, changed composition
```
