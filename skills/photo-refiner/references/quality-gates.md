# Quality gates

A detail patch is accepted only when it passes **all** relevant gates below. Passing registration alone never proves that the patch is a valid recovery.

## 1. Effective-detail budget

Before generation, run `scripts/pixel_budget.py` against the planned crop and final subject size. A patch must provide enough effective subject pixels to justify replacing local detail in the final canvas.

Default minimum `detail_ratio` values:

- face: `0.85`
- hand: `0.75`
- head/hair/ornaments: `0.65`
- costume: `0.50`
- prop: `0.50`
- architecture: `0.50`
- background: `0.30`
- generic: `0.50`

When the budget fails, first tighten the crop so the important subject occupies more of the generated patch. If the crop is already tight, request a larger patch or reduce the final local scale. Do not accept a low-ratio patch merely because the bitmap dimensions are large.

## 2. Registration

Default acceptance requires at least 40 RANSAC inliers and an inlier ratio of at least `0.75` after the SIFT ratio test. For large costume or prop tiles, prefer at least 100 inliers. The target tile must match the exact LOOK MASTER crop, median reprojection error must not exceed 3 pixels, p95 reprojection error must not exceed 8 pixels, and warped-patch coverage must be at least 90% unless a stricter job-specific gate is selected.

Registration model defaults are region-aware:

- face -> `similarity`
- head/hair/ornaments -> `affine`
- hand -> `affine`
- costume -> `homography`
- prop -> `homography`
- architecture -> `homography`
- background/generic -> `homography`

Do not promote a failed face similarity registration to homography merely to force acceptance. A face that requires perspective warping to match the target is an identity/geometry warning and should normally be regenerated.

Registration reports must include target-crop delta, model, inlier metrics, reprojection errors, projected-area ratio, transform plausibility, and coverage. Reject reflected/negative-determinant transforms, implausible condition numbers, non-convex projected corners, or excessive area change even when inlier counts pass. Invalid warp areas must remain transparent to blending.

## 3. SOURCE MASTER structure / identity

Reject regardless of registration score for double eyes, lashes, lips, fingers, contours, cords, or seams; altered identity, gaze, expression, hand pose, finger count, garment construction, broken embroidery, shifted props, malformed weave, invented architecture/terrain, or factual scene drift.

For a face tile, reject if the forehead, temples, cheeks, jawline, chin, or surrounding transition skin is absent, if the chin lies at the crop edge, or if jaw/chin sharpness differs from restored facial detail. Compare feature spacing, face outline, expression and gaze with SOURCE MASTER before blend acceptance.

Face target crops must be created with `crop_tile.py --face-tight --face-safe` for the default head-and-face plan. The face should occupy about 60-80% of the patch height. If the source itself cuts off the chin, do not invent it: preserve the accepted LOOK MASTER and report the source-boundary limitation.

## 4. LOOK MASTER preservation

Once the user approves the Image 2.5 base, that image is the LOOK MASTER. Local recovery must preserve its low-frequency color, lighting, tone, atmosphere and visual style. `register_blend.py` therefore restores LOOK MASTER low-frequency content and introduces only registered patch mid/high-frequency detail.

Reject a patch if it visibly changes the approved local white balance, relights the face independently of the scene, changes approved shadow/highlight separation, or creates a local saturation/contrast discontinuity.

## 5. Seam / sharpness continuity

Reject visible crop seams, halos, hard texture boundaries, local over-sharpening, or a patch whose sharpness is inconsistent with adjacent accepted content. Broad tiles must be applied before specific tiles: costume/body structure first, head/hair/ornaments second, face last.

For portraits in historical or classical costume, the garment is part of the subject. Preserve silhouette, collar, sleeves, waist, hem, embroidery, weave and drape. Reject clothing patches that flatten intentional folds, break embroidery continuity, or change garment construction.

## 6. Optional depth-order gate

Apply this gate only when the active detail plan contains an **active `depth_guard`** produced by `apply_depth_prior.py`. Absence of depth metadata never fails a job.

Depth is advisory. SOURCE MASTER remains the geometry authority. Reject a guarded patch when it visibly:

- moves an object that was in front of the subject behind it, or vice versa;
- reveals skin, clothing, hair, or object surfaces that were genuinely occluded;
- erases a legitimate foreground crossing such as a railing, branch, veil, sleeve, or prop;
- changes hand/prop front-back ordering relative to the torso;
- creates a hard binary blur boundary when the requested depth-of-field should transition gradually;
- collapses a requested atmospheric-perspective gradient into a flat mask-like separation.

When `depth_guard.merge_policy` is `do-not-merge-across-depth-boundary`, do not broaden that patch crop across the named discontinuity merely to reduce generation count. When it is `broad-merge-safe`, treat that only as permission to consider a broad crop; it is never a requirement to merge.

Do not fail a patch solely because monocular depth inference disagrees with clear visible SOURCE MASTER evidence. Mirrors, reflections, water, glass, sky, long-lens compression, and ambiguous transparency are common depth failure modes.

## Retry path

```text
two-reference patch
  -> pixel budget passes
  -> registration + structure/identity + LOOK MASTER + optional depth-order + seam gates pass: blend
  -> fails generation/structure: geometry-locked target-only retry
      -> all gates pass: blend and report fallback
      -> fails: reject, preserve clean LOOK MASTER, and report
```

Maximum two generation attempts per tile unless the user explicitly asks for more. Always blend from a clean accepted state; never build on a rejected composite.

## Additions retained from earlier contracts

- A passing registration may optionally use `--blend-mask` to reduce rectangular seams; this is a blending aid, not permission to weaken identity or geometry checks.
- The planner must treat the normal generation count as a **soft budget**, score candidate value/scale, and prefer broad regions over many small regions. Reject plans that create micro-patches for eyes, mouth, ears, sleeves, or single ornaments by default. A balanced plan normally contains 0–3 patches, but may expand to 4–6 only when the remaining regions exceed the overflow-value threshold and still pass Pixel Budget. Six is the balanced hard ceiling.
- If a broad `head` patch adequately covers hair, ears, and ornaments, do not split it into more generated patches merely to improve the mask.
- Optional depth metadata may tighten merge safety or visual review, but it does **not** increase the patch budget by itself.

## Optional landmark structure gate

When reliable facial landmarks are already available from the active backend/vision pass, run `landmark_identity_gate.py` before accepting a face patch. The default normalized RMSE threshold is `0.055` and the worst-point threshold is `0.10`. Failure rejects the face patch even if SIFT/similarity registration passes. Absence of landmarks does not fail the job; visual identity review remains mandatory.

## Multiband fusion v2

Registration geometry coverage and blend-mask coverage are separate metrics. A small lightweight mask must never weaken the registration coverage gate. LOOK MASTER owns the low band and most of the mid band; patch contribution is strongest in the high band.
