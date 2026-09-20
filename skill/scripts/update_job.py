#!/usr/bin/env python3
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from delivery_gate import measure
from job_contract import atomic_write_json


TRANSITIONS = {
    "initialized": {"prepared", "failed"},
    "prepared": {"base_generated", "failed"},
    "base_generated": {"details_processed", "completed", "failed"},
    "details_processed": {"completed", "creative_generated", "failed"},
    "creative_generated": {"completed", "failed"},
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


def approval_artifact(args, job_dir: Path, allowed_kinds: set[str], flag: str) -> dict:
    """Bind an approval to the exact image the user was shown.

    Without this the ledger records only a boolean, so nothing later can tell
    whether the delivered file descends from what was actually approved.
    """
    matches = [(kind, path) for kind, path in args.artifact if kind in allowed_kinds]
    if not matches:
        raise SystemExit(
            f"{flag} must carry the approved image: add --artifact {' or '.join(sorted(allowed_kinds))}=<file inside the job directory>"
        )
    kind, raw_path = matches[-1]
    path = raw_path.expanduser().resolve()
    if not path.is_file() or not path.is_relative_to(job_dir):
        raise SystemExit(f"{flag} image must be an existing file inside the job directory: {path}")
    return {"kind": kind, **measure(path)}


def creative_binding(data: dict) -> str:
    """`creative_output` is null for ordinary refinement jobs."""
    return (data.get("creative_output") or {}).get("upstream_binding") or ""


def verify_delivery_gate(data: dict) -> None:
    """A delivery may not be an interpolated copy of a smaller approved image."""
    gate = data.get("delivery_gate")
    if not isinstance(gate, dict):
        raise SystemExit(
            "Refusing to complete: the job has no delivery gate result. "
            "Run delivery_gate.py --master <approved image> --final <delivered file> first."
        )
    if gate.get("verdict") != "pass":
        raise SystemExit(
            "Refusing to complete: the delivery gate failed. "
            + str(gate.get("required_action") or "").strip()
        )
    for role in ("master", "final"):
        recorded = gate.get(role) or {}
        path = Path(recorded.get("path", ""))
        if not path.is_file():
            raise SystemExit(f"stale delivery gate result: the {role} file {path} is gone; re-run delivery_gate.py")
        measured = measure(path)
        if measured["size"] != recorded.get("size") or measured["sha256"] != recorded.get("sha256"):
            raise SystemExit(
                f"stale delivery gate result: the {role} image changed after the gate passed; "
                "re-run delivery_gate.py before completing"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Advance a photo-refiner job and record artifacts.")
    parser.add_argument("job", type=Path, help="Path to job.json")
    parser.add_argument("--status", choices=sorted(TRANSITIONS))
    parser.add_argument("--artifact", action="append", type=parse_artifact, default=[])
    parser.add_argument("--note", default="")
    parser.add_argument("--approve-master", action="store_true")
    parser.add_argument("--master-frame", type=Path)
    parser.add_argument("--approve-base-preview", action="store_true")
    parser.add_argument("--approve-creative-preview", action="store_true")
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
        if data.get("execution_mode") == "creative-translation":
            raise SystemExit("Creative translations use effect-preview approval, not batch master-frame approval")
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

    if args.approve_creative_preview:
        if data.get("execution_mode") != "creative-translation" or creative_binding(data) != "hd-master":
            raise SystemExit("Creative-draft approval applies only to hd-master creative chains")
        if current != "creative_generated":
            raise SystemExit("Creative draft can be approved only after status creative_generated")
        data["approved_preview"] = approval_artifact(args, job_dir, {"creative_preview"}, "--approve-creative-preview")
        data.setdefault("creative_preview", {})["approved"] = True
        event = {"status": current, "event": "creative_preview_approved", "at": now}
        if args.note.strip():
            event["note"] = args.note.strip()
        data.setdefault("history", []).append(event)

    if args.approve_base_preview:
        preview_eligible = data.get("workflow") == "single" or data.get("execution_mode") == "creative-translation"
        if data.get("delivery_mode") != "preview-first" or not preview_eligible:
            raise SystemExit("Base-preview approval applies only to single-image or creative-translation preview-first jobs")
        if current != "base_generated":
            raise SystemExit("Base preview can be approved only after status base_generated")
        data["approved_preview"] = approval_artifact(
            args, job_dir, {"base_preview", "look_master"}, "--approve-base-preview"
        )
        data.setdefault("base_preview", {})["approved"] = True
        event = {"status": current, "event": "base_preview_approved", "at": now}
        if args.note.strip():
            event["note"] = args.note.strip()
        data.setdefault("history", []).append(event)

    if args.status and args.status != current:
        if args.status not in TRANSITIONS[current]:
            raise SystemExit(f"Invalid status transition: {current} -> {args.status}")
        if args.status == "creative_generated" and creative_binding(data) != "hd-master":
            raise SystemExit("creative_generated applies only to hd-master creative chains")
        if (
            current == "details_processed"
            and args.status == "completed"
            and creative_binding(data) == "hd-master"
        ):
            raise SystemExit("hd-master creative chains must pass through creative_generated")
        if (
            current == "creative_generated"
            and args.status == "completed"
            and not data.get("creative_preview", {}).get("approved")
        ):
            raise SystemExit("Approve the creative draft before the final redraw pass")
        if (
            data.get("workflow") == "batch"
            and data.get("execution_mode") != "creative-translation"
            and current == "base_generated"
            and args.status in {"details_processed", "completed"}
            and not data.get("batch", {}).get("master_frame_approved")
        ):
            raise SystemExit("Approve the batch master frame before continuing")
        if (
            data.get("delivery_mode") == "preview-first"
            and (data.get("workflow") == "single" or data.get("execution_mode") == "creative-translation")
            and current == "base_generated"
            and args.status in {"details_processed", "completed"}
            and not data.get("base_preview", {}).get("approved")
        ):
            raise SystemExit("Approve the base preview before continuing")
        if args.status == "completed":
            verify_delivery_gate(data)
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
    atomic_write_json(job_path, data)
    print(json.dumps({"job": str(job_path), "status": data["status"], "artifacts": len(data["artifacts"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
