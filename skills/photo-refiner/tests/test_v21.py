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


class PhotoRefinerV21Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.jpg"
        Image.new("RGB", (120, 80), (130, 110, 90)).save(self.source, quality=95)

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, name, *args, ok=True):
        command = [sys.executable, str(SCRIPTS / name), *map(str, args)]
        result = subprocess.run(command, capture_output=True, text=True)
        if ok and result.returncode != 0:
            self.fail(f"{command} failed: {result.stderr}\n{result.stdout}")
        if not ok and result.returncode == 0:
            self.fail(f"{command} unexpectedly succeeded")
        return result

    def init_job(self):
        result = self.run_script(
            "init_job.py", self.source, "--output-root", self.root / "jobs",
            "--preset", "natural-landscape", "--confirmed",
        )
        return Path(result.stdout.strip())

    def test_preset_strength_authority_and_srgb_manifest(self):
        resolved = json.loads(self.run_script("resolve_prompt.py", "--preset", "natural-landscape").stdout)
        self.assertEqual(resolved["preset_version"], 2)
        self.assertEqual(resolved["default_strength"], 35)
        manifest = json.loads((self.init_job() / "job.json").read_text())
        self.assertEqual(manifest["version"], 2)
        self.assertEqual(manifest["working_color_space"], "sRGB")
        self.assertIn("look_master", manifest["authority_model"])
        self.assertEqual(manifest["retouch"]["style_strength"], 35)
        self.assertEqual(manifest["detail"]["pixel_budget_thresholds"]["face"], 0.85)
        self.assertEqual(manifest["quality_gate"]["registration_model_by_region"]["face"], "similarity")

    def test_prepare_source_embeds_srgb_profile(self):
        output = self.root / "normalized.png"
        self.run_script("prepare_source.py", self.source, output)
        with Image.open(output) as image:
            self.assertTrue(image.info.get("icc_profile"))
            self.assertEqual(image.mode, "RGB")

    def test_style_strength_becomes_semantic_generation_instruction(self):
        job = self.init_job()
        manifest_path = job / "job.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["retouch"]["style_strength"] = 80
        manifest_path.write_text(json.dumps(manifest))
        brief = json.loads(self.run_script("build_edit_prompt.py", manifest_path).stdout)
        self.assertEqual(brief["style_execution_level"], "strong")
        self.assertIn("strong execution level", brief["requested_adjustments"][0])
        self.assertNotIn("80/100", brief["requested_adjustments"][0])
        self.assertTrue(any("LOOK MASTER" in item for item in brief["requested_adjustments"]))

    def test_pixel_budget_accepts_real_detail_and_rejects_fake_upscale(self):
        accepted = json.loads(self.run_script(
            "pixel_budget.py", "--patch-size", "1536x1536",
            "--working-canvas", "1000x1000", "--delivery-canvas", "1714x1714",
            "--region-crop", "0,0,1000,1000", "--region-subject", "150,150,700,700",
            "--region-type", "face",
        ).stdout)
        self.assertTrue(accepted["accepted"])
        rejected = json.loads(self.run_script(
            "pixel_budget.py", "--patch-size", "1536x1536",
            "--working-canvas", "1000x1000", "--delivery-canvas", "2000x2000",
            "--region-crop", "0,0,1000,1000", "--region-subject", "325,325,350,350",
            "--region-type", "face",
            ok=False,
        ).stdout)
        self.assertFalse(rejected["accepted"])
        self.assertEqual(rejected["recommended_action"], "tighten_crop")

    def test_pixel_budget_cannot_be_fooled_by_working_canvas_numbers(self):
        # A patch that only fills its working-canvas region must not read as
        # sufficient once the delivery canvas is several times larger.
        result = json.loads(self.run_script(
            "pixel_budget.py", "--patch-size", "1254x1254",
            "--working-canvas", "1024x1536", "--delivery-canvas", "1024x1536",
            "--region-crop", "472,382,245,370", "--region-subject", "492,415,205,276",
            "--region-type", "face",
        ).stdout)
        self.assertTrue(result["accepted"])
        delivered = json.loads(self.run_script(
            "pixel_budget.py", "--patch-size", "1254x1254",
            "--working-canvas", "1024x1536", "--delivery-canvas", "4672x7008",
            "--region-crop", "472,382,245,370", "--region-subject", "492,415,205,276",
            "--region-type", "face",
            ok=False,
        ).stdout)
        self.assertFalse(delivered["accepted"])

    def test_face_registration_uses_similarity_and_frequency_fusion(self):
        rng = np.random.default_rng(17)
        base = rng.integers(0, 256, (320, 320, 3), dtype=np.uint8)
        target = base[60:260, 70:270].copy()
        base_path, target_path, patch_path = self.root / "base.png", self.root / "target.png", self.root / "patch.png"
        cv2.imwrite(str(base_path), base)
        cv2.imwrite(str(target_path), target)
        cv2.imwrite(str(patch_path), target)
        report = json.loads(self.run_script(
            "register_blend.py", "--base", base_path, "--target", target_path, "--patch", patch_path,
            "--output", self.root / "out.png", "--x", 70, "--y", 60, "--region-type", "face",
        ).stdout)
        self.assertTrue(report["accepted"])
        self.assertEqual(report["registration_model"], "similarity")
        self.assertEqual(report["fusion_mode"], "look-master-low-frequency-plus-patch-detail")


if __name__ == "__main__":
    unittest.main()
