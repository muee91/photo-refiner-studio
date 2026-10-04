#!/usr/bin/env python3
"""Bind the approved batch master frame as appearance-only shared authority."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from job_contract import atomic_write_json


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze an approved batch master as shared style authority.")
    parser.add_argument("job", type=Path, help="Parent batch job.json")
    args = parser.parse_args()

    job_path = args.job.expanduser().resolve()
    if not job_path.is_file() or job_path.name != "job.json":
        raise SystemExit(f"Missing job manifest: {job_path}")
    data = json.loads(job_path.read_text(encoding="utf-8"))
    if data.get("workflow") != "batch" or data.get("execution_mode") == "creative-translation":
        raise SystemExit("Batch style authority applies only to ordinary photo-refinement batches")
    batch = data.get("batch") or {}
    if not batch.get("master_frame_approved"):
        raise SystemExit("Approve the batch master frame first")
    master = Path(str(batch.get("master_frame") or "")).expanduser().resolve()
    if not master.is_file() or not master.is_relative_to(job_path.parent):
        raise SystemExit("Approved batch master frame is missing or outside the batch job directory")
    try:
        with Image.open(master) as image:
            pixel_size = [image.width, image.height]
    except OSError as exc:
        raise SystemExit(f"Cannot read approved batch master: {exc}") from exc

    now = datetime.now().astimezone().isoformat()
    batch["style_authority"] = {
        "kind": "batch-style-master",
        "path": str(master),
        "pixel_size": pixel_size,
        "file_size": master.stat().st_size,
        "sha256": sha256_file(master),
        "owns": ["color", "lighting", "tone", "atmosphere", "retouch_character", "grain"],
        "does_not_own": ["identity", "pose", "anatomy", "factual_geometry", "garment_construction", "frame_specific_texture"],
        "bound_at": now,
    }
    batch["authority_rule"] = "share-appearance-never-share-photographic-facts"
    data["batch"] = batch
    data["updated_at"] = now
    data.setdefault("history", []).append({
        "status": data.get("status"),
        "event": "batch_style_authority_bound",
        "at": now,
        "sha256": batch["style_authority"]["sha256"],
    })
    atomic_write_json(job_path, data)
    print(json.dumps({"job": str(job_path), "style_authority": batch["style_authority"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
