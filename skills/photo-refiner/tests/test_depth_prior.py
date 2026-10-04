import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import apply_depth_prior


class DepthPriorTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "working_canvas": [1000, 1500],
            "delivery_canvas": [1000, 1500],
            "region_count": 2,
            "estimated_generated_patches": 2,
            "soft_generated_patch_budget": 3,
            "hard_generated_patch_ceiling": 6,
            "regions": [
                {
                    "region_type": "costume",
                    "region_role": "costume",
                    "crop": {"x": 180, "y": 280, "width": 640, "height": 980},
                    "subject_box": {"x": 220, "y": 300, "width": 560, "height": 900},
                },
                {
                    "region_type": "hand",
                    "region_role": "hand",
                    "crop": {"x": 250, "y": 720, "width": 240, "height": 260},
                    "subject_box": {"x": 285, "y": 755, "width": 170, "height": 190},
                },
            ],
        }

    def vision(self, **depth_overrides):
        depth = {
            "source": "vision-relative",
            "confidence": 0.86,
            "subject_depth_uniformity": 0.70,
            "occlusion_risk": "high",
            "background_separation": "strong",
            "intents": ["occlusion"],
            "discontinuities": [
                {
                    "label": "foreground-railing",
                    "relation": "foreground-over-subject",
                    "strength": 0.92,
                    "box": {"x": 0.18, "y": 0.55, "width": 0.62, "height": 0.10},
                }
            ],
        }
        depth.update(depth_overrides)
        return {
            "schema_version": 1,
            "coordinate_space": "normalized",
            "subject_type": "portrait",
            "regions": {},
            "depth_prior": depth,
        }

    def test_depth_prior_never_changes_generation_count_or_regions(self):
        result = apply_depth_prior.annotate_plan(self.plan, self.vision())
        self.assertEqual(result["region_count"], self.plan["region_count"])
        self.assertEqual(result["estimated_generated_patches"], self.plan["estimated_generated_patches"])
        self.assertEqual(result["soft_generated_patch_budget"], self.plan["soft_generated_patch_budget"])
        self.assertEqual(result["hard_generated_patch_ceiling"], self.plan["hard_generated_patch_ceiling"])
        self.assertEqual(len(result["regions"]), len(self.plan["regions"]))
        self.assertEqual(result["depth_prior"]["generation_count_delta"], 0)

    def test_intersecting_occlusion_marks_region_depth_sensitive(self):
        result = apply_depth_prior.annotate_plan(self.plan, self.vision())
        costume = result["regions"][0]["depth_guard"]
        hand = result["regions"][1]["depth_guard"]
        self.assertTrue(costume["occlusion_sensitive"])
        self.assertEqual(costume["merge_policy"], "do-not-merge-across-depth-boundary")
        self.assertTrue(any(item["label"] == "foreground-railing" for item in costume["discontinuities"]))
        self.assertTrue(hand["occlusion_sensitive"])
        self.assertIn("preserve visible foreground/background ordering from SOURCE MASTER", hand["prompt_constraints"])

    def test_low_risk_uniform_subject_exposes_only_a_merge_hint(self):
        result = apply_depth_prior.annotate_plan(
            self.plan,
            self.vision(
                confidence=0.90,
                subject_depth_uniformity=0.90,
                occlusion_risk="low",
                discontinuities=[],
            ),
        )
        for region in result["regions"]:
            self.assertEqual(region["depth_guard"]["merge_policy"], "broad-merge-safe")
            self.assertFalse(region["depth_guard"]["occlusion_sensitive"])

    def test_low_confidence_prior_is_ignored_without_mutating_regions(self):
        result = apply_depth_prior.annotate_plan(self.plan, self.vision(confidence=0.30))
        self.assertFalse(result["depth_prior"]["active"])
        self.assertEqual(result["depth_prior"]["ignored_reason"], "confidence_below_0.55")
        self.assertNotIn("depth_guard", result["regions"][0])

    def test_absent_depth_prior_is_valid_and_noop(self):
        result = apply_depth_prior.annotate_plan(self.plan, {
            "schema_version": 1,
            "coordinate_space": "pixel",
            "subject_type": "portrait",
            "regions": {},
        })
        self.assertFalse(result["depth_prior"]["present"])
        self.assertEqual(result["regions"], self.plan["regions"])

    def test_invalid_depth_confidence_is_rejected(self):
        with self.assertRaises(ValueError):
            apply_depth_prior.annotate_plan(self.plan, self.vision(confidence=1.5))

    def test_cli_writes_annotated_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "plan.json"
            vision = root / "vision.json"
            output = root / "depth-plan.json"
            plan.write_text(json.dumps(self.plan), encoding="utf-8")
            vision.write_text(json.dumps(self.vision()), encoding="utf-8")
            import subprocess
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "apply_depth_prior.py"),
                    "--plan", str(plan),
                    "--vision-analysis", str(vision),
                    "--output", str(output),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(saved["depth_prior"]["active"])
            self.assertEqual(saved["depth_prior"]["generation_count_delta"], 0)


if __name__ == "__main__":
    unittest.main()
