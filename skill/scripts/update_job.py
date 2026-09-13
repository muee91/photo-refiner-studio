#!/usr/bin/env python3
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


TRANSITIONS = {
    "initialized": {"prepared", "failed"},
    "prepared": {"base_generated", "failed"},
    "base_generated": {"details_processed", "completed", "failed"},
    "details_processed": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
}


def parse_artifact(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Artifact must be KIND=PATH")
    kind, raw_path = value.split("=", 1)
    if not kind.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("Artifact must be KIND=PATH")
    return kind.strip(), Path(raw_path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Advance a photo-refiner job and record artifacts.")
    parser.add_argument("job", type=Path, help="Path to job.json")
    parser.add_argument("--status", choices=sorted(TRANSITIONS))
    parser.add_argument("--artifact", action="append", type=parse_artifact, default=[])
    parser.add_argument("--note", default="")
    parser.add_argument("--approve-master", action="store_true")
    parser.add_argument("--master-frame", type=Path)
    parser.add_argument("--approve-base-preview", action="store_true")
    args = parser.parse_args()

    job_path = args.job.expanduser().resolve()
    if not job_path.is_file() or job_path.name != "job.json":
        raise SystemExit(f"Missing job manifest: {job_path}")
    job_dir = job_path.parent
    data = json.loads(job_path.read_text(encoding="utf-8"))
    current = data.get("status")
    if current not in TRANSITIONS:
        raise SystemExit(f"Unknown current job status: {current}")

    now = datetime.now().astimezone().isoformat()
    if args.approve_master:
        if data.get("workflow") != "batch":
            raise SystemExit("Master-frame approval applies only to batch jobs")
        if current != "base_generated":
            raise SystemExit("Master frame can be approved only after status base_generated")
        if args.master_frame is None:
            raise SystemExit("--master-frame is required with --approve-master")
        master_frame = args.master_frame.expanduser().resolve()
        if not master_frame.is_file() or not master_frame.is_relative_to(job_dir):
            raise SystemExit("Approved master frame must be an existing file inside the job directory")
        data["batch"]["master_frame"] = str(master_frame)
        data["batch"]["master_frame_approved"] = True
        event = {"status": current, "event": "master_frame_approved", "at": now}
        if args.note.strip():
            event["note"] = args.note.strip()
        data.setdefault("history", []).append(event)

    if args.approve_base_preview:
        if data.get("delivery_mode") != "preview-first" or data.get("workflow") != "single":
            raise SystemExit("Base-preview approval applies only to single-image preview-first jobs")
        if current != "base_generated":
            raise SystemExit("Base preview can be approved only after status base_generated")
        data.setdefault("base_preview", {})["approved"] = True
        event = {"status": current, "event": "base_preview_approved", "at": now}
        if args.note.strip():
            event["note"] = args.note.strip()
        data.setdefault("history", []).append(event)

    if args.status and args.status != current:
        if args.status not in TRANSITIONS[current]:
            raise SystemExit(f"Invalid status transition: {current} -> {args.status}")
        if (
            data.get("workflow") == "batch"
            and current == "base_generated"
            and args.status in {"details_processed", "completed"}
            and not data.get("batch", {}).get("master_frame_approved")
        ):
            raise SystemExit("Approve the batch master frame before continuing")
        if (
            data.get("delivery_mode") == "preview-first"
            and data.get("workflow") == "single"
            and current == "base_generated"
            and args.status in {"details_processed", "completed"}
            and not data.get("base_preview", {}).get("approved")
        ):
            raise SystemExit("Approve the base preview before continuing")
        data["status"] = args.status
        event = {"status": args.status, "at": now}
        if args.note.strip():
            event["note"] = args.note.strip()
        data.setdefault("history", []).append(event)

    for kind, raw_path in args.artifact:
        artifact = raw_path.expanduser().resolve()
        if not artifact.is_file():
            raise SystemExit(f"Missing artifact: {artifact}")
        if not artifact.is_relative_to(job_dir):
            raise SystemExit(f"Artifact must be inside the job directory: {artifact}")
        data.setdefault("artifacts", []).append(
            {
                "kind": kind,
                "path": str(artifact),
                "size": artifact.stat().st_size,
                "sha256": sha256_file(artifact),
                "recorded_at": now,
            }
        )

    data["updated_at"] = now
    temporary = job_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(job_path)
    print(json.dumps({"job": str(job_path), "status": data["status"], "artifacts": len(data["artifacts"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
