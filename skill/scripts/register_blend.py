#!/usr/bin/env python3
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from job_contract import atomic_write_json


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


AUTO_MODELS = {
    "face": "similarity",
    "head": "affine",
    "hand": "affine",
    "costume": "homography",
    "prop": "homography",
    "architecture": "homography",
    "background": "homography",
    "generic": "homography",
}
STRICT_MODELS = {"face": "similarity", "head": "affine", "hand": "affine"}


def rectangles_intersect(first: dict, second: dict) -> bool:
    """Return true when two positive-area boxes share any pixels."""
    return not (
        first["x"] + first["width"] <= second["x"]
        or second["x"] + second["width"] <= first["x"]
        or first["y"] + first["height"] <= second["y"]
        or second["y"] + second["height"] <= first["y"]
    )


def smoothstep(value: np.ndarray) -> np.ndarray:
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def estimate_transform(model: str, src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray | None, np.ndarray | None]:
    if model == "homography":
        return cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if model == "affine":
        matrix, mask = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    elif model == "similarity":
        matrix, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    else:
        raise ValueError(f"Unknown registration model: {model}")
    if matrix is None:
        return None, mask
    transform = np.vstack([matrix, [0.0, 0.0, 1.0]]).astype(np.float64)
    return transform, mask


def warp_image(image: np.ndarray, transform: np.ndarray, width: int, height: int, interpolation: int) -> np.ndarray:
    if np.allclose(transform[2], [0.0, 0.0, 1.0]):
        return cv2.warpAffine(
            image,
            transform[:2],
            (width, height),
            flags=interpolation,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
    return cv2.warpPerspective(
        image,
        transform,
        (width, height),
        flags=interpolation,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def normalized_low_frequency(image: np.ndarray, valid_mask: np.ndarray, sigma: float) -> np.ndarray:
    """Blur only valid warped pixels so black warp borders do not contaminate color matching."""
    weight = valid_mask.astype(np.float32) / 255.0
    weighted = image.astype(np.float32) * weight[..., None]
    blurred_weighted = cv2.GaussianBlur(weighted, (0, 0), sigmaX=sigma, sigmaY=sigma)
    blurred_weight = cv2.GaussianBlur(weight, (0, 0), sigmaX=sigma, sigmaY=sigma)
    return blurred_weighted / np.maximum(blurred_weight[..., None], 1e-4)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register a generated detail patch and frequency-blend it into the approved LOOK MASTER canvas."
    )
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True, help="Exact crop from the approved base/LOOK MASTER canvas")
    parser.add_argument("--patch", type=Path, required=True, help="Generated high-detail patch")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    parser.add_argument("--region-type", choices=sorted(AUTO_MODELS), default="generic")
    parser.add_argument("--model", choices=["auto", "similarity", "affine", "homography"], default="auto")
    parser.add_argument("--min-ratio", type=float, default=0.75)
    parser.add_argument("--min-inliers", type=int, default=40)
    parser.add_argument("--feather", type=float, default=80.0)
    parser.add_argument("--detail-gain", type=float, default=1.0, help="Gain for patch high-frequency detail after LOOK MASTER restoration")
    parser.add_argument("--mid-detail-gain", type=float, help="Optional mid-frequency patch contribution. Defaults are region-aware and deliberately conservative.")
    parser.add_argument("--ratio-test", type=float, default=0.70)
    parser.add_argument("--blend-mask", type=Path, help="Optional grayscale mask matching the patch dimensions; used to reduce rectangular seams without adding new patch generations")
    parser.add_argument("--target-tolerance", type=float, default=1.0)
    parser.add_argument("--min-coverage", type=float, default=0.90)
    parser.add_argument("--max-median-error", type=float, default=3.0)
    parser.add_argument("--max-p95-error", type=float, default=8.0)
    parser.add_argument("--job", type=Path, help="job.json; required when recording an auditable detail/tile blend")
    parser.add_argument("--plan", type=Path, help="detail-plan.json for an ordinary/creative-safe blend receipt")
    parser.add_argument("--planner-region-index", type=int, help="Region index from --plan")
    parser.add_argument("--tile-plan", type=Path, help="tile-plan.json for an hd-master redraw blend receipt")
    parser.add_argument("--tile-index", type=int, help="Tile index from --tile-plan")
    args = parser.parse_args()

    if not 0.0 <= args.detail_gain <= 2.0:
        raise SystemExit("--detail-gain must be between 0 and 2")
    if args.region_type in STRICT_MODELS and args.model not in {"auto", STRICT_MODELS[args.region_type]}:
        raise SystemExit(
            f"{args.region_type} patches must use the protected {STRICT_MODELS[args.region_type]} "
            "registration model; a looser transform can change identity or anatomy"
        )
    default_mid = {"face": 0.20, "head": 0.30, "hand": 0.30, "costume": 0.40, "prop": 0.40, "architecture": 0.35, "background": 0.30, "generic": 0.35}
    mid_detail_gain = default_mid[args.region_type] if args.mid_detail_gain is None else args.mid_detail_gain
    if not 0.0 <= mid_detail_gain <= 1.0:
        raise SystemExit("--mid-detail-gain must be between 0 and 1")
    model = AUTO_MODELS[args.region_type] if args.model == "auto" else args.model
    detail_receipt_requested = args.plan is not None or args.planner_region_index is not None
    tile_receipt_requested = args.tile_plan is not None or args.tile_index is not None
    if detail_receipt_requested and tile_receipt_requested:
        raise SystemExit("Use either --plan/--planner-region-index or --tile-plan/--tile-index, not both")
    receipt_requested = args.job is not None or detail_receipt_requested or tile_receipt_requested
    if receipt_requested and args.job is None:
        raise SystemExit("--job is required for audited blend evidence")
    if detail_receipt_requested and (args.plan is None or args.planner_region_index is None):
        raise SystemExit("--plan and --planner-region-index must be supplied together")
    if tile_receipt_requested and (args.tile_plan is None or args.tile_index is None):
        raise SystemExit("--tile-plan and --tile-index must be supplied together")
    if args.planner_region_index is not None and args.planner_region_index < 0:
        raise SystemExit("--planner-region-index must be zero or greater")
    if args.tile_index is not None and args.tile_index < 0:
        raise SystemExit("--tile-index must be zero or greater")

    base_path = args.base.expanduser().resolve()
    target_path = args.target.expanduser().resolve()
    patch_path = args.patch.expanduser().resolve()
    output = args.output.expanduser().resolve()
    blend_mask_path = args.blend_mask.expanduser().resolve() if args.blend_mask else None
    protected_paths = {base_path, target_path, patch_path}
    if blend_mask_path is not None:
        protected_paths.add(blend_mask_path)
    if output in protected_paths:
        raise SystemExit("Refusing to overwrite a base, target, patch, or mask image")

    blend_context = None
    if receipt_requested:
        job_path = args.job.expanduser().resolve()
        if not job_path.is_file() or job_path.name != "job.json":
            raise SystemExit(f"Missing job manifest: {job_path}")
        job_dir = job_path.parent
        for evidence_path in (base_path, target_path, patch_path, output):
            if not evidence_path.is_relative_to(job_dir):
                raise SystemExit(f"Audited blend paths must stay inside the job directory: {evidence_path}")
        job_data = json.loads(job_path.read_text(encoding="utf-8"))
        patch_sha256 = sha256_file(patch_path)

        if tile_receipt_requested:
            plan_path = args.tile_plan.expanduser().resolve()
            if not plan_path.is_file() or not plan_path.is_relative_to(job_dir):
                raise SystemExit("Tile plan must be an existing file inside the job directory")
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            matches = [item for item in (plan.get("tiles") or []) if item.get("index") == args.tile_index]
            if len(matches) != 1:
                raise SystemExit(f"--tile-index {args.tile_index} must match exactly one tile")
            region = matches[0]
            box = region.get("box") or {}
            if args.region_type in {"generic", "background"}:
                protected_regions = plan.get("protected_regions") or (plan.get("provenance") or {}).get("protected_regions") or []
                for protected in protected_regions:
                    protected_box = protected.get("box") or {}
                    if all(key in protected_box for key in ("x", "y", "width", "height")) and rectangles_intersect(box, protected_box):
                        raise SystemExit(
                            f"Broad {args.region_type} tile {args.tile_index} intersects protected "
                            f"{protected.get('region_type', 'subject')} region {protected.get('region_role', '')!r}; "
                            "regenerate the tile plan with protected-region splitting"
                        )
            evidence_kind = "tile-redraw"
            index_name = "tile_index"
            index_value = args.tile_index
            receipt_list = "tile_blend_receipts"
            plan_sha_field = "tile_plan_sha256"
            plan_path_field = "tile_plan_path"
        else:
            plan_path = args.plan.expanduser().resolve()
            if not plan_path.is_file() or not plan_path.is_relative_to(job_dir):
                raise SystemExit("Detail plan must be an existing file inside the job directory")
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            regions = plan.get("regions") or []
            if not 0 <= args.planner_region_index < len(regions):
                raise SystemExit(
                    f"--planner-region-index {args.planner_region_index} is outside the detail plan ({len(regions)} regions)"
                )
            region = regions[args.planner_region_index]
            box = region.get("crop") or {}
            evidence_kind = "detail-patch"
            index_name = "planner_region_index"
            index_value = args.planner_region_index
            receipt_list = "detail_blend_receipts"
            plan_sha_field = "detail_plan_sha256"
            plan_path_field = "detail_plan_path"

        if region.get("region_type") != args.region_type:
            raise SystemExit(
                f"Planned region type {region.get('region_type')!r} does not match --region-type {args.region_type!r}"
            )
        if args.x != box.get("x") or args.y != box.get("y"):
            raise SystemExit("Blend placement must match the planned region box exactly")
        plan_sha256 = sha256_file(plan_path)
        accepted_observations = [
            item for item in (job_data.get("patch_observations") or [])
            if isinstance(item, dict)
            and item.get("evidence_kind") == evidence_kind
            and item.get("evidence_plan_sha256") == plan_sha256
            and item.get(index_name) == index_value
            and item.get("patch_sha256") == patch_sha256
            and (item.get("budget_recheck") or {}).get("accepted") is True
        ]
        if not accepted_observations:
            raise SystemExit(
                f"Patch has no accepted record_patch_observation.py evidence for this exact {evidence_kind} plan entry"
            )
        blend_context = {
            "kind": evidence_kind,
            "job_path": job_path,
            "job_data": job_data,
            "plan_path": plan_path,
            "plan_sha256": plan_sha256,
            "plan_sha_field": plan_sha_field,
            "plan_path_field": plan_path_field,
            "receipt_list": receipt_list,
            "index_name": index_name,
            "index_value": index_value,
            "region": region,
            "box": box,
            "patch_sha256": patch_sha256,
        }

    base = cv2.imread(str(base_path), cv2.IMREAD_COLOR)
    target = cv2.imread(str(target_path), cv2.IMREAD_COLOR)
    patch = cv2.imread(str(patch_path), cv2.IMREAD_COLOR)
    if base is None or target is None or patch is None:
        raise SystemExit("Could not read base, target, or patch")
    if blend_mask_path is not None:
        blend_mask = cv2.imread(str(blend_mask_path), cv2.IMREAD_GRAYSCALE)
        if blend_mask is None:
            raise SystemExit("Could not read blend mask")
        if blend_mask.shape[:2] != patch.shape[:2]:
            raise SystemExit("Blend mask must match the patch dimensions")
    else:
        blend_mask = None
    height, width = target.shape[:2]
    patch_h, patch_w = patch.shape[:2]
    if blend_context is not None:
        box = blend_context["box"]
        if width != box.get("width") or height != box.get("height"):
            raise SystemExit(
                f"Target crop {width}x{height} does not match planned box {box.get('width')}x{box.get('height')}"
            )
    target_ratio = width / height
    patch_ratio = patch_w / patch_h
    aspect_deviation = abs(patch_ratio - target_ratio) / target_ratio
    if aspect_deviation > 0.05:
        raise SystemExit(
            f"Patch aspect {patch_ratio:.3f} deviates from target region aspect {target_ratio:.3f} "
            f"by {aspect_deviation * 100:.1f}% (>5%). Regenerate the patch at the target region aspect "
            "instead of recropping the target to match the generator output; a mismatched patch distorts content."
        )
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
    minimum_points = 4 if model == "homography" else 3
    if len(good) < minimum_points:
        raise SystemExit(f"Registration rejected: only {len(good)} matches for {model}")
    src = np.float32([kp_patch[item.queryIdx].pt for item in good])
    dst = np.float32([kp_target[item.trainIdx].pt for item in good])
    transform, inlier_mask = estimate_transform(model, src, dst)
    inliers = int(inlier_mask.sum()) if inlier_mask is not None else 0
    ratio = inliers / len(good)
    report = {
        "region_type": args.region_type,
        "registration_model": model,
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
    linear = transform[:2, :2]
    determinant = float(np.linalg.det(linear))
    condition = float(np.linalg.cond(linear)) if np.isfinite(linear).all() else float("inf")
    implausible = (
        not np.isfinite(projected_corners).all()
        or not cv2.isContourConvex(projected_corners.astype(np.float32))
        or area_ratio < 0.25
        or area_ratio > 4.0
        or determinant <= 0
        or condition > 6.0
        or median_error > args.max_median_error
        or p95_error > args.max_p95_error
    )
    if implausible:
        report.update(
            {
                "median_reprojection_error": median_error,
                "p95_reprojection_error": p95_error,
                "projected_area_ratio": area_ratio,
                "linear_determinant": determinant,
                "linear_condition": condition,
                "reason": f"implausible {model} transform",
            }
        )
        print(json.dumps(report, indent=2))
        raise SystemExit(2)

    aligned = warp_image(patch, transform, width, height, cv2.INTER_LANCZOS4).astype(np.float32)
    # Geometry coverage is independent of the optional blend mask. A lightweight mask
    # may intentionally cover only the center/subject and must not weaken the warp gate.
    geometry_source_mask = np.full(patch.shape[:2], 255, dtype=np.uint8)
    geometry_mask = warp_image(geometry_source_mask, transform, width, height, cv2.INTER_NEAREST)
    geometry_coverage = float(np.count_nonzero(geometry_mask) / geometry_mask.size)
    if geometry_coverage < args.min_coverage:
        report.update(
            {
                "median_reprojection_error": median_error,
                "p95_reprojection_error": p95_error,
                "projected_area_ratio": area_ratio,
                "coverage": geometry_coverage,
                "reason": "insufficient warped-patch geometry coverage",
            }
        )
        print(json.dumps(report, indent=2))
        raise SystemExit(2)

    if blend_mask is not None:
        warped_blend_mask = warp_image(blend_mask, transform, width, height, cv2.INTER_LINEAR).astype(np.float32)
    else:
        warped_blend_mask = geometry_mask.astype(np.float32)
    mask_coverage = float(np.mean(warped_blend_mask / 255.0))
    if blend_mask is not None and mask_coverage < 0.05:
        report.update({"coverage": geometry_coverage, "mask_coverage": mask_coverage, "reason": "blend mask is effectively empty"})
        print(json.dumps(report, indent=2))
        raise SystemExit(2)

    # Multiband fusion: LOOK MASTER owns low frequency and most mid-frequency
    # appearance; the patch contributes a controlled amount of mid detail and the high
    # frequency texture. This reduces local re-grading and sharpness discontinuities.
    target_float = target.astype(np.float32)
    sigma_large = max(min(width, height) / 28.0, 12.0)
    sigma_small = max(min(width, height) / 110.0, 2.0)
    aligned_large = normalized_low_frequency(aligned, geometry_mask, sigma_large)
    aligned_small = normalized_low_frequency(aligned, geometry_mask, sigma_small)
    target_large = cv2.GaussianBlur(target_float, (0, 0), sigmaX=sigma_large, sigmaY=sigma_large)
    target_small = cv2.GaussianBlur(target_float, (0, 0), sigmaX=sigma_small, sigmaY=sigma_small)
    target_mid = target_small - target_large
    aligned_mid = aligned_small - aligned_large
    aligned_high = aligned - aligned_small
    corrected = np.clip(
        target_large
        + target_mid * (1.0 - mid_detail_gain)
        + aligned_mid * mid_detail_gain
        + aligned_high * args.detail_gain,
        0,
        255,
    )

    yy, xx = np.mgrid[0:height, 0:width]
    distance = np.minimum.reduce([xx, yy, width - 1 - xx, height - 1 - yy]).astype(np.float32)
    edge_alpha = smoothstep(distance / max(args.feather, 1.0))[..., None]
    alpha = edge_alpha * (warped_blend_mask / 255.0)[..., None]
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
            "linear_determinant": determinant,
            "linear_condition": condition,
            "coverage": geometry_coverage,
            "mask_coverage": mask_coverage,
            "fusion_mode": "look-master-low-frequency-plus-patch-detail",
            "fusion_version": 2,
            "multiband": True,
            "mid_detail_gain": mid_detail_gain,
            "detail_gain": args.detail_gain,
            "custom_blend_mask": blend_mask_path is not None,
        }
    )
    if blend_context is not None:
        output_sha256 = sha256_file(output)
        receipt = {
            "schema_version": 1,
            "kind": blend_context["kind"],
            "recorded_at": datetime.now().astimezone().isoformat(),
            blend_context["plan_path_field"]: str(blend_context["plan_path"]),
            blend_context["plan_sha_field"]: blend_context["plan_sha256"],
            blend_context["index_name"]: blend_context["index_value"],
            "region_type": args.region_type,
            "input_base_path": str(base_path),
            "input_base_sha256": sha256_file(base_path),
            "target_path": str(target_path),
            "target_sha256": sha256_file(target_path),
            "patch_path": str(patch_path),
            "patch_sha256": blend_context["patch_sha256"],
            "output_path": str(output),
            "output_sha256": output_sha256,
            "registration": {
                "model": model,
                "inliers": inliers,
                "inlier_ratio": ratio,
                "median_reprojection_error": median_error,
                "p95_reprojection_error": p95_error,
                "coverage": geometry_coverage,
                "accepted": True,
            },
        }
        job_data = blend_context["job_data"]
        receipts = job_data.setdefault(blend_context["receipt_list"], [])
        if not isinstance(receipts, list):
            raise SystemExit(f"job.json {blend_context['receipt_list']} must be an array")
        receipt["sequence"] = len(receipts) + 1
        receipts.append(receipt)
        job_data["updated_at"] = receipt["recorded_at"]
        atomic_write_json(blend_context["job_path"], job_data)
        report["blend_receipt"] = receipt
        if blend_context["kind"] == "tile-redraw":
            report["tile_blend_receipt"] = receipt
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
