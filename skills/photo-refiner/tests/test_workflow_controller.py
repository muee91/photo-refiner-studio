#!/usr/bin/env python3
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCRIPT = SCRIPTS / "workflow_controller.py"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("workflow_controller", SCRIPT)
workflow_controller = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(workflow_controller)


class WorkflowControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def base_job(self, **changes):
        job = {
            "status": "base_generated",
            "delivery_mode": "preview-first",
            "base_preview": {"required": True, "approved": False},
            "creative_preview": {"required": False, "approved": False},
            "creative_output": None,
            "detail": {"mode": "adaptive"},
            "hd_working_canvas_policy": {"routes": ["native-detail", "ultrasharp-detail", "full-canvas-tile-redraw"]},
            "patch_observations": [],
            "detail_blend_receipts": [],
            "tile_blend_receipts": [],
        }
        job.update(changes)
        return job

    def test_preview_checkpoint_does_not_guess_approval(self):
        decision = workflow_controller.decide(self.base_job(), self.job_dir)
        self.assertEqual(decision["next_action"], "await_base_review")
        self.assertTrue(decision["user_input_required"])

    def test_continue_at_preview_maps_to_exact_approval_action(self):
        decision = workflow_controller.decide(self.base_job(), self.job_dir, "continue")
        self.assertEqual(decision["next_action"], "record_base_approval")
        self.assertIn("--approve-base-preview", decision["command_hint"])

    def test_approved_base_routes_to_hd_preparation(self):
        job = self.base_job(base_preview={"required": True, "approved": True})
        decision = workflow_controller.decide(job, self.job_dir)
        self.assertEqual(decision["next_action"], "prepare_hd_working_canvas")
        self.assertFalse(decision["user_input_required"])

    def test_source_backed_raw_plan_is_normalized_without_user_tiling_choice(self):
        (self.job_dir / "detail-plan.raw.json").write_text(json.dumps({
            "regions": [],
            "delivery_feasibility": {"verdict": "needs-tiling"},
            "tiling_requirement": {"tile_count": 22, "consent_prompt": "choose 22 tiles or smaller delivery"},
        }), encoding="utf-8")
        job = self.base_job(
            base_preview={"required": True, "approved": True},
            hd_working_canvas={"route": "source-backed-detail"},
        )
        decision = workflow_controller.decide(job, self.job_dir)
        self.assertEqual(decision["next_action"], "apply_source_backing")
        self.assertFalse(decision["user_input_required"])
        self.assertNotIn("22", decision["visible_status"])

    def test_source_backed_zero_region_plan_can_finish_detail_stage(self):
        plan = self.job_dir / "detail-plan.source-backed.json"
        plan.write_text(json.dumps({"regions": [], "delivery_feasibility": {"verdict": "source-backed"}}), encoding="utf-8")
        job = self.base_job(
            base_preview={"required": True, "approved": True},
            hd_working_canvas={"route": "source-backed-detail"},
        )
        decision = workflow_controller.decide(job, self.job_dir)
        self.assertEqual(decision["next_action"], "mark_details_processed")

    def test_details_processed_runs_gate_before_completion(self):
        job = self.base_job(status="details_processed", base_preview={"required": True, "approved": True})
        decision = workflow_controller.decide(job, self.job_dir)
        self.assertEqual(decision["next_action"], "run_delivery_gate")
        job["delivery_gate"] = {"verdict": "pass"}
        decision = workflow_controller.decide(job, self.job_dir)
        self.assertEqual(decision["next_action"], "complete_job")

    def test_hd_master_creative_has_distinct_review_checkpoint(self):
        job = self.base_job(
            status="creative_generated",
            creative_output={"upstream_binding": "hd-master"},
            creative_preview={"required": True, "approved": False},
        )
        decision = workflow_controller.decide(job, self.job_dir)
        self.assertEqual(decision["next_action"], "await_creative_review")
        decision = workflow_controller.decide(job, self.job_dir, "approve")
        self.assertEqual(decision["next_action"], "record_creative_approval")
        self.assertIn("--approve-creative-preview", decision["command_hint"])

    def test_contract_normalization_includes_source_backed_route_and_hides_economics(self):
        job = self.base_job()
        changed = workflow_controller.normalize_contract(job)
        self.assertTrue(changed)
        self.assertEqual(job["hd_working_canvas_policy"]["routes"], workflow_controller.HD_ROUTES)
        self.assertEqual(
            job["hd_working_canvas_policy"]["user_facing_policy"],
            "hide-internal-route-and-patch-economics",
        )


if __name__ == "__main__":
    unittest.main()
