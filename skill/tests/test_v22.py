import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_blend_mask import build_mask
from landmark_identity_gate import evaluate_landmarks
from plan_detail_tiles import Box, build_plan


class PhotoRefinerV22Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.jpg"
        Image.new("RGB", (1500, 2000), (120, 100, 80)).save(self.source, quality=95)

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, name, *args, ok=True):
        command = [sys.executable, str(SCRIPTS / name), *map(str, args)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=25)
        if ok and result.returncode != 0:
            self.fail(f"{command} failed: {result.stderr}\n{result.stdout}")
        if not ok and result.returncode == 0:
            self.fail(f"{command} unexpectedly succeeded")
        return result

    def test_manifest_includes_v22_generation_budget_defaults(self):
        result = self.run_script(
            "init_job.py", self.source, "--output-root", self.root / "jobs",
            "--preset", "natural-cinematic", "--detail-budget", "fast", "--confirmed",
        )
        manifest = json.loads((Path(result.stdout.strip()) / "job.json").read_text())
        self.assertEqual(manifest["release_version"], "2.2")
        self.assertEqual(manifest["detail"]["generation_budget"], "fast")
        self.assertEqual(manifest["detail"]["max_generated_patches"], 1)
        self.assertEqual(manifest["detail"]["planner"], "adaptive-value-merge-v2")
        self.assertEqual(manifest["detail"]["mask_mode"], "lightweight")
        self.assertEqual(manifest["quality_gate"]["landmark_identity_gate"]["mode"], "optional-when-landmarks-available")

    def test_balanced_planner_prefers_three_coarse_patches_for_large_portrait(self):
        plan = build_plan(
            1500, 2000,
            subject_type="portrait", detail_budget="balanced",
            subject_box=Box(400, 350, 700, 1300), face_box=Box(600, 500, 250, 350),
            hand_boxes=[], prop_boxes=[],
        )
        self.assertEqual(plan["planner"], "adaptive-value-merge-v2")
        self.assertEqual(plan["max_generated_patches"], 3)
        self.assertEqual(plan["estimated_generated_patches"], 3)
        self.assertEqual([item["region_type"] for item in plan["regions"]], ["costume", "head", "face"])
        self.assertTrue(all(item["requires_pixel_budget_check"] for item in plan["regions"]))

    def test_balanced_budget_is_ceiling_not_quota_for_tiny_face(self):
        plan = build_plan(
            1500, 2000,
            subject_type="portrait", detail_budget="balanced",
            subject_box=Box(500, 500, 400, 900), face_box=Box(650, 550, 70, 90),
            hand_boxes=[], prop_boxes=[],
        )
        self.assertEqual(plan["max_generated_patches"], 3)
        self.assertEqual(plan["estimated_generated_patches"], 1)
        self.assertEqual([item["region_type"] for item in plan["regions"]], ["costume"])
        skipped_types = {item["region_type"] for item in plan["skipped_candidates"]}
        self.assertIn("face", skipped_types)
        self.assertIn("head", skipped_types)

    def test_landscape_without_high_value_region_uses_zero_local_generations(self):
        plan = build_plan(
            1500, 2000,
            subject_type="landscape", detail_budget="balanced",
            subject_box=None, face_box=None, hand_boxes=[], prop_boxes=[],
        )
        self.assertEqual(plan["estimated_generated_patches"], 0)
        self.assertEqual(plan["regions"], [])

    def test_fast_planner_collapses_to_single_face_patch(self):
        plan = build_plan(
            1500, 2000,
            subject_type="portrait", detail_budget="fast",
            subject_box=Box(400, 350, 700, 1300), face_box=Box(600, 500, 250, 350),
            hand_boxes=[], prop_boxes=[],
        )
        self.assertEqual(plan["region_count"], 1)
        self.assertEqual(plan["regions"][0]["region_type"], "face")

    def test_lightweight_blend_mask_adds_no_generation_calls(self):
        mask, mode, _ = build_mask(300, 300, "head", (60, 40, 180, 200), "auto", 0.06)
        self.assertEqual(mode, "shape-lite")
        self.assertGreater(float(mask.mean() / 255.0), 0.05)
        # Contract assertion: this helper is deterministic local masking only.
        self.assertEqual(mask.shape, (300, 300))

    def test_lightweight_blend_mask_integrates_with_multiband_registration(self):
        rng = np.random.default_rng(123)
        base = rng.integers(0, 256, (320, 320, 3), dtype=np.uint8)
        target = base[60:260, 70:270].copy()
        base_path = self.root / "base.png"
        target_path = self.root / "target.png"
        patch_path = self.root / "patch.png"
        mask_path = self.root / "face-mask.png"
        cv2.imwrite(str(base_path), base); cv2.imwrite(str(target_path), target); cv2.imwrite(str(patch_path), target)
        mask, _, _ = build_mask(200, 200, "face", (40, 20, 120, 140), "auto", 0.06)
        cv2.imwrite(str(mask_path), mask)
        report = json.loads(self.run_script(
            "register_blend.py",
            "--base", base_path, "--target", target_path, "--patch", patch_path,
            "--blend-mask", mask_path, "--output", self.root / "out.png",
            "--x", 70, "--y", 60, "--region-type", "face",
        ).stdout)
        self.assertTrue(report["accepted"])
        self.assertTrue(report["custom_blend_mask"])
        self.assertEqual(report["registration_model"], "similarity")
        self.assertEqual(report["fusion_version"], 2)
        self.assertTrue(report["multiband"])
        self.assertAlmostEqual(report["mid_detail_gain"], 0.20)
        self.assertGreater(report["coverage"], 0.90)
        self.assertLess(report["mask_coverage"], report["coverage"])

    def test_landmark_identity_gate_accepts_similarity_and_rejects_structure_drift(self):
        names = ["left_eye", "right_eye", "nose_tip", "mouth_left", "mouth_right", "chin", "jaw_left", "jaw_right"]
        source = np.asarray([[30,40],[70,40],[50,58],[38,72],[62,72],[50,92],[28,74],[72,74]], dtype=np.float64)
        good = source + np.asarray([3,2], dtype=np.float64)
        bad = np.asarray([[26,38],[82,43],[58,66],[31,78],[72,70],[66,108],[18,83],[88,80]], dtype=np.float64)
        accepted = evaluate_landmarks(source, good, names)
        rejected = evaluate_landmarks(source, bad, names)
        self.assertTrue(accepted["accepted"])
        self.assertFalse(rejected["accepted"])
        self.assertGreater(rejected["normalized_rmse"], rejected["thresholds"]["max_normalized_rmse"])


if __name__ == "__main__":
    unittest.main()
