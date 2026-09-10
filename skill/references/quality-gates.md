# Quality gates

Default acceptance requires at least 40 RANSAC inliers and an inlier ratio of at least 0.75 after the SIFT ratio test. For large costume or prop tiles, prefer at least 100 inliers. The target tile must also match the exact base crop, median reprojection error must not exceed 3 pixels, p95 reprojection error must not exceed 8 pixels, and warped-patch coverage must be at least 90% unless a stricter job-specific gate is selected.

Reject regardless of registration score for double eyes, lashes, lips, fingers, contours, cords, or seams; altered identity, gaze, expression, hand pose, or finger count; broken embroidery; shifted props; malformed weave; visible crop seams; or sharpness inconsistent with the base. For a face tile, reject if the forehead, temples, cheeks, jawline, chin, or surrounding transition skin is absent from the tile, if the chin lies at the crop edge, or if jaw/chin sharpness differs from the restored facial detail.

Face target crops must be created with `crop_tile.py --face-tight --face-safe` for the default head-and-face plan. The face should occupy about 60–80% of the patch height; reject a face patch when excessive hair, flowers, jewelry, or background reduces facial occupancy below roughly half the patch. Keep the chin and a narrow transition-skin margin, but let the separate head tile carry most hair and ornament detail. Use the emitted expanded coordinates, not the original detector coordinates, for later registration. If the source photo itself cuts off the chin, do not invent it: preserve the accepted base and report that source-boundary limitation.

```text
two-reference patch
  -> passes numeric and visual gates: blend
  -> fails: geometry-locked target-only retry
      -> passes: blend and report fallback
      -> fails: reject, preserve the clean base, and report
```

Apply broad tiles before specific tiles. Apply identity-sensitive tiles such as the face last. Always blend from a clean accepted state; never build on a rejected composite.

For portraits in historical or classical costume, the garment is part of the subject: process a broad costume/body-structure tile before head and face, preserving silhouette, collar, sleeves, waist, hem, embroidery, weave, and drape. Reject clothing patches that flatten intentional folds, break embroidery continuity, or change garment construction.

Registration reports must include target-crop delta, reprojection errors, projected-area ratio, and coverage. Reject implausible or non-convex homographies even when inlier counts pass. Invalid warp areas must remain transparent to blending; never fill them with reflected patch pixels.
