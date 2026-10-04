#!/usr/bin/env python3
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("workflow_controller", SCRIPTS / "workflow_controller.py")
workflow_controller = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(workflow_controller)


class BatchControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def parent(self, **changes):
        job = {
            "status": "base_generated",
            "workflow": "batch",
            "execution_mode": "photo-refinement",
            "creative_output": None,
            "batch": {
                "master_frame_approved": False,
                "frames": [],
            },
        }
        job.update(changes)
        return job

    def test_batch_master_uses_review_checkpoint(self):
        decision = workflow_controller.decide(self.parent(), self.root)
        self.assertEqual(decision["next_action"], "await_batch_master_review")
        self.assertEqual(decision["review_checkpoint"], "batch-master")
        self.assertTrue(decision["user_input_required"])

    def test_approved_master_binds_style_before_materialization(self):
        job = self.parent(batch={"master_frame_approved": True, "frames": []})
        decision = workflow_controller.decide(job, self.root)
        self.assertEqual(decision["next_action"], "bind_batch_style_authority")
        job["batch"]["style_authority"] = {"path": "master.png", "sha256": "abc"}
        decision = workflow_controller.decide(job, self.root)
        self.assertEqual(decision["next_action"], "materialize_batch_frames")

    def test_parent_delegates_one_child_without_sharing_other_frame_state(self):
        child_dir = self.root / "frame-0"
        child_dir.mkdir()
        child_path = child_dir / "job.json"
        child_path.write_text(json.dumps({
            "status": "prepared",
            "workflow": "single",
            "execution_mode": "photo-refinement",
            "creative_output": None,
            "detail": {"mode": "adaptive"},
            "batch_frame": {
                "frame_index": 0,
                "source_authority": {"sha256": "frame-source"},
                "shared_style_authority": {"sha256": "style"},
            },
        }), encoding="utf-8")
        job = self.parent(batch={
            "master_frame_approved": True,
            "style_authority": {"path": "master.png", "sha256": "style"},
            "frames": [{"index": 0, "child_job": str(child_path), "status": "prepared"}],
        })
        decision = workflow_controller.decide(job, self.root)
        self.assertEqual(decision["next_action"], "process_batch_frame")
        self.assertEqual(decision["frame_index"], 0)
        self.assertEqual(decision["child_decision"]["next_action"], "generate_base")
        self.assertEqual(decision["child_decision"]["shared_style_authority"]["sha256"], "style")

    def test_all_completed_children_finalize_parent(self):
        child_dir = self.root / "frame-0"
        child_dir.mkdir()
        child_path = child_dir / "job.json"
        child_path.write_text(json.dumps({"status": "completed", "workflow": "single", "execution_mode": "photo-refinement"}), encoding="utf-8")
        job = self.parent(batch={
            "master_frame_approved": True,
            "style_authority": {"path": "master.png", "sha256": "style"},
            "frames": [{"index": 0, "child_job": str(child_path), "status": "completed"}],
        })
        decision = workflow_controller.decide(job, self.root)
        self.assertEqual(decision["next_action"], "finalize_batch")


if __name__ == "__main__":
    unittest.main()
