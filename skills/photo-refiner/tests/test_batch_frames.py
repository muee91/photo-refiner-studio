#!/usr/bin/env python3
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


class BatchFrameAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sources = []
        for index, color in enumerate(((80, 110, 140), (140, 100, 80))):
            path = self.root / f"source-{index}.jpg"
            Image.new("RGB", (900 + index * 20, 1200), color).save(path, quality=95)
            self.sources.append(path)
        self.master = self.root / "master.png"
        Image.new("RGB", (1024, 1365), (100, 120, 100)).save(self.master)
        self.job = self.root / "job.json"
        parent = {
            "version": 2,
            "release_version": "2.4",
            "created_at": "2026-10-05T00:00:00+00:00",
            "status": "base_generated",
            "working_color_space": "sRGB",
            "execution_mode": "photo-refinement",
            "creative_recipe": None,
            "creative_output": None,
            "workflow": "batch",
            "ui_mode": "simple",
            "sources": [str(p.resolve()) for p in self.sources],
            "source_records": [
                {"path": str(p.resolve()), "size": p.stat().st_size, "sha256": sha256_file(p)}
                for p in self.sources
            ],
            "preset": "natural-cinematic",
            "resolved_prompt": {"preset": "natural-cinematic", "label": "自然电影感", "prompt": "test", "avoid": ""},
            "aspect_ratio": "original",
            "framing": "preserve",
            "resolution": "source-width",
            "delivery_mode": "preview-first",
            "base_preview": {"required": False, "approved": False},
            "creative_preview": {"required": False, "approved": False},
            "output_format": "jpg",
            "batch": {
                "consistency": "balanced",
                "master_frame": str(self.master.resolve()),
                "shared_identity": True,
                "shared_scene": True,
                "shared_prompt": True,
                "master_frame_approved": True,
            },
            "detail": {"mode": "adaptive", "generation_budget": "balanced"},
            "retouch": {"style_strength": 45, "detail_strength": 60},
            "quality_gate": {},
            "output": {"separate_job_folder": True, "keep_intermediates": False},
            "hd_working_canvas_policy": {"mode": "automatic", "routes": ["native-detail", "source-backed-detail", "ultrasharp-detail", "full-canvas-tile-redraw"]},
            "upscale_passes": [],
            "patch_observations": [],
            "patch_observation_summary": {"count": 0, "size_match_count": 0, "size_mismatch_count": 0, "actual_sizes": [], "requested_sizes": []},
            "artifacts": [],
            "history": [{"status": "base_generated", "at": "2026-10-05T00:00:00+00:00"}],
        }
        self.job.write_text(json.dumps(parent, indent=2), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, script, *args):
        result = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_frames_share_style_but_never_source_authority(self):
        bound = self.run_script("bind_batch_master.py", self.job)
        authority = bound["style_authority"]
        self.assertEqual(authority["sha256"], sha256_file(self.master))
        self.assertIn("identity", authority["does_not_own"])

        result = self.run_script("batch_frames.py", self.job, "--materialize")
        self.assertEqual(result["frame_count"], 2)
        children = [json.loads(Path(item["child_job"]).read_text(encoding="utf-8")) for item in result["frames"]]
        self.assertEqual(children[0]["workflow"], "single")
        self.assertEqual(children[0]["delivery_mode"], "one-click")
        self.assertEqual(children[0]["sources"], [str(self.sources[0].resolve())])
        self.assertEqual(children[1]["sources"], [str(self.sources[1].resolve())])
        self.assertNotEqual(
            children[0]["batch_frame"]["source_authority"]["sha256"],
            children[1]["batch_frame"]["source_authority"]["sha256"],
        )
        self.assertEqual(
            children[0]["batch_frame"]["shared_style_authority"]["sha256"],
            children[1]["batch_frame"]["shared_style_authority"]["sha256"],
        )
        self.assertEqual(children[0]["batch_frame"]["authority_rule"], "share-appearance-never-share-photographic-facts")

    def test_parent_finalizes_only_after_every_child_completed(self):
        self.run_script("bind_batch_master.py", self.job)
        result = self.run_script("batch_frames.py", self.job, "--materialize")
        for item in result["frames"]:
            child_path = Path(item["child_job"])
            child = json.loads(child_path.read_text(encoding="utf-8"))
            child["status"] = "completed"
            child_path.write_text(json.dumps(child, indent=2), encoding="utf-8")
        final = self.run_script("batch_frames.py", self.job, "--finalize")
        self.assertTrue(final["all_completed"])
        parent = json.loads(self.job.read_text(encoding="utf-8"))
        self.assertEqual(parent["status"], "completed")
        self.assertTrue(parent["batch"]["completed"])


if __name__ == "__main__":
    unittest.main()
