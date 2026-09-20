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
from plan_detail_tiles import Box, build_plan, load_vision_analysis


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
        self.assertEqual(manifest["release_version"], "2.4")
        self.assertEqual(manifest["detail"]["generation_budget"], "fast")
        self.assertEqual(manifest["detail"]["soft_generated_patch_budget"], 1)
        self.assertEqual(manifest["detail"]["hard_generated_patch_ceiling"], 1)
        self.assertEqual(manifest["detail"]["max_generated_patches"], 1)
        self.assertEqual(manifest["detail"]["planner"], "adaptive-value-merge-v2.2")
        self.assertEqual(manifest["detail"]["mask_mode"], "lightweight")
        self.assertEqual(manifest["quality_gate"]["landmark_identity_gate"]["mode"], "optional-when-landmarks-available")

    def test_patch_observation_records_actual_file_dimensions_and_mismatch(self):
        result = self.run_script(
            "init_job.py", self.source, "--output-root", self.root / "observed-jobs",
            "--preset", "natural-cinematic", "--detail-budget", "balanced", "--confirmed",
        )
        job_dir = Path(result.stdout.strip())
        job_path = job_dir / "job.json"
        patch = job_dir / "intermediates" / "patches" / "face.png"
        patch.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1024, 768), (90, 80, 70)).save(patch)

        observation = json.loads(self.run_script(
            "record_patch_observation.py", job_path,
            "--patch", patch,
            "--region-type", "face",
            "--region-role", "face",
            "--requested-size", "1536x1536",
            "--source-crop-size", "800x800",
            "--final-region-size", "900x900",
            "--planner-region-index", 2,
            "--attempt", 1,
        ).stdout)
        self.assertEqual(observation["requested_size"], [1536, 1536])
        self.assertEqual(observation["actual_size"], [1024, 768])
        self.assertFalse(observation["size_match"])
        self.assertAlmostEqual(observation["return_scale"]["width"], 1024 / 1536, places=6)
        self.assertAlmostEqual(observation["return_scale"]["height"], 768 / 1536, places=6)

        manifest = json.loads(job_path.read_text())
        self.assertTrue(manifest["patch_observation"]["enabled"])
        self.assertEqual(len(manifest["patch_observations"]), 1)
        self.assertEqual(manifest["patch_observation_summary"]["count"], 1)
        self.assertEqual(manifest["patch_observation_summary"]["size_match_count"], 0)
        self.assertEqual(manifest["patch_observation_summary"]["size_mismatch_count"], 1)
        self.assertEqual(manifest["patch_observation_summary"]["actual_sizes"], ["1024x768"])
        self.assertEqual(manifest["patch_observation_summary"]["requested_sizes"], ["1536x1536"])

    def test_patch_observation_rejects_jobs_with_local_recovery_disabled(self):
        result = self.run_script(
            "init_job.py", self.source, "--output-root", self.root / "disabled-observation-jobs",
            "--preset", "natural-cinematic",
            "--creative-recipe", "s001-abstract-quartet",
            "--creative-assembly-mode", "original-assembly",
            "--detail-budget", "balanced", "--confirmed",
        )
        job_dir = Path(result.stdout.strip())
        job_path = job_dir / "job.json"
        patch = job_dir / "intermediates" / "patch.png"
        Image.new("RGB", (1024, 1024), (90, 80, 70)).save(patch)
        rejected = self.run_script(
            "record_patch_observation.py", job_path,
            "--patch", patch,
            "--region-type", "generic",
            "--requested-size", "1024x1024",
            ok=False,
        )
        self.assertIn("local detail recovery disabled", rejected.stderr)

    def test_single_source_direct_effect_creative_enables_adaptive_hd_recovery(self):
        result = self.run_script(
            "init_job.py", self.source, "--output-root", self.root / "creative-jobs",
            "--preset", "natural-cinematic",
            "--creative-recipe", "s001-abstract-quartet",
            "--creative-assembly-mode", "direct-effect",
            "--detail-budget", "balanced", "--confirmed",
        )
        manifest = json.loads((Path(result.stdout.strip()) / "job.json").read_text())
        self.assertEqual(manifest["release_version"], "2.4")
        self.assertEqual(manifest["execution_mode"], "creative-translation")
        self.assertEqual(manifest["detail"]["mode"], "creative-safe-adaptive")
        self.assertEqual(manifest["detail"]["planner"], "adaptive-value-merge-v2.4-creative-safe")
        self.assertEqual(manifest["detail"]["patch_scope"], "adaptive-subject")
        self.assertEqual(manifest["detail"]["hard_generated_patch_ceiling"], 5)
        self.assertEqual(manifest["detail"]["look_authority"], "CREATIVE_LOOK_MASTER")
        self.assertEqual(manifest["detail"]["identity_authority"], "SOURCE_MASTER")
        self.assertEqual(manifest["authority_model"]["creative_look_master"][0], "approved_creative_canvas")

    def test_original_assembly_keeps_local_recovery_disabled(self):
        result = self.run_script(
            "init_job.py", self.source, "--output-root", self.root / "assembly-jobs",
            "--preset", "natural-cinematic",
            "--creative-recipe", "s001-abstract-quartet",
            "--creative-assembly-mode", "original-assembly",
            "--detail-budget", "balanced", "--confirmed",
        )
        manifest = json.loads((Path(result.stdout.strip()) / "job.json").read_text())
        self.assertEqual(manifest["detail"]["mode"], "not-applicable")
        self.assertEqual(manifest["detail"]["max_generated_patches"], 0)

    def test_creative_safe_full_body_splits_upper_and_lower_costume_with_capped_budget(self):
        plan = build_plan(
            1500, 2000,
            subject_type="classical-portrait", detail_budget="balanced",
            subject_box=Box(330, 120, 840, 1760), face_box=Box(620, 230, 210, 250),
            hand_boxes=[Box(430, 900, 160, 220), Box(850, 900, 160, 220)],
            prop_boxes=[],
            recovery_profile="creative-safe",
            portrait_extent="full",
            detail_complexity="normal",
        )
        self.assertEqual(plan["recovery_profile"], "creative-safe")
        self.assertEqual(plan["portrait_extent"], "full")
        self.assertEqual(plan["soft_generated_patch_budget"], 3)
        self.assertEqual(plan["hard_generated_patch_ceiling"], 4)
        self.assertEqual(plan["estimated_generated_patches"], 4)
        self.assertEqual(plan["planner"], "adaptive-value-merge-v2.4-creative-safe")
        roles = {item["region_role"] for item in plan["regions"]}
        self.assertIn("upper-costume", roles)
        self.assertIn("lower-costume", roles)
        self.assertIn("head", roles)
        self.assertIn("face", roles)

    def test_creative_safe_complex_full_body_caps_at_five(self):
        plan = build_plan(
            1500, 2000,
            subject_type="portrait", detail_budget="balanced",
            subject_box=Box(300, 100, 900, 1800), face_box=Box(620, 220, 200, 240),
            hand_boxes=[Box(390, 920, 180, 240), Box(900, 920, 180, 240)],
            prop_boxes=[Box(1000, 500, 300, 1100)],
            recovery_profile="creative-safe",
            portrait_extent="full",
            detail_complexity="complex",
        )
        self.assertEqual(plan["portrait_extent"], "complex-full")
        self.assertEqual(plan["soft_generated_patch_budget"], 4)
        self.assertEqual(plan["hard_generated_patch_ceiling"], 5)
        self.assertLessEqual(plan["estimated_generated_patches"], 5)

    def test_balanced_planner_prefers_three_coarse_patches_for_large_portrait(self):
        plan = build_plan(
            1500, 2000,
            subject_type="portrait", detail_budget="balanced",
            subject_box=Box(400, 350, 700, 1300), face_box=Box(600, 500, 250, 350),
            hand_boxes=[], prop_boxes=[],
        )
        self.assertEqual(plan["planner"], "adaptive-value-merge-v2.2")
        self.assertEqual(plan["soft_generated_patch_budget"], 3)
        self.assertEqual(plan["hard_generated_patch_ceiling"], 6)
        self.assertEqual(plan["max_generated_patches"], 6)
        self.assertEqual(plan["estimated_generated_patches"], 3)
        self.assertEqual([item["region_type"] for item in plan["regions"]], ["costume", "head", "face"])
        self.assertTrue(all(item["requires_pixel_budget_check"] for item in plan["regions"]))

    def test_vision_analysis_handoff_converts_normalized_regions(self):
        analysis = self.root / "vision-analysis.json"
        analysis.write_text(json.dumps({
            "schema_version": 1,
            "coordinate_space": "normalized",
            "subject_type": "classical-portrait",
            "regions": {
                "subject": {"x": 0.2, "y": 0.1, "width": 0.6, "height": 0.8},
                "face": {"x": 0.4, "y": 0.15, "width": 0.2, "height": 0.18},
                "hands": [{"x": 0.3, "y": 0.7, "width": 0.1, "height": 0.12}],
                "props": [{"x": 0.6, "y": 0.45, "width": 0.15, "height": 0.2}],
            },
        }), encoding="utf-8")
        resolved = load_vision_analysis(analysis, 1500, 2000)
        self.assertEqual(resolved["subject_type"], "classical-portrait")
        self.assertEqual(resolved["subject_box"], Box(300, 200, 900, 1600))
        self.assertEqual(resolved["face_box"], Box(600, 300, 300, 360))
        self.assertEqual(resolved["hand_boxes"], [Box(450, 1400, 150, 240)])
        self.assertEqual(resolved["prop_boxes"], [Box(900, 900, 225, 400)])

    def test_vision_analysis_cli_feeds_planner_and_records_source(self):
        analysis = self.root / "vision-analysis.json"
        analysis.write_text(json.dumps({
            "schema_version": 1,
            "coordinate_space": "pixel",
            "subject_type": "landscape",
            "regions": {"subject": {"x": 200, "y": 300, "width": 900, "height": 700}},
        }), encoding="utf-8")
        result = self.run_script(
            "plan_detail_tiles.py", "--image", self.source,
            "--vision-analysis", analysis,
        )
        plan = json.loads(result.stdout)
        self.assertEqual(plan["subject_type"], "landscape")
        self.assertEqual(plan["regions"][0]["region_type"], "generic")
        self.assertEqual(plan["vision_analysis"]["schema_version"], 1)

    def test_vision_analysis_rejects_unknown_schema(self):
        analysis = self.root / "bad-vision-analysis.json"
        analysis.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_vision_analysis(analysis, 1500, 2000)

    def test_balanced_budget_is_ceiling_not_quota_for_tiny_face(self):
        plan = build_plan(
            1500, 2000,
            subject_type="portrait", detail_budget="balanced",
            subject_box=Box(500, 500, 400, 900), face_box=Box(650, 550, 70, 90),
            hand_boxes=[], prop_boxes=[],
        )
        self.assertEqual(plan["soft_generated_patch_budget"], 3)
        self.assertEqual(plan["hard_generated_patch_ceiling"], 6)
        self.assertEqual(plan["max_generated_patches"], 6)
        self.assertEqual(plan["estimated_generated_patches"], 1)
        self.assertEqual([item["region_type"] for item in plan["regions"]], ["costume"])
        skipped_types = {item["region_type"] for item in plan["skipped_candidates"]}
        self.assertIn("face", skipped_types)
        self.assertIn("head", skipped_types)

    def test_balanced_complex_portrait_can_overflow_soft_budget_without_exceeding_hard_ceiling(self):
        plan = build_plan(
            1500, 2000,
            subject_type="classical-portrait", detail_budget="balanced",
            subject_box=Box(330, 260, 840, 1500), face_box=Box(590, 410, 310, 410),
            hand_boxes=[Box(420, 1260, 230, 300), Box(780, 1240, 230, 300)],
            prop_boxes=[Box(500, 1050, 430, 500)],
        )
        self.assertEqual(plan["soft_generated_patch_budget"], 3)
        self.assertEqual(plan["hard_generated_patch_ceiling"], 6)
        self.assertGreater(plan["estimated_generated_patches"], 3)
        self.assertLessEqual(plan["estimated_generated_patches"], 6)
        self.assertTrue(plan["adaptive_overflow_used"])
        self.assertGreater(plan["overflow_generated_patches"], 0)
        region_types = [item["region_type"] for item in plan["regions"]]
        self.assertTrue({"costume", "head", "face"}.issubset(set(region_types)))
        self.assertGreater(sum(item in {"hand", "prop"} for item in region_types), 0)
        self.assertEqual(region_types[-1], "face")

    def test_balanced_small_auxiliary_regions_do_not_trigger_overflow(self):
        plan = build_plan(
            1500, 2000,
            subject_type="portrait", detail_budget="balanced",
            subject_box=Box(400, 350, 700, 1300), face_box=Box(600, 500, 250, 350),
            hand_boxes=[Box(500, 1400, 80, 90), Box(850, 1420, 75, 85)],
            prop_boxes=[Box(650, 1300, 90, 100)],
        )
        self.assertEqual(plan["estimated_generated_patches"], 3)
        self.assertFalse(plan["adaptive_overflow_used"])
        self.assertEqual(plan["overflow_generated_patches"], 0)

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
