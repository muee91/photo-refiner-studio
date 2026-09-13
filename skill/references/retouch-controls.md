# Retouch controls

Photo Refiner Studio stores confirmed numeric controls under `job.json.retouch`. Use `scripts/build_edit_prompt.py` to convert them into the generation brief. Zero means no requested change. Do not infer an enabled beauty or body control from the photograph alone.

## Safety and fidelity

- `portrait.enabled` and `body.enabled` default to false. When false, their dependent values must be zero.
- Face and body geometry controls are capped at 40. Treat 1–10 as subtle, 11–20 as moderate, and 21–40 as strong. Preserve identity, expression, joints, hands, garment construction, background lines, and contact shadows at every strength.
- Beauty controls must retain pores and real skin texture. Do not erase permanent identity marks unless specifically requested.
- Wrinkle reduction removes distracting compression folds, not intentional pleats, seams, embroidery, drape, fabric weave, or garment silhouette.
- Background cleanup may remove small distractions only. Do not remove meaningful props, people, text, architecture, terrain, or narrative elements without an explicit request.
- Sky, foliage, and architectural enhancement preserve original geometry and avoid repeated textures, invented objects, halos, and HDR artifacts.

## Implementation routing

- Global tonal controls and final resizing are deterministic where practical.
- Blemish removal, wrinkle reduction, distraction removal, body geometry, and semantic background changes require localized generative patches followed by registration and quality gates.
- Apply broad non-identity changes first, clothing and body geometry next, and the face last.
- Any generated face/body/clothing patch that fails registration or visual identity/anatomy review is rejected; retain the last clean accepted state.
