from __future__ import annotations

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


class SourceBackedRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SCRIPTS))
        import prepare_hd_working_canvas
        import delivery_gate
        cls.router = prepare_hd_working_canvas
        cls.delivery_gate = delivery_gate

    @classmethod
    def tearDownClass(cls):
        sys.path.pop(0)

    def test_source_width_photo_prefers_source_backing_over_full_canvas_redraw(self):
        route = self.router.choose_route(
            (1024, 1536),
            (4672, 7008),
            informative_engine_ready=False,
            source_backed=True,
        )
        self.assertEqual(route["route"], "source-backed-detail")
        self.assertFalse(route["requires_full_canvas_redraw"])

    def test_non_source_backed_canvas_still_uses_full_canvas_when_needed(self):
        route = self.router.choose_route(
            (1024, 1536),
            (4672, 7008),
            informative_engine_ready=False,
            source_backed=False,
        )
        self.assertEqual(route["route"], "full-canvas-tile-redraw")
        self.assertTrue(route["requires_full_canvas_redraw"])

    def test_subject_protection_disables_full_canvas_4x_route(self):
        route = self.router.choose_route(
            (1024, 1536),
            (3072, 4608),
            informative_engine_ready=True,
            source_backed=False,
            subject_protected=True,
        )
        self.assertEqual(route["route"], "full-canvas-tile-redraw")
        self.assertTrue(route["requires_full_canvas_redraw"])

    def test_subject_manifest_is_protected_from_upscaler(self):
        self.assertTrue(self.router.subject_protection_required({
            "detail": {"mode": "adaptive", "patch_scope": "head-and-face", "head_patch": True}
        }))
        self.assertFalse(self.router.subject_protection_required({
            "detail": {"mode": "base-only", "patch_scope": "none", "head_patch": False}
        }))


class SourceBackedPlanNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inserted = str(SCRIPTS) not in sys.path
        if inserted:
            sys.path.insert(0, str(SCRIPTS))
        import delivery_gate
        cls.delivery_gate = delivery_gate
        cls._inserted_scripts_path = inserted

    @classmethod
    def tearDownClass(cls):
        if cls._inserted_scripts_path:
            sys.path.remove(str(SCRIPTS))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_dir = self.root / "job"
        self.job_dir.mkdir()
        (self.job_dir / "intermediates").mkdir()

        self.source = self.root / "source.jpg"
        self.look = self.job_dir / "intermediates" / "look.png"
        self.hd = self.job_dir / "intermediates" / "hd-working.png"
        Image.new("RGB", (400, 600), (80, 100, 120)).save(self.source, quality=95)
        Image.new("RGB", (100, 150), (100, 110, 130)).save(self.look)
        Image.new("RGB", (400, 600), (95, 108, 128)).save(self.hd)

        self.job_path = self.job_dir / "job.json"
        self.plan_path = self.job_dir / "detail-plan.raw.json"
        self.output_path = self.job_dir / "detail-plan.source-backed.json"

        job = {
            "creative_recipe": None,
            "resolution": "source-width",
            "aspect_ratio": "original",
            "upscale_passes": [],
            "hd_working_canvas_policy": {"mode": "automatic"},
            "hd_working_canvas": {
                "schema_version": 2,
                "route": "source-backed-detail",
                "source_backed": True,
                "input": str(self.look.resolve()),
                "input_size": [100, 150],
                "input_sha256": sha256_file(self.look),
                "delivery_canvas": [400, 600],
                "output": str(self.hd.resolve()),
                "output_size": [400, 600],
                "output_sha256": sha256_file(self.hd),
                "source_detail_result": {
                    "source_master": str(self.source.resolve()),
                    "source_master_sha256": sha256_file(self.source),
                    "look_master": str(self.look.resolve()),
                    "look_master_sha256": sha256_file(self.look),
                },
            },
        }
        self.job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")

        plan = {
            "working_canvas": [400, 600],
            "delivery_canvas": [400, 600],
            "region_count": 1,
            "regions": [{
                "region_type": "face",
                "region_role": "face",
                "crop": {"x": 120, "y": 80, "width": 160, "height": 200},
            }],
            "regions_dropped_for_budget": [{
                "region_type": "costume",
                "region_role": "lower-costume",
                "crop_box": {"x": 60, "y": 280, "width": 280, "height": 300},
                "detail_ratio": 0.31,
                "threshold": 0.50,
                "max_honest_delivery_width": 220,
                "reason": "cannot serve the delivery canvas",
            }],
            "delivery_feasibility": {
                "verdict": "needs-tiling",
                "requested_delivery_width": 400,
                "max_honest_delivery_width": 220,
                "binding_regions": ["lower-costume"],
            },
            "tiling_requirement": {
                "required": True,
                "tile_count": 22,
                "estimated_generation_calls": 22,
                "consent_prompt": "Need about 22 tile redraws",
            },
        }
        self.plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_normalization_removes_tile_consent_and_records_source_geometry(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "apply_source_backing.py"),
                str(self.job_path),
                str(self.plan_path),
                "--output",
                str(self.output_path),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        normalized = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(normalized["delivery_feasibility"]["verdict"], "source-backed")
        self.assertEqual(normalized["regions_dropped_for_budget"], [])
        self.assertFalse(normalized["tiling_requirement"]["required"])
        self.assertFalse(normalized["tiling_requirement"]["user_confirmation_required"])
        self.assertEqual(normalized["tiling_requirement"]["estimated_generation_calls"], 0)
        self.assertEqual(normalized["source_backing"]["source_backed_region_count"], 1)
        self.assertEqual(
            normalized["source_backing"]["source_backed_regions"][0]["action"],
            "retain-source-master-detail",
        )

        job = json.loads(self.job_path.read_text(encoding="utf-8"))
        source_passes = [
            item for item in job["upscale_passes"]
            if item.get("engine") == "source-master-detail-lift"
        ]
        self.assertEqual(len(source_passes), 1)
        self.assertTrue(source_passes[0]["adds_information"])
        self.assertEqual(source_passes[0]["from"], [100, 150])
        self.assertEqual(source_passes[0]["information_to"], [400, 600])

        factor, passes = self.delivery_gate.information_raise(job, [100, 150])
        self.assertEqual(factor, 4.0)
        self.assertEqual(passes[0]["engine"], "source-master-detail-lift")


if __name__ == "__main__":
    unittest.main()
