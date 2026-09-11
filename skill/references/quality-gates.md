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

## Retry path

```text
two-reference patch
  -> pixel budget passes
  -> registration + structure/identity + LOOK MASTER + seam gates pass: blend
  -> fails generation/structure: geometry-locked target-only retry
      -> all gates pass: blend and report fallback
      -> fails: reject, preserve clean LOOK MASTER, and report
```

Maximum two generation attempts per tile unless the user explicitly asks for more. Always blend from a clean accepted state; never build on a rejected composite.
