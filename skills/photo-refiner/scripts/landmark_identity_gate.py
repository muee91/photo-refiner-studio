#!/usr/bin/env python3
"""Optional lightweight face-structure gate using externally supplied landmarks.

No face detector or heavy identity model is bundled. The script accepts 5-point (or
richer) landmark JSON from the active vision/backend, computes a deterministic
least-squares similarity alignment with NumPy, and rejects proportion/shape drift.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


REQUIRED = ["left_eye", "right_eye", "nose_tip", "mouth_left", "mouth_right"]
OPTIONAL = ["chin", "jaw_left", "jaw_right"]


def load_points(path: Path) -> tuple[list[str], np.ndarray]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Landmark file must be an object: {path}")
    missing = [name for name in REQUIRED if name not in data]
    if missing:
        raise SystemExit(f"Missing required landmarks in {path}: {', '.join(missing)}")
    names = REQUIRED + [name for name in OPTIONAL if name in data]
    points = []
    for name in names:
        value = data[name]
        if not isinstance(value, list) or len(value) != 2:
            raise SystemExit(f"Landmark {name} must be [x, y]")
        point = np.asarray(value, dtype=np.float64)
        if not np.isfinite(point).all():
            raise SystemExit(f"Landmark {name} is not finite")
        points.append(point)
    return names, np.asarray(points, dtype=np.float64)


def similarity_align(source: np.ndarray, candidate: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return aligned candidate and a 2x3 candidate->source similarity matrix."""
    if source.shape != candidate.shape or source.shape[0] < 2:
        raise ValueError("Source/candidate landmark arrays must have the same shape")
    src_mean = source.mean(axis=0)
    cand_mean = candidate.mean(axis=0)
    src_centered = source - src_mean
    cand_centered = candidate - cand_mean
    variance = float(np.sum(cand_centered ** 2))
    if variance <= 1e-12:
        raise ValueError("Degenerate candidate landmark geometry")
    covariance = cand_centered.T @ src_centered
    u, singular, vt = np.linalg.svd(covariance)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
        singular[-1] *= -1
    scale = float(np.sum(singular) / variance)
    aligned = scale * (candidate @ rotation.T)
    translation = src_mean - scale * (cand_mean @ rotation.T)
    aligned += translation
    matrix = np.column_stack([scale * rotation, translation.reshape(2, 1)])
    return aligned, matrix


def evaluate_landmarks(source: np.ndarray, candidate: np.ndarray, names: list[str], max_normalized_rmse: float = 0.055, max_point_error: float = 0.10) -> dict:
    aligned, matrix = similarity_align(source, candidate)
    errors = np.linalg.norm(aligned - source, axis=1)
    source_diag = float(np.linalg.norm(source.max(axis=0) - source.min(axis=0)))
    if source_diag <= 1e-9:
        raise ValueError("Degenerate source landmark geometry")
    normalized_errors = errors / source_diag
    rmse = float(np.sqrt(np.mean(normalized_errors ** 2)))
    max_error = float(normalized_errors.max())
    accepted = rmse <= max_normalized_rmse and max_error <= max_point_error
    worst_index = int(np.argmax(normalized_errors))
    return {
        "accepted": accepted,
        "gate": "similarity-normalized-landmark-structure-v2",
        "landmarks": names,
        "normalized_rmse": rmse,
        "max_normalized_point_error": max_error,
        "worst_landmark": names[worst_index],
        "thresholds": {
            "max_normalized_rmse": max_normalized_rmse,
            "max_point_error": max_point_error,
        },
        "transform": matrix.tolist(),
        "detector_required": False,
        "note": "Supplementary structure gate only; visual identity review remains required for identity-sensitive patches.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare SOURCE MASTER and candidate face landmarks after deterministic similarity alignment.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--max-normalized-rmse", type=float, default=0.055)
    parser.add_argument("--max-point-error", type=float, default=0.10)
    args = parser.parse_args()
    if args.max_normalized_rmse <= 0 or args.max_point_error <= 0:
        raise SystemExit("Identity thresholds must be positive")

    source_path = args.source.expanduser().resolve()
    candidate_path = args.candidate.expanduser().resolve()
    source_names, source_all = load_points(source_path)
    candidate_names, candidate_all = load_points(candidate_path)
    common = [name for name in source_names if name in candidate_names]
    if len(common) < 5:
        raise SystemExit("At least the five canonical facial landmarks are required in both files")
    source_map = {name: point for name, point in zip(source_names, source_all)}
    candidate_map = {name: point for name, point in zip(candidate_names, candidate_all)}
    source = np.asarray([source_map[name] for name in common], dtype=np.float64)
    candidate = np.asarray([candidate_map[name] for name in common], dtype=np.float64)

    try:
        report = evaluate_landmarks(source, candidate, common, args.max_normalized_rmse, args.max_point_error)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, indent=2))
    if not report["accepted"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
