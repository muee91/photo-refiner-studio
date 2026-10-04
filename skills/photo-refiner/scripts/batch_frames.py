#!/usr/bin/env python3
"""Materialize and synchronize independent frame jobs for Photo Refiner batches.

A batch shares appearance intent, not photographic facts. Every source frame gets
its own single-image child job so SOURCE MASTER, LOOK MASTER, patches, registration,
and delivery evidence can never leak across photographs.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import datetime
from pathlib import Path

from job_contract import atomic_write_json


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned[:80] or "frame"


def read_job(path: Path) -> tuple[Path, dict]:
    job_path = path.expanduser().resolve()
    if not job_path.is_file() or job_path.name != "job.json":
        raise SystemExit(f"Missing job manifest: {job_path}")
    data = json.loads(job_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("job.json must contain an object")
    return job_path, data


def assert_batch_parent(data: dict) -> None:
    if data.get("workflow") != "batch" or data.get("execution_mode") == "creative-translation":
        raise SystemExit("Per-frame batch authority applies to ordinary photo-refinement batch jobs")


def style_authority(data: dict) -> dict:
    batch = data.get("batch") or {}
    authority = batch.get("style_authority")
    if not isinstance(authority, dict) or not authority.get("path") or not authority.get("sha256"):
        raise SystemExit("Approve the batch master frame before materializing frame jobs")
    return authority


def reset_child(parent: dict, *, parent_path: Path, index: int, source: str, source_record: dict,
                child_path: Path, authority: dict, attempt: int) -> dict:
    child = copy.deepcopy(parent)
    ts = now_iso()
    child["created_at"] = ts
    child["updated_at"] = ts
    child["status"] = "initialized"
    child["workflow"] = "single"
    child["sources"] = [source]
    child["source_records"] = [copy.deepcopy(source_record)]
    child["delivery_mode"] = "one-click"
    child["base_preview"] = {"required": False, "approved": False}
    child["creative_preview"] = {"required": False, "approved": False}
    child.pop("approved_preview", None)
    child.pop("hd_working_canvas", None)
    child.pop("delivery_gate", None)
    child.pop("detail_blend_receipts", None)
    child.pop("tile_blend_receipts", None)
    child["upscale_passes"] = []
    child["patch_observations"] = []
    child["patch_observation_summary"] = {
        "count": 0,
        "size_match_count": 0,
        "size_mismatch_count": 0,
        "actual_sizes": [],
        "requested_sizes": [],
    }
    child["artifacts"] = []
    child["history"] = [{"status": "initialized", "at": ts, "event": "batch_frame_materialized"}]
    child["batch_frame"] = {
        "parent_job": str(parent_path),
        "frame_index": index,
        "attempt": attempt,
        "source_authority": copy.deepcopy(source_record),
        "shared_style_authority": copy.deepcopy(authority),
        "authority_rule": "share-appearance-never-share-photographic-facts",
    }
    child["batch"] = {
        "parent_job": str(parent_path),
        "frame_index": index,
        "consistency": (parent.get("batch") or {}).get("consistency", "balanced"),
        "shared_style_only": True,
    }
    child["output"] = {
        "separate_job_folder": True,
        "keep_intermediates": bool((parent.get("output") or {}).get("keep_intermediates")),
    }
    child["batch_parent_authority"] = {
        "resolved_prompt": copy.deepcopy(parent.get("resolved_prompt")),
        "style_reference": copy.deepcopy(authority),
    }
    return child


def child_dir_for(parent_dir: Path, index: int, source: str, attempt: int) -> Path:
    suffix = "" if attempt <= 1 else f"-attempt{attempt}"
    stem = safe_name(Path(source).stem)
    return parent_dir / "frames" / f"{index:04d}-{stem}{suffix}"


def materialize(parent_path: Path, parent: dict) -> dict:
    assert_batch_parent(parent)
    if parent.get("status") != "base_generated":
        raise SystemExit("Batch frames can be materialized only after the batch master frame is generated")
    batch = parent.setdefault("batch", {})
    if not batch.get("master_frame_approved"):
        raise SystemExit("Approve the batch master frame before materializing frame jobs")
    authority = style_authority(parent)
    sources = parent.get("sources") or []
    records = parent.get("source_records") or []
    if len(sources) < 2 or len(records) != len(sources):
        raise SystemExit("Batch source records are incomplete")

    existing = batch.get("frames") if isinstance(batch.get("frames"), list) else []
    existing_by_index = {item.get("index"): item for item in existing if isinstance(item, dict)}
    frames = []
    for index, (source, record) in enumerate(zip(sources, records)):
        current = existing_by_index.get(index) or {}
        attempt = max(1, int(current.get("attempt") or 1))
        child_dir = child_dir_for(parent_path.parent, index, source, attempt)
        child_path = child_dir / "job.json"
        if not child_path.is_file():
            child_dir.mkdir(parents=True, exist_ok=True)
            (child_dir / "intermediates").mkdir(exist_ok=True)
            (child_dir / "outputs").mkdir(exist_ok=True)
            child = reset_child(
                parent,
                parent_path=parent_path,
                index=index,
                source=source,
                source_record=record,
                child_path=child_path,
                authority=authority,
                attempt=attempt,
            )
            atomic_write_json(child_path, child)
        child = json.loads(child_path.read_text(encoding="utf-8"))
        frames.append({
            "index": index,
            "source": source,
            "source_sha256": record.get("sha256"),
            "child_job": str(child_path),
            "attempt": attempt,
            "status": child.get("status", "initialized"),
        })

    batch["authority_version"] = 1
    batch["authority_rule"] = "shared-style-per-frame-source-look-patch-delivery"
    batch["frames"] = frames
    batch["frame_count"] = len(frames)
    batch["active_frame_index"] = next((item["index"] for item in frames if item["status"] != "completed"), None)
    batch["materialized_at"] = now_iso()
    parent["updated_at"] = batch["materialized_at"]
    parent.setdefault("history", []).append({
        "status": parent.get("status"),
        "event": "batch_frames_materialized",
        "at": batch["materialized_at"],
        "frame_count": len(frames),
    })
    atomic_write_json(parent_path, parent)
    return {"job": str(parent_path), "frames": frames, "frame_count": len(frames)}


def sync(parent_path: Path, parent: dict, *, finalize: bool = False) -> dict:
    assert_batch_parent(parent)
    batch = parent.setdefault("batch", {})
    frames = batch.get("frames") or []
    if not frames:
        raise SystemExit("Batch frames have not been materialized")
    updated = []
    completed = failed = 0
    for frame in frames:
        child_path = Path(str(frame.get("child_job") or "")).expanduser().resolve()
        if not child_path.is_file():
            status = "missing"
        else:
            child = json.loads(child_path.read_text(encoding="utf-8"))
            status = child.get("status", "unknown")
        item = dict(frame)
        item["status"] = status
        updated.append(item)
        completed += status == "completed"
        failed += status in {"failed", "missing"}
    batch["frames"] = updated
    batch["completed_frames"] = completed
    batch["failed_frames"] = failed
    batch["active_frame_index"] = next((item["index"] for item in updated if item["status"] != "completed"), None)
    batch["synced_at"] = now_iso()
    all_completed = completed == len(updated)
    if finalize:
        if not all_completed:
            raise SystemExit(f"Cannot finalize batch: {completed}/{len(updated)} frames completed, {failed} failed/missing")
        parent["status"] = "completed"
        batch["completed"] = True
        batch["completed_at"] = now_iso()
        parent.setdefault("history", []).append({
            "status": "completed",
            "event": "batch_completed",
            "at": batch["completed_at"],
            "frame_count": len(updated),
        })
    parent["updated_at"] = now_iso()
    atomic_write_json(parent_path, parent)
    return {
        "job": str(parent_path),
        "frame_count": len(updated),
        "completed_frames": completed,
        "failed_frames": failed,
        "all_completed": all_completed,
        "frames": updated,
    }


def retry(parent_path: Path, parent: dict, index: int) -> dict:
    assert_batch_parent(parent)
    batch = parent.setdefault("batch", {})
    frames = batch.get("frames") or []
    matches = [item for item in frames if item.get("index") == index]
    if len(matches) != 1:
        raise SystemExit(f"Unknown batch frame index: {index}")
    frame = matches[0]
    source = frame["source"]
    source_record = (parent.get("source_records") or [])[index]
    authority = style_authority(parent)
    attempt = int(frame.get("attempt") or 1) + 1
    child_dir = child_dir_for(parent_path.parent, index, source, attempt)
    child_dir.mkdir(parents=True, exist_ok=False)
    (child_dir / "intermediates").mkdir()
    (child_dir / "outputs").mkdir()
    child_path = child_dir / "job.json"
    child = reset_child(
        parent,
        parent_path=parent_path,
        index=index,
        source=source,
        source_record=source_record,
        child_path=child_path,
        authority=authority,
        attempt=attempt,
    )
    atomic_write_json(child_path, child)
    frame.update({"child_job": str(child_path), "attempt": attempt, "status": "initialized"})
    batch["active_frame_index"] = index
    parent["updated_at"] = now_iso()
    parent.setdefault("history", []).append({
        "status": parent.get("status"),
        "event": "batch_frame_retry",
        "frame_index": index,
        "attempt": attempt,
        "at": parent["updated_at"],
    })
    atomic_write_json(parent_path, parent)
    return {"job": str(parent_path), "frame_index": index, "attempt": attempt, "child_job": str(child_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage independent frame jobs for an ordinary Photo Refiner batch.")
    parser.add_argument("job", type=Path, help="Parent batch job.json")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--materialize", action="store_true")
    group.add_argument("--sync", action="store_true")
    group.add_argument("--finalize", action="store_true")
    group.add_argument("--retry-index", type=int)
    args = parser.parse_args()

    parent_path, parent = read_job(args.job)
    if args.materialize:
        output = materialize(parent_path, parent)
    elif args.sync:
        output = sync(parent_path, parent, finalize=False)
    elif args.finalize:
        output = sync(parent_path, parent, finalize=True)
    else:
        if args.retry_index is None or args.retry_index < 0:
            raise SystemExit("--retry-index must be zero or greater")
        output = retry(parent_path, parent, args.retry_index)
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
