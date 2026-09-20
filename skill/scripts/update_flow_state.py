#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

TERMINAL_OK = {"approved", "completed", "skipped"}
ALLOWED = {
    "pending": {"running", "skipped", "failed"},
    "running": {"waiting-approval", "completed", "failed"},
    "waiting-approval": {"approved", "failed"},
    "approved": {"completed"},
    "completed": set(),
    "skipped": set(),
    "failed": set(),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Advance one Photo Refiner Flow execution-plan step.")
    parser.add_argument("job", type=Path)
    parser.add_argument("--step", required=True)
    parser.add_argument("--state", required=True, choices=sorted(ALLOWED))
    parser.add_argument("--note", default="")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--artifact-kind", default="flow-step")
    args = parser.parse_args()

    job_path = args.job.expanduser().resolve()
    if not job_path.is_file() or job_path.name != "job.json":
        raise SystemExit(f"Missing job manifest: {job_path}")
    data = json.loads(job_path.read_text(encoding="utf-8"))
    if data.get("product") != "photo-refiner-flow":
        raise SystemExit("This is not a Photo Refiner Flow job")
    flow = data.get("flow")
    if not isinstance(flow, dict) or not isinstance(flow.get("steps"), list):
        raise SystemExit("Flow job is missing compiled execution steps")

    steps = flow["steps"]
    index = next((i for i, step in enumerate(steps) if step.get("id") == args.step), None)
    if index is None:
        raise SystemExit(f"Unknown Flow step: {args.step}")
    step = steps[index]
    current = step.get("state", "pending")
    if current not in ALLOWED:
        raise SystemExit(f"Unknown current Flow state: {current}")
    if args.state == current:
        print(json.dumps({"job": str(job_path), "step": args.step, "state": current}, ensure_ascii=False))
        return
    if args.state not in ALLOWED[current]:
        raise SystemExit(f"Invalid Flow step transition: {current} -> {args.state}")

    if args.state == "running":
        blockers = [
            earlier.get("id")
            for earlier in steps[:index]
            if earlier.get("state") not in TERMINAL_OK
        ]
        if blockers:
            raise SystemExit("Complete earlier Flow steps first: " + ", ".join(blockers))

    now = datetime.now().astimezone().isoformat()
    step["state"] = args.state
    step["updated_at"] = now
    if args.note.strip():
        step["note"] = args.note.strip()

    if args.artifact is not None:
        artifact = args.artifact.expanduser().resolve()
        if not artifact.is_file():
            raise SystemExit(f"Missing artifact: {artifact}")
        if not artifact.is_relative_to(job_path.parent):
            raise SystemExit("Flow artifacts must stay inside the job directory")
        record = {
            "kind": args.artifact_kind,
            "step": args.step,
            "path": str(artifact),
            "size": artifact.stat().st_size,
            "sha256": sha256_file(artifact),
            "recorded_at": now,
        }
        step.setdefault("artifacts", []).append(record)
        data.setdefault("artifacts", []).append(record)

    flow["current_step"] = None if args.state in TERMINAL_OK else args.step
    states = [item.get("state", "pending") for item in steps]
    if "failed" in states:
        data["status"] = "failed"
    elif all(state in TERMINAL_OK for state in states):
        data["status"] = "completed"
        flow["current_step"] = None
    elif "waiting-approval" in states:
        data["status"] = "waiting-approval"
    else:
        data["status"] = "running"

    data["updated_at"] = now
    data.setdefault("history", []).append({
        "event": "flow-step",
        "step": args.step,
        "state": args.state,
        "at": now,
        **({"note": args.note.strip()} if args.note.strip() else {}),
    })

    temp = job_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(job_path)
    print(json.dumps({
        "job": str(job_path),
        "step": args.step,
        "state": args.state,
        "jobStatus": data["status"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
