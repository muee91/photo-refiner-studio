#!/usr/bin/env python3
"""Deterministic next-action controller for Photo Refiner jobs.

The language model should not infer the pipeline from prose after every user turn.
This controller reads job.json plus durable job artifacts and returns one semantic
next action. It never performs image generation and it never fabricates approval.

It may normalize non-semantic metadata (currently the canonical HD route list) so
old jobs created before a metadata fix remain resumable.
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


def _result(
    phase: str,
    next_action: str,
    *,
    visible_status: str,
    user_input_required: bool = False,
    action_type: str = "local",
    internal_reason: str = "",
    script: str | None = None,
    requires: list[str] | None = None,
    command_hint: str | None = None,
) -> dict:
    payload = {
        "phase": phase,
        "next_action": next_action,
        "action_type": action_type,
        "user_input_required": user_input_required,
        "visible_status": visible_status,
        "internal_reason": internal_reason,
        "requires": requires or [],
    }
    if script:
        payload["script"] = script
    if command_hint:
        payload["command_hint"] = command_hint
    return payload


def _creative_binding(job: dict) -> str:
    return (job.get("creative_output") or {}).get("upstream_binding") or ""


def _gate_passed(job: dict) -> bool:
    return (job.get("delivery_gate") or {}).get("verdict") == "pass"


def _plan_candidates(job_dir: Path) -> dict[str, Path]:
    return {
        "raw": job_dir / "detail-plan.raw.json",
        "source_backed": job_dir / "detail-plan.source-backed.json",
        "final": job_dir / "detail-plan.final.json",
        "tile": job_dir / "tile-plan.json",
    }


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _effective_detail_plan(job_dir: Path) -> tuple[Path | None, dict | None]:
    candidates = _plan_candidates(job_dir)
    for key in ("final", "source_backed", "raw"):
        plan = _read_json(candidates[key])
        if plan is not None:
            return candidates[key], plan
    return None, None


def _detail_execution_complete(job: dict, plan_path: Path, plan: dict) -> bool:
    regions = plan.get("regions") or []
    if not regions:
        return True
    plan_sha = sha256_file(plan_path)
    observations = [
        item for item in (job.get("patch_observations") or [])
        if isinstance(item, dict)
        and item.get("evidence_kind") == "detail-patch"
        and item.get("evidence_plan_sha256") == plan_sha
        and (item.get("budget_recheck") or {}).get("accepted") is True
    ]
    receipts = [
        item for item in (job.get("detail_blend_receipts") or [])
        if isinstance(item, dict)
        and item.get("kind") == "detail-patch"
        and item.get("detail_plan_sha256") == plan_sha
        and (item.get("registration") or {}).get("accepted") is True
    ]
    observed_indices = {item.get("planner_region_index") for item in observations}
    receipt_indices = {item.get("planner_region_index") for item in receipts}
    expected = set(range(len(regions)))
    return expected.issubset(observed_indices) and expected.issubset(receipt_indices)


def _tile_execution_complete(job: dict, plan_path: Path, plan: dict) -> bool:
    tiles = plan.get("tiles") or []
    if not tiles:
        return False
    plan_sha = sha256_file(plan_path)
    observations = [
        item for item in (job.get("patch_observations") or [])
        if isinstance(item, dict)
        and item.get("evidence_kind") == "tile-redraw"
        and item.get("evidence_plan_sha256") == plan_sha
        and (item.get("budget_recheck") or {}).get("accepted") is True
    ]
    receipts = [
        item for item in (job.get("tile_blend_receipts") or [])
        if isinstance(item, dict)
        and item.get("kind") == "tile-redraw"
        and item.get("tile_plan_sha256") == plan_sha
        and (item.get("registration") or {}).get("accepted") is True
    ]
    observed = {item.get("tile_index") for item in observations}
    blended = {item.get("tile_index") for item in receipts}
    expected = {item.get("index") for item in tiles}
    return expected.issubset(observed) and expected.issubset(blended)


def _review_action(kind: str, event: str) -> dict:
    if event in {"approve", "continue"}:
        flag = "--approve-creative-preview" if kind == "creative" else "--approve-base-preview"
        artifact_kind = "creative_preview" if kind == "creative" else "base_preview"
        return _result(
            f"{kind}_review",
            f"record_{kind}_approval",
            visible_status="确认当前效果并继续",
            action_type="state",
            internal_reason="The user approved the exact review checkpoint; bind that bitmap before continuing.",
            script="update_job.py",
            requires=["approved-image-path"],
            command_hint=f"update_job.py <job.json> {flag} --artifact {artifact_kind}=<approved-image>",
        )
    if event == "redo":
        return _result(
            f"{kind}_review",
            f"regenerate_{kind}",
            visible_status="重新生成当前版本",
            action_type="provider",
            internal_reason="The user rejected the current checkpoint; restart from the last clean authority.",
        )
    if event == "adjust":
        return _result(
            f"{kind}_review",
            "reopen_studio",
            visible_status="调整设置",
            action_type="user",
            internal_reason="The user wants to change the frozen edit brief before another generation.",
        )
    return _result(
        f"{kind}_review",
        f"await_{kind}_review",
        visible_status="请确认当前效果",
        user_input_required=True,
        action_type="user",
        internal_reason="A configured review checkpoint is required before downstream HD/detail work.",
        requires=["approve", "redo", "adjust"],
    )


def decide(job: dict, job_dir: Path, event: str = "inspect") -> dict:
    if event not in EVENTS:
        raise ValueError(f"Unsupported workflow event: {event}")

    status = job.get("status")
    if status == "failed":
        return _result("failed", "stop", visible_status="任务已失败", action_type="state", internal_reason="job.status is failed")
    if status == "completed":
        return _result("completed", "done", visible_status="已完成", action_type="state", internal_reason="job.status is completed")
    if status == "initialized":
        return _result(
            "preparation",
            "prepare_sources_and_prompt",
            visible_status="正在准备照片",
            action_type="local",
            script="prepare_source.py + build_edit_prompt.py",
            internal_reason="The job exists but normalized inputs/edit brief have not been marked prepared.",
        )
    if status == "prepared":
        return _result(
            "base_generation",
            "generate_base",
            visible_status="正在生成主效果",
            action_type="provider",
            internal_reason="Prepared job needs a complete base/creative effect render from ChatGPT Images.",
        )

    if status == "base_generated":
        preview = job.get("base_preview") or {}
        if preview.get("required") and not preview.get("approved"):
            return _review_action("base", event)

        hd = job.get("hd_working_canvas") or {}
        if not hd.get("route"):
            return _result(
                "hd_preparation",
                "prepare_hd_working_canvas",
                visible_status="正在完成原图尺寸智能恢复",
                action_type="local",
                script="prepare_hd_working_canvas.py",
                internal_reason="No HD working-canvas route has been recorded yet.",
                requires=["exact-look-master"],
            )

        route = hd.get("route")
        plans = _plan_candidates(job_dir)
        if route == "full-canvas-tile-redraw":
            tile_plan = _read_json(plans["tile"])
            if tile_plan is None:
                return _result(
                    "detail_planning",
                    "plan_full_canvas_redraw",
                    visible_status="正在准备高清细节",
                    action_type="local",
                    script="plan_detail_tiles.py + plan_tile_redraw.py",
                    internal_reason="This transformed canvas cannot be source-backed and requires full delivery coverage.",
                    requires=["vision-analysis", "observed-patch-size"],
                )
            if not _tile_execution_complete(job, plans["tile"], tile_plan):
                return _result(
                    "detail_generation",
                    "generate_planned_tiles",
                    visible_status="正在恢复高清细节",
                    action_type="provider",
                    internal_reason="The tile plan exists but not every tile has accepted observation + blend evidence.",
                    requires=["tile-plan.json"],
                )
            return _result(
                "state_transition",
                "mark_details_processed",
                visible_status="高清细节已完成",
                action_type="state",
                script="update_job.py",
                command_hint="update_job.py <job.json> --status details_processed",
            )

        raw_plan = _read_json(plans["raw"])
        source_plan = _read_json(plans["source_backed"])
        final_plan = _read_json(plans["final"])
        if raw_plan is None and final_plan is None and source_plan is None:
            return _result(
                "detail_planning",
                "plan_details",
                visible_status="正在分析关键细节",
                action_type="local",
                script="plan_detail_tiles.py",
                internal_reason=f"HD route {route} is ready but no detail plan exists.",
                requires=["vision-analysis", "observed-patch-size"],
            )
        if route == "source-backed-detail" and source_plan is None and final_plan is None:
            return _result(
                "detail_planning",
                "apply_source_backing",
                visible_status="正在保留原片真实细节",
                action_type="local",
                script="apply_source_backing.py",
                internal_reason="Raw tiling pressure must be normalized against the real SOURCE MASTER before patch execution.",
                requires=["detail-plan.raw.json"],
            )

        plan_path, plan = _effective_detail_plan(job_dir)
        if plan_path is None or plan is None:
            return _result("detail_planning", "plan_details", visible_status="正在分析关键细节", script="plan_detail_tiles.py")
        if not _detail_execution_complete(job, plan_path, plan):
            return _result(
                "detail_generation",
                "generate_planned_patches",
                visible_status="正在恢复关键细节",
                action_type="provider",
                internal_reason="Only selected high-value regions require generation; unselected source-backed regions stay on SOURCE MASTER detail.",
                requires=[str(plan_path)],
            )
        return _result(
            "state_transition",
            "mark_details_processed",
            visible_status="细节恢复已完成",
            action_type="state",
            script="update_job.py",
            command_hint="update_job.py <job.json> --status details_processed",
        )

    if status == "details_processed":
        if _creative_binding(job) == "hd-master":
            return _result(
                "creative_generation",
                "generate_creative_draft",
                visible_status="正在生成创意定稿预览",
                action_type="provider",
                internal_reason="HD master is complete; hd-master creative chains now render the creative draft.",
            )
        if not _gate_passed(job):
            return _result(
                "delivery",
                "run_delivery_gate",
                visible_status="正在检查最终成片",
                action_type="local",
                script="delivery_gate.py",
                internal_reason="Detail execution is complete but delivery has not been certified.",
            )
        return _result(
            "state_transition",
            "complete_job",
            visible_status="成片检查通过",
            action_type="state",
            script="update_job.py",
            command_hint="update_job.py <job.json> --status completed",
        )

    if status == "creative_generated":
        preview = job.get("creative_preview") or {}
        if preview.get("required") and not preview.get("approved"):
            return _review_action("creative", event)
        if not _gate_passed(job):
            return _result(
                "creative_delivery",
                "render_and_gate_creative_delivery",
                visible_status="正在完成高清创意成片",
                action_type="provider",
                internal_reason="Approved creative draft still needs its final delivery-resolution redraw/evidence chain before gating.",
                requires=["approved-creative-preview"],
            )
        return _result(
            "state_transition",
            "complete_job",
            visible_status="创意成片检查通过",
            action_type="state",
            script="update_job.py",
            command_hint="update_job.py <job.json> --status completed",
        )

    return _result(
        "unknown",
        "inspect_job",
        visible_status="正在检查任务状态",
        action_type="local",
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
    decision["event"] = args.event
    decision["job"] = str(job_path)
    decision["controller_version"] = 1
    print(json.dumps(decision, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
