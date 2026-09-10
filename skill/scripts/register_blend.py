#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def smoothstep(value: np.ndarray) -> np.ndarray:
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Register a generated detail patch and feather-blend it into a base image.")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True, help="Exact crop from the base image")
    parser.add_argument("--patch", type=Path, required=True, help="Generated high-detail patch")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    parser.add_argument("--min-ratio", type=float, default=0.75)
    parser.add_argument("--min-inliers", type=int, default=40)
    parser.add_argument("--feather", type=float, default=80.0)
    parser.add_argument("--ratio-test", type=float, default=0.70)
    parser.add_argument("--target-tolerance", type=float, default=1.0)
    parser.add_argument("--min-coverage", type=float, default=0.90)
    parser.add_argument("--max-median-error", type=float, default=3.0)
    parser.add_argument("--max-p95-error", type=float, default=8.0)
    args = parser.parse_args()

    base_path = args.base.expanduser().resolve()
    target_path = args.target.expanduser().resolve()
    patch_path = args.patch.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output in {base_path, target_path, patch_path}:
        raise SystemExit("Refusing to overwrite a base, target, or patch image")
    base = cv2.imread(str(base_path), cv2.IMREAD_COLOR)
    target = cv2.imread(str(target_path), cv2.IMREAD_COLOR)
    patch = cv2.imread(str(patch_path), cv2.IMREAD_COLOR)
    if base is None or target is None or patch is None:
        raise SystemExit("Could not read base, target, or patch")
    height, width = target.shape[:2]
    if args.x < 0 or args.y < 0 or args.x + width > base.shape[1] or args.y + height > base.shape[0]:
        raise SystemExit("Target placement is outside base bounds")
    expected_target = base[args.y:args.y + height, args.x:args.x + width]
    target_delta = cv2.absdiff(expected_target, target).astype(np.float32)
    target_mean_delta = float(target_delta.mean())
    target_p99_delta = float(np.percentile(target_delta, 99))
    if target_mean_delta > args.target_tolerance or target_p99_delta > max(3.0, args.target_tolerance * 3.0):
        raise SystemExit(
            f"Target is not the exact base crop at ({args.x}, {args.y}); "
            f"mean delta {target_mean_delta:.3f}, p99 delta {target_p99_delta:.3f}"
        )

    sift = cv2.SIFT_create(nfeatures=15000, contrastThreshold=0.015)
    kp_patch, desc_patch = sift.detectAndCompute(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), None)
    kp_target, desc_target = sift.detectAndCompute(cv2.cvtColor(target, cv2.COLOR_BGR2GRAY), None)
    if desc_patch is None or desc_target is None:
        raise SystemExit("Not enough image features for registration")
    pairs = cv2.BFMatcher().knnMatch(desc_patch, desc_target, k=2)
    good = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < args.ratio_test * pair[1].distance]
    if len(good) < 4:
        raise SystemExit(f"Registration rejected: only {len(good)} matches")
    src = np.float32([kp_patch[item.queryIdx].pt for item in good])
    dst = np.float32([kp_target[item.trainIdx].pt for item in good])
    transform, inlier_mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    inliers = int(inlier_mask.sum()) if inlier_mask is not None else 0
    ratio = inliers / len(good)
    report = {
        "matches": len(good),
        "inliers": inliers,
        "inlier_ratio": ratio,
        "target_mean_delta": target_mean_delta,
        "target_p99_delta": target_p99_delta,
        "accepted": False,
    }
    if transform is None or inliers < args.min_inliers or ratio < args.min_ratio:
        print(json.dumps(report, indent=2))
        raise SystemExit(2)

    inlier_flags = inlier_mask.ravel().astype(bool)
    projected_inliers = cv2.perspectiveTransform(src[inlier_flags].reshape(-1, 1, 2), transform).reshape(-1, 2)
    reprojection_errors = np.linalg.norm(projected_inliers - dst[inlier_flags], axis=1)
    median_error = float(np.median(reprojection_errors))
    p95_error = float(np.percentile(reprojection_errors, 95))
    corners = np.float32(
        [[[0, 0], [patch.shape[1] - 1, 0], [patch.shape[1] - 1, patch.shape[0] - 1], [0, patch.shape[0] - 1]]]
    )
    projected_corners = cv2.perspectiveTransform(corners, transform)[0]
    projected_area = float(abs(cv2.contourArea(projected_corners)))
    target_area = float(width * height)
    area_ratio = projected_area / target_area
    if (
        not np.isfinite(projected_corners).all()
        or not cv2.isContourConvex(projected_corners.astype(np.float32))
        or area_ratio < 0.25
        or area_ratio > 4.0
        or median_error > args.max_median_error
        or p95_error > args.max_p95_error
    ):
        report.update(
            {
                "median_reprojection_error": median_error,
                "p95_reprojection_error": p95_error,
                "projected_area_ratio": area_ratio,
                "reason": "implausible homography",
            }
        )
        print(json.dumps(report, indent=2))
        raise SystemExit(2)

    aligned = cv2.warpPerspective(
        patch,
        transform,
        (width, height),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    ).astype(np.float32)
    patch_mask = np.full(patch.shape[:2], 255, dtype=np.uint8)
    valid_mask = cv2.warpPerspective(
        patch_mask,
        transform,
        (width, height),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    coverage = float(np.count_nonzero(valid_mask) / valid_mask.size)
    if coverage < args.min_coverage:
        report.update(
            {
                "median_reprojection_error": median_error,
                "p95_reprojection_error": p95_error,
                "projected_area_ratio": area_ratio,
                "coverage": coverage,
                "reason": "insufficient warped-patch coverage",
            }
        )
        print(json.dumps(report, indent=2))
        raise SystemExit(2)
    target_float = target.astype(np.float32)
    sigma = max(min(width, height) / 30.0, 12.0)
    aligned_low = cv2.GaussianBlur(aligned, (0, 0), sigmaX=sigma, sigmaY=sigma)
    target_low = cv2.GaussianBlur(target_float, (0, 0), sigmaX=sigma, sigmaY=sigma)
    corrected = np.clip(aligned + target_low - aligned_low, 0, 255)

    yy, xx = np.mgrid[0:height, 0:width]
    distance = np.minimum.reduce([xx, yy, width - 1 - xx, height - 1 - yy]).astype(np.float32)
    alpha = smoothstep(distance / max(args.feather, 1.0))[..., None]
    alpha *= (valid_mask.astype(np.float32) / 255.0)[..., None]
    result = base.astype(np.float32)
    region = result[args.y:args.y + height, args.x:args.x + width]
    result[args.y:args.y + height, args.x:args.x + width] = region * (1.0 - alpha) + corrected * alpha
    result = np.clip(result, 0, 255).astype(np.uint8)

    output.parent.mkdir(parents=True, exist_ok=True)
    params = [cv2.IMWRITE_PNG_COMPRESSION, 4] if output.suffix.lower() == ".png" else [cv2.IMWRITE_JPEG_QUALITY, 96]
    if not cv2.imwrite(str(output), result, params):
        raise SystemExit("Could not write output")
    report.update(
        {
            "accepted": True,
            "output": str(output),
            "transform": transform.tolist(),
            "median_reprojection_error": median_error,
            "p95_reprojection_error": p95_error,
            "projected_area_ratio": area_ratio,
            "coverage": coverage,
        }
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
