#!/usr/bin/env python3
"""Summarize observed client-returned patch dimensions across Photo Refiner jobs."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def collect_job_paths(values: list[Path]) -> list[Path]:
    jobs: set[Path] = set()
    for raw in values:
        path = raw.expanduser().resolve()
        if path.is_file():
            if path.name != "job.json":
                raise SystemExit(f"Expected job.json, got: {path}")
            jobs.add(path)
        elif path.is_dir():
            jobs.update(candidate.resolve() for candidate in path.rglob("job.json"))
        else:
            raise SystemExit(f"Missing path: {path}")
    return sorted(jobs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize actual patch sizes observed from the ChatGPT client image-generation path."
    )
    parser.add_argument("path", nargs="+", type=Path, help="One or more job.json files or directories containing jobs")
    args = parser.parse_args()

    job_paths = collect_job_paths(args.path)
    observations: list[dict] = []
    for job_path in job_paths:
        data = json.loads(job_path.read_text(encoding="utf-8"))
        for item in data.get("patch_observations", []):
            if isinstance(item, dict):
                copied = dict(item)
                copied["_job"] = str(job_path)
                observations.append(copied)

    mappings = Counter()
    by_detail_mode: dict[str, Counter] = {}
    valid: list[dict] = []
    for item in observations:
        requested = item.get("requested_size")
        actual = item.get("actual_size")
        if not (
            isinstance(requested, list) and len(requested) == 2
            and isinstance(actual, list) and len(actual) == 2
        ):
            continue
        req_label = f"{requested[0]}x{requested[1]}"
        actual_label = f"{actual[0]}x{actual[1]}"
        mappings[(req_label, actual_label)] += 1
        mode = str(item.get("detail_mode") or "unknown")
        by_detail_mode.setdefault(mode, Counter())[actual_label] += 1
        valid.append(item)

    def pixels(item: dict) -> int:
        size = item["actual_size"]
        return int(size[0]) * int(size[1])

    max_width = max(valid, key=lambda item: int(item["actual_size"][0])) if valid else None
    max_height = max(valid, key=lambda item: int(item["actual_size"][1])) if valid else None
    max_pixels = max(valid, key=pixels) if valid else None

    report = {
        "jobs_scanned": len(job_paths),
        "observations": len(valid),
        "requested_to_actual": [
            {"requested": requested, "actual": actual, "count": count}
            for (requested, actual), count in sorted(mappings.items())
        ],
        "actual_sizes_by_detail_mode": {
            mode: [{"size": size, "count": count} for size, count in sorted(counter.items())]
            for mode, counter in sorted(by_detail_mode.items())
        },
        "maximum_observed_width": None if max_width is None else {
            "pixels": max_width["actual_size"][0],
            "size": max_width["actual_size"],
            "region_type": max_width.get("region_type"),
            "job": max_width["_job"],
        },
        "maximum_observed_height": None if max_height is None else {
            "pixels": max_height["actual_size"][1],
            "size": max_height["actual_size"],
            "region_type": max_height.get("region_type"),
            "job": max_height["_job"],
        },
        "maximum_observed_total_pixels": None if max_pixels is None else {
            "pixels": pixels(max_pixels),
            "size": max_pixels["actual_size"],
            "region_type": max_pixels.get("region_type"),
            "job": max_pixels["_job"],
        },
        "important": "These are observed ChatGPT client outputs, not a claimed platform maximum.",
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
