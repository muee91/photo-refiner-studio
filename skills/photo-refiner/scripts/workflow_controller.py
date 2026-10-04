#!/usr/bin/env python3
"""Deterministic next-action controller for Photo Refiner jobs.

The model should not reconstruct the pipeline from prose after every user turn.
This controller reads durable job state and returns one semantic next action. It
never performs image generation and never invents user approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from job_contract import atomic_write_json

HD_ROUTES = [
    "native-detail",
    "source-backed-detail",
    "ultrasharp-detail",
    "full-canvas-tile-redraw",
]
EVENTS = {"inspect", "continue", "approve", "redo", "adjust"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def result(phase, next_action, visible_status, *, action_type="local", user_input_required=False,
           internal_reason="", script=None, requires=None, command_hint=None):
    value = {
        "phase": phase,
        "next_action": next_action,
        "action_type": action_type,
        "user_input_required": user_input_required,
        "visible_status": visible_status,
        "internal_reason": internal_reason,
        "requires": requires or [],
    }
    if script:
        value["script"] = script
    if command_hint:
        value["command_hint"] = command_hint
    return value


def creative_binding(job: dict) -> str:
    return (job.get("creative_output") or {}).get("upstream_binding") or ""


def gate_passed(job: dict) -> bool:
    return (job.get("delivery_gate") or {}).get("verdict") == "pass"


def plan_paths(job_dir: Path) -> dict[str, Path]:
    return {
        "raw": job_dir / "detail-plan.raw.json",
        "source_backed": job_dir / "detail-plan.source-backed.json",
        "final": job_dir / "detail-plan.final.json",
        "tile": job_dir / "tile-plan.json",
    }


def read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def effective_detail_plan(job_dir: Path) -> tuple[Path | None, dict | None]:
    paths = plan_paths(job_dir)
    for key in ("final", "source_backed", "raw"):
        value = read_json(paths[key])
        if value is not None:
            return paths[key], value
    return None, None


def detail_execution_complete(job: dict, plan_path: Path, plan: dict) -> bool:
    regions = plan.get("regions") or []
    if not regions:
        return True
    plan_sha = sha256_file(plan_path)
    observations = {
        item.get("planner_region_index")
        for item in (job.get("patch_observations") or [])
        if isinstance(item, dict)
        and item.get("evidence_kind") == "detail-patch"
        and item.get("evidence_plan_sha256") == plan_sha
        and (item.get("budget_recheck") or {}).get("accepted") is True
    }
    receipts = {
        item.get("planner_region_index")
        for item in (job.get("detail_blend_receipts") or [])
        if isinstance(item, dict)
        and item.get("kind") == "detail-patch"
        and item.get("detail_plan_sha256") == plan_sha
        and (item.get("registration") or {}).get("accepted") is True
    }
    expected = set(range(len(regions)))
    return expected.issubset(observations) and expected.issubset(receipts)


def tile_execution_complete(job: dict, plan_path: Path, plan: dict) -> bool:
    tiles = plan.get("tiles") or []
    if not tiles:
        return False
    plan_sha = sha256_file(plan_path)
    observations = {
        item.get("tile_index")
        for item in (job.get("patch_observations") or [])
        if isinstance(item, dict)
        and item.get("evidence_kind") == "tile-redraw"
        and item.get("evidence_plan_sha256") == plan_sha
        and (item.get("budget_recheck") or {}).get("accepted") is True
    }
    receipts = {
        item.get("tile_index")
        for item in (job.get("tile_blend_receipts") or [])
        if isinstance(item, dict)
        and item.get("kind") == "tile-redraw"
        and item.get("tile_plan_sha256") == plan_sha
        and (item.get("registration") or {}).get("accepted") is True
    }
    expected = {item.get("index") for item in tiles}
    return expected.issubset(observations) and expected.issubset(receipts)


def review_action(kind: str, event: str) -> dict:
    if event in {"approve", "continue"}:
        flag = "--approve-creative-preview" if kind == "creative" else "--approve-base-preview"
        artifact = "creative_preview" if kind == "creative" else "base_preview"
        return result(
            f"{kind}_review", f"record_{kind}_approval", "确认当前效果并继续",
            action_type="state", script="update_job.py", requires=["approved-image-path"],
            internal_reason="Bind the exact displayed bitmap before continuing.",
            command_hint=f"update_job.py <job.json> {flag} --artifact {artifact}=<approved-image>",
        )
    if event == "redo":
        return result(
            f"{kind}_review", f"regenerate_{kind}", "重新生成当前版本",
            action_type="provider", internal_reason="Restart from the last clean authority.",
        )
    if event == "adjust":
        return result(
            f"{kind}_review", "reopen_studio", "调整设置",
            action_type="user", internal_reason="Change the frozen edit brief before regenerating.",
        )
    return result(
        f"{kind}_review", f"await_{kind}_review", "请确认当前效果",
        action_type="user", user_input_required=True, requires=["approve", "redo", "adjust"],
        internal_reason="A configured review checkpoint is required.",
    )


def delivery_action(job: dict, *, from_status: str) -> dict:
    if not gate_passed(job):
        return result(
            "delivery", "run_delivery_gate", "正在检查最终成片",
            script="delivery_gate.py",
            internal_reason=f"{from_status} is ready but delivery has not been certified.",
        )
    return result(
        "state_transition", "complete_job", "成片检查通过",
        action_type="state", script="update_job.py",
        command_hint="update_job.py <job.json> --status completed",
    )


def decide(job: dict, job_dir: Path, event: str = "inspect") -> dict:
    if event not in EVENTS:
        raise ValueError(f"Unsupported workflow event: {event}")

    status = job.get("status")
    if status == "failed":
        return result("failed", "stop", "任务已失败", action_type="state")
    if status == "completed":
        return result("completed", "done", "已完成", action_type="state")
    if status == "initialized":
        return result(
            "preparation", "prepare_sources_and_prompt", "正在准备照片",
            script="prepare_source.py + build_edit_prompt.py",
            command_hint="prepare inputs/prompt, then update_job.py <job.json> --status prepared",
        )
    if status == "prepared":
        return result(
            "base_generation", "generate_base", "正在生成主效果",
            action_type="provider",
            internal_reason="Generate the complete base/creative effect with ChatGPT Images.",
        )

    if status == "base_generated":
        preview = job.get("base_preview") or {}
        if preview.get("required") and not preview.get("approved"):
            return review_action("base", event)

        hd = job.get("hd_working_canvas") or {}
        if not hd.get("route"):
            return result(
                "hd_preparation", "prepare_hd_working_canvas", "正在完成原图尺寸智能恢复",
                script="prepare_hd_working_canvas.py", requires=["exact-look-master"],
                internal_reason="No HD working-canvas route has been recorded yet.",
            )

        # Recovery disabled means no planner/patch stage. This is common for
        # base-only one-click jobs and recipe-controlled creative assemblies.
        detail_mode = (job.get("detail") or {}).get("mode")
        if detail_mode in {"base-only", "not-applicable"}:
            return delivery_action(job, from_status="base_generated/no-local-recovery")

        route = hd.get("route")
        paths = plan_paths(job_dir)
        if route == "full-canvas-tile-redraw":
            tile_plan = read_json(paths["tile"])
            if tile_plan is None:
                return result(
                    "detail_planning", "plan_full_canvas_redraw", "正在准备高清细节",
                    script="plan_detail_tiles.py + plan_tile_redraw.py",
                    requires=["vision-analysis", "observed-patch-size"],
                    internal_reason="Transformed canvas cannot be SOURCE MASTER-backed.",
                )
            if not tile_execution_complete(job, paths["tile"], tile_plan):
                return result(
                    "detail_generation", "generate_planned_tiles", "正在恢复高清细节",
                    action_type="provider", requires=["tile-plan.json"],
                    internal_reason="Not every selected tile has accepted observation + blend evidence.",
                )
            return result(
                "state_transition", "mark_details_processed", "高清细节已完成",
                action_type="state", script="update_job.py",
                command_hint="update_job.py <job.json> --status details_processed",
            )

        raw_plan = read_json(paths["raw"])
        source_plan = read_json(paths["source_backed"])
        final_plan = read_json(paths["final"])
        if raw_plan is None and source_plan is None and final_plan is None:
            return result(
                "detail_planning", "plan_details", "正在分析关键细节",
                script="plan_detail_tiles.py", requires=["vision-analysis", "observed-patch-size"],
                internal_reason=f"HD route {route} is ready but no detail plan exists.",
            )
        if route == "source-backed-detail" and source_plan is None and final_plan is None:
            return result(
                "detail_planning", "apply_source_backing", "正在保留原片真实细节",
                script="apply_source_backing.py", requires=["detail-plan.raw.json"],
                internal_reason="Normalize raw tiling pressure against the real SOURCE MASTER; never ask the user to choose tile count.",
            )

        plan_path, plan = effective_detail_plan(job_dir)
        if plan_path is None or plan is None:
            return result("detail_planning", "plan_details", "正在分析关键细节", script="plan_detail_tiles.py")
        if not detail_execution_complete(job, plan_path, plan):
            return result(
                "detail_generation", "generate_planned_patches", "正在恢复关键细节",
                action_type="provider", requires=[str(plan_path)],
                internal_reason="Generate only selected high-value regions; source-backed unselected regions retain SOURCE MASTER detail.",
            )
        return result(
            "state_transition", "mark_details_processed", "细节恢复已完成",
            action_type="state", script="update_job.py",
            command_hint="update_job.py <job.json> --status details_processed",
        )

    if status == "details_processed":
        if creative_binding(job) == "hd-master":
            return result(
                "creative_generation", "generate_creative_draft", "正在生成创意定稿预览",
                action_type="provider",
                internal_reason="HD photographic master is complete; render the creative draft next.",
            )
        return delivery_action(job, from_status="details_processed")

    if status == "creative_generated":
        preview = job.get("creative_preview") or {}
        if preview.get("required") and not preview.get("approved"):
            return review_action("creative", event)
        if not gate_passed(job):
            return result(
                "creative_delivery", "render_and_gate_creative_delivery", "正在完成高清创意成片",
                action_type="provider", requires=["approved-creative-preview"],
                internal_reason="Approved creative draft still needs final delivery-resolution redraw/evidence.",
            )
        return result(
            "state_transition", "complete_job", "创意成片检查通过",
            action_type="state", script="update_job.py",
            command_hint="update_job.py <job.json> --status completed",
        )

    return result(
        "unknown", "inspect_job", "正在检查任务状态",
        internal_reason=f"No controller rule matched status={status!r}.",
    )


def normalize_contract(job: dict) -> bool:
    changed = False
    policy = job.setdefault("hd_working_canvas_policy", {})
    if policy.get("routes") != HD_ROUTES:
        policy["routes"] = list(HD_ROUTES)
        changed = True
    if policy.get("user_facing_policy") != "hide-internal-route-and-patch-economics":
        policy["user_facing_policy"] = "hide-internal-route-and-patch-economics"
        changed = True
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Return the one deterministic next action for a Photo Refiner job.")
    parser.add_argument("job", type=Path, help="Path to job.json")
    parser.add_argument("--event", choices=sorted(EVENTS), default="inspect", help="Semantic user event; controller never invents approval")
    args = parser.parse_args()

    job_path = args.job.expanduser().resolve()
    if not job_path.is_file() or job_path.name != "job.json":
        raise SystemExit(f"Missing job manifest: {job_path}")
    data = json.loads(job_path.read_text(encoding="utf-8"))
    if normalize_contract(data):
        atomic_write_json(job_path, data)
    decision = decide(data, job_path.parent, args.event)
    decision.update({"event": args.event, "job": str(job_path), "controller_version": 1})
    print(json.dumps(decision, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
