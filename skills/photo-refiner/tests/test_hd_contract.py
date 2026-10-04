"""Focused v2.4 HD contract after the Plugin 1.0 architecture split."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import delivery_gate
import job_contract
import prepare_hd_working_canvas


class HdContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.jpg"
        Image.new("RGB", (1024, 1536), (90, 120, 150)).save(self.source, quality=95)

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, name, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / name), *map(str, args)],
            capture_output=True,
            text=True,
            timeout=40,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def init_job(self, *extra):
        result = self.run_script(
            "init_job.py",
            self.source,
            "--output-root", self.root / "jobs",
            "--preset", "natural-cinematic",
            "--confirmed",
            *extra,
        )
        return Path(result.stdout.strip().splitlines()[-1])

    def test_skill_version_and_face_pixel_budget_are_pinned(self):
        heading = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8").splitlines()[5]
        self.assertEqual(heading, f"# Photo Refiner v{job_contract.SKILL_VERSION}")
        self.assertEqual(job_contract.SKILL_VERSION, "2.4")
        self.assertEqual(job_contract.PIXEL_BUDGET_THRESHOLDS["face"], 0.85)

    def test_hd_router_uses_native_ultrasharp_then_full_canvas(self):
        native = prepare_hd_working_canvas.choose_route((2000, 3000), (2048, 3072), True)
        self.assertEqual(native["route"], "native-detail")

        ai = prepare_hd_working_canvas.choose_route((1024, 1536), (3072, 4608), True)
        self.assertEqual(ai["route"], "ultrasharp-detail")
        self.assertEqual(ai["model_scale"], 3)

        tiled = prepare_hd_working_canvas.choose_route((1024, 1536), (4672, 7008), True)
        self.assertEqual(tiled["route"], "full-canvas-tile-redraw")
        self.assertTrue(tiled["requires_full_canvas_redraw"])

        no_engine = prepare_hd_working_canvas.choose_route((1024, 1536), (2048, 3072), False)
        self.assertEqual(no_engine["route"], "full-canvas-tile-redraw")

    def test_ultrasharp_file_size_cannot_exceed_its_information_boundary(self):
        data = {"upscale_passes": [{
            "engine": "4x-ultrasharp-spandrel",
            "adds_information": True,
            "from": [1024, 1536],
            "to": [6144, 9216],
            "information_to": [4096, 6144],
            "native_information_scale": 4,
            "interpolated_tail": [2048, 3072],
        }]}
        factor, passes = delivery_gate.information_raise(data, [1024, 1536])
        self.assertEqual(factor, 4.0)
        self.assertEqual(passes[0]["information_to"], [4096, 6144])
        self.assertEqual(passes[0]["to"], [6144, 9216])

    def test_interpolated_tail_cannot_be_laundered_through_a_second_ai_pass(self):
        data = {"upscale_passes": [
            {
                "engine": "4x-ultrasharp-spandrel",
                "adds_information": True,
                "from": [1024, 1536],
                "to": [6144, 9216],
                "information_to": [4096, 6144],
            },
            {
                "engine": "4x-ultrasharp-spandrel",
                "adds_information": True,
                "from": [6144, 9216],
                "to": [24576, 36864],
                "information_to": [24576, 36864],
            },
        ]}
        factor, passes = delivery_gate.information_raise(data, [1024, 1536])
        self.assertEqual(factor, 4.0)
        self.assertEqual(len(passes), 1)

    def test_tile_planner_binds_canvas_and_preserves_face_threshold(self):
        canvas = self.root / "canvas.png"
        Image.new("RGB", (1200, 1600), (80, 90, 100)).save(canvas)
        result = self.run_script(
            "plan_tile_redraw.py",
            "--image", canvas,
            "--observed-patch-size", "768x768",
            "--region-box", "350,300,420,520",
            "--region-type", "face",
            "--sliver-margin", "0",
        )
        plan = json.loads(result.stdout)
        self.assertEqual(plan["verdict"], "pass")
        self.assertEqual(plan["canvas"], [1200, 1600])
        self.assertEqual(Path(plan["canvas_path"]), canvas.resolve())
        self.assertEqual(plan["canvas_sha256"], hashlib.sha256(canvas.read_bytes()).hexdigest())
        self.assertGreater(plan["tile_count"], 0)
        self.assertEqual(plan["estimated_generation_calls"], plan["tile_count"])
        for tile in plan["tiles"]:
            self.assertEqual(tile["region_type"], "face")
            self.assertEqual(tile["threshold"], 0.85)
            self.assertGreaterEqual(tile["budget_ratio"], tile["threshold"])

    def test_full_canvas_plan_has_no_holes_or_delegated_slivers(self):
        canvas = self.root / "full.png"
        Image.new("RGB", (1024, 1536), (80, 90, 100)).save(canvas)
        result = self.run_script(
            "plan_tile_redraw.py",
            "--image", canvas,
            "--observed-patch-size", "768x768",
            "--full-canvas",
            "--sliver-margin", "0",
        )
        plan = json.loads(result.stdout)
        self.assertEqual(plan["verdict"], "pass")
        self.assertIn("full_canvas", plan["provenance"]["source"])
        self.assertEqual(plan["coverage"]["hole_area"], 0)
        self.assertEqual(plan["coverage"]["sliver_area"], 0)
        self.assertEqual(len(plan["blend_sequence"]), plan["tile_count"])
        self.assertEqual(set(plan["blend_sequence"]), {tile["index"] for tile in plan["tiles"]})

    def test_delivery_gate_fails_closed_when_recovery_evidence_is_missing(self):
        job_dir = self.init_job("--detail-mode", "adaptive", "--resolution", "1024x1536")
        job = job_dir / "job.json"
        generated = job_dir / "generated.png"
        Image.new("RGB", (1024, 1536), (90, 120, 150)).save(generated)
        prepared = job_dir / "intermediates" / "hd-working.png"
        self.run_script(
            "prepare_hd_working_canvas.py",
            job,
            "--input", generated,
            "--output", prepared,
            "--delivery-size", "1024x1536",
        )
        rejected = self.run_script(
            "delivery_gate.py",
            job,
            "--master", prepared,
            "--final", prepared,
            ok=False,
        )
        self.assertEqual(rejected.returncode, 3)
        report = json.loads(rejected.stdout)
        self.assertEqual(report["verdict"], "fail")
        self.assertIn(report["budget"].get("reason"), {"missing_detail_plan", "missing_detail_plan_or_full_canvas_tile_plan"})

    def test_current_one_click_job_cannot_use_an_unbound_enlarged_master(self):
        job_dir = self.init_job("--detail-mode", "base-only", "--delivery-mode", "one-click", "--resolution", "1024x1536")
        job = job_dir / "job.json"
        master = job_dir / "master.png"
        Image.new("RGB", (1024, 1536), (90, 120, 150)).save(master)
        rejected = self.run_script(
            "delivery_gate.py",
            job,
            "--master", master,
            "--final", master,
            ok=False,
        )
        self.assertEqual(rejected.returncode, 3)
        report = json.loads(rejected.stdout)
        self.assertFalse(report["geometry"]["reference_evidence_ok"])
        self.assertIn("prepare_hd_working_canvas", report["required_action"])


if __name__ == "__main__":
    unittest.main()
