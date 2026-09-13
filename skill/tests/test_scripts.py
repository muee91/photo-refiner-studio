import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"


class ScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.jpg"
        Image.new("RGB", (120, 80), (40, 90, 140)).save(self.source, quality=95)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_script(self, name: str, *args: object, ok: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / name), *(str(item) for item in args)],
            capture_output=True,
            text=True,
        )
        if ok and result.returncode != 0:
            self.fail(f"{name} failed: {result.stdout}\n{result.stderr}")
        if not ok and result.returncode == 0:
            self.fail(f"{name} unexpectedly succeeded: {result.stdout}")
        return result

    def init_job(self, *extra: object) -> Path:
        result = self.run_script(
            "init_job.py",
            self.source,
            "--output-root",
            self.root / "jobs",
            "--preset",
            "eastern-twilight",
            "--confirmed",
            *extra,
        )
        return Path(result.stdout.strip())

    def test_prompt_resolution_and_manifest_snapshot(self) -> None:
        resolved = self.run_script("resolve_prompt.py", "--preset", "natural-landscape")
        prompt = json.loads(resolved.stdout)
        self.assertEqual(prompt["preset"], "natural-landscape")
        self.assertEqual(len(prompt["prompt_hash"]), 64)

        job = self.init_job()
        manifest = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "initialized")
        self.assertEqual(manifest["ui_mode"], "simple")
        self.assertTrue(manifest["confirmed_at"])
        self.assertEqual(len(manifest["source_records"][0]["sha256"]), 64)
        self.assertEqual(manifest["resolved_prompt"]["preset"], "eastern-twilight")
        self.assertTrue(manifest["resolved_prompt"]["prompt"])
        self.assertTrue(manifest["resolved_prompt"]["avoid"])
        self.assertEqual(manifest["delivery_mode"], "preview-first")
        self.assertTrue(manifest["base_preview"]["required"])
        self.assertFalse(manifest["base_preview"]["approved"])
        self.assertEqual(manifest["detail"]["patch_scope"], "head-and-face")
        self.assertTrue(manifest["detail"]["head_patch"])

    def test_confirmation_and_unknown_preset_are_rejected(self) -> None:
        self.run_script(
            "init_job.py",
            self.source,
            "--output-root",
            self.root / "jobs",
            "--preset",
            "eastern-twilight",
            ok=False,
        )
        result = self.run_script(
            "init_job.py",
            self.source,
            "--output-root",
            self.root / "jobs",
            "--preset",
            "typo-preset",
            "--confirmed",
            ok=False,
        )
        self.assertIn("Unknown preset", result.stderr + result.stdout)

    def test_directory_source_and_escaped_path_fail_with_actionable_errors(self) -> None:
        directory_result = self.run_script(
            "init_job.py",
            self.root,
            "--output-root",
            self.root / "jobs",
            "--preset",
            "eastern-twilight",
            "--confirmed",
            ok=False,
        )
        self.assertIn("directory, not a photograph", directory_result.stderr + directory_result.stdout)
        missing_result = self.run_script(
            "init_job.py",
            self.root / "missing\\_photo.jpg",
            "--output-root",
            self.root / "jobs2",
            "--preset",
            "eastern-twilight",
            "--confirmed",
            ok=False,
        )
        self.assertIn("Missing source files", missing_result.stderr + missing_result.stdout)

    def test_job_names_do_not_collide(self) -> None:
        first = self.init_job()
        second = self.init_job()
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir() and second.is_dir())

    def test_prepare_never_overwrites_source(self) -> None:
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.run_script("prepare_source.py", self.source, self.source, ok=False)
        after = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.run_script("prepare_source.py", self.source, self.root / "wrong.jpg", ok=False)
        self.run_script("prepare_source.py", self.source, self.root / "normalized.png")

    def test_crop_requires_positive_dimensions(self) -> None:
        self.run_script(
            "crop_tile.py",
            self.source,
            self.root / "tile.png",
            "--x",
            10,
            "--y",
            10,
            "--width",
            -5,
            "--height",
            20,
            ok=False,
        )

    def test_face_safe_crop_expands_below_the_proposed_face_box(self) -> None:
        result = self.run_script(
            "crop_tile.py",
            self.source,
            self.root / "face.png",
            "--x",
            30,
            "--y",
            20,
            "--width",
            40,
            "--height",
            30,
            "--face-safe",
        )
        report = json.loads(result.stdout)
        self.assertTrue(report["face_safe"])
        self.assertLess(report["crop"]["x"], 30)
        self.assertLess(report["crop"]["y"], 20)
        self.assertGreater(report["crop"]["height"], 30)
        self.assertGreater(report["crop"]["y"] + report["crop"]["height"], 50)

    def test_face_tight_crop_keeps_more_facial_occupancy_than_safe_crop(self) -> None:
        safe = json.loads(self.run_script(
            "crop_tile.py", self.source, self.root / "safe.png", "--x", 30, "--y", 20,
            "--width", 40, "--height", 30, "--face-safe",
        ).stdout)
        tight = json.loads(self.run_script(
            "crop_tile.py", self.source, self.root / "tight.png", "--x", 30, "--y", 20,
            "--width", 40, "--height", 30, "--face-safe", "--face-tight",
        ).stdout)
        self.assertTrue(tight["face_tight"])
        self.assertLessEqual(tight["size"][0], safe["size"][0])
        self.assertLessEqual(tight["size"][1], safe["size"][1])

    def test_resize_rejects_implicit_distortion(self) -> None:
        self.run_script(
            "resize_output.py",
            self.source,
            self.root / "square.png",
            "--size",
            "100x100",
            ok=False,
        )
        self.run_script(
            "resize_output.py",
            self.source,
            self.root / "contained.png",
            "--size",
            "100x100",
            "--fit",
            "contain",
        )
        with Image.open(self.root / "contained.png") as image:
            self.assertEqual(image.size, (100, 100))

    def test_job_state_transitions_and_artifacts(self) -> None:
        job = self.init_job()
        artifact = job / "intermediates" / "normalized.png"
        Image.new("RGB", (8, 8), "white").save(artifact)
        self.run_script(
            "update_job.py",
            job / "job.json",
            "--status",
            "prepared",
            "--artifact",
            f"normalized={artifact}",
        )
        manifest = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "prepared")
        self.assertEqual(manifest["artifacts"][0]["kind"], "normalized")
        self.assertEqual(len(manifest["artifacts"][0]["sha256"]), 64)
        self.run_script("update_job.py", job / "job.json", "--status", "completed", ok=False)

    def test_edit_brief_includes_confirmed_retouch_controls(self) -> None:
        job = self.init_job()
        manifest_path = job / "job.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["retouch"] = {
            "style_strength": 80,
            "global": {"contrast": 12},
            "portrait": {"enabled": False},
            "body": {"enabled": False},
            "clothing": {"wrinkleReduction": 30, "preserveTexture": 90},
            "background": {"skyEnhance": 20},
            "detail_strength": 60,
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.run_script("build_edit_prompt.py", manifest_path)
        brief = json.loads(result.stdout)
        self.assertTrue(any("clothing wrinkles" in item for item in brief["requested_adjustments"]))
        self.assertTrue(any("existing sky" in item for item in brief["requested_adjustments"]))
        self.assertEqual(brief["style_strength"], 80)
        self.assertIn("unmistakably visible", brief["style_execution_intent"])
        self.assertIn("near-identical conservative retouch", brief["base_prompt"])
        self.assertEqual(len(brief["edit_brief_hash"]), 64)
        self.assertEqual(brief["delivery_mode"], "preview-first")

    def test_face_detail_brief_requires_complete_jaw_and_chin_context(self) -> None:
        job = self.init_job("--detail-mode", "face")
        manifest_path = job / "job.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["retouch"] = {"detail_strength": 60}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        brief = json.loads(self.run_script("build_edit_prompt.py", manifest_path).stdout)
        self.assertTrue(any("jawline, chin" in item for item in brief["requested_adjustments"]))

    def test_default_detail_plan_separates_head_and_face_patches(self) -> None:
        job = self.init_job("--detail-mode", "face")
        manifest_path = job / "job.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["retouch"] = {"detail_strength": 60}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        brief = json.loads(self.run_script("build_edit_prompt.py", manifest_path).stdout)
        self.assertTrue(any("person-priority detail plan" in item for item in brief["requested_adjustments"]))
        self.assertTrue(any("costume-and-body-structure" in item for item in brief["requested_adjustments"]))

    def test_preview_first_requires_base_approval_but_one_click_does_not(self) -> None:
        preview_job = self.init_job()
        self.run_script("update_job.py", preview_job / "job.json", "--status", "prepared")
        self.run_script("update_job.py", preview_job / "job.json", "--status", "base_generated")
        self.run_script("update_job.py", preview_job / "job.json", "--status", "completed", ok=False)
        self.run_script("update_job.py", preview_job / "job.json", "--approve-base-preview")
        self.run_script("update_job.py", preview_job / "job.json", "--status", "completed")

        one_click_job = self.init_job()
        manifest_path = one_click_job / "job.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["delivery_mode"] = "one-click"
        manifest["base_preview"] = {"required": False, "approved": False}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.run_script("update_job.py", manifest_path, "--status", "prepared")
        self.run_script("update_job.py", manifest_path, "--status", "base_generated")
        self.run_script("update_job.py", manifest_path, "--status", "completed")

    def test_batch_requires_master_approval(self) -> None:
        second_source = self.root / "source-2.jpg"
        Image.new("RGB", (120, 80), (80, 100, 120)).save(second_source, quality=95)
        result = self.run_script(
            "init_job.py",
            self.source,
            second_source,
            "--output-root",
            self.root / "jobs",
            "--preset",
            "natural-landscape",
            "--confirmed",
        )
        job = Path(result.stdout.strip())
        self.run_script("update_job.py", job / "job.json", "--status", "prepared")
        self.run_script("update_job.py", job / "job.json", "--status", "base_generated")
        self.run_script("update_job.py", job / "job.json", "--status", "completed", ok=False)
        master = job / "outputs" / "master.png"
        Image.new("RGB", (12, 8), "white").save(master)
        self.run_script(
            "update_job.py",
            job / "job.json",
            "--approve-master",
            "--master-frame",
            master,
        )
        self.run_script("update_job.py", job / "job.json", "--status", "completed")

    def test_registration_checks_target_and_coverage(self) -> None:
        rng = np.random.default_rng(7)
        base = rng.integers(0, 256, (320, 320, 3), dtype=np.uint8)
        target = base[60:260, 70:270].copy()
        base_path = self.root / "base.png"
        target_path = self.root / "target.png"
        patch_path = self.root / "patch.png"
        cv2.imwrite(str(base_path), base)
        cv2.imwrite(str(target_path), target)
        cv2.imwrite(str(patch_path), target)
        accepted = self.run_script(
            "register_blend.py",
            "--base",
            base_path,
            "--target",
            target_path,
            "--patch",
            patch_path,
            "--output",
            self.root / "blended.png",
            "--x",
            70,
            "--y",
            60,
        )
        report = json.loads(accepted.stdout)
        self.assertTrue(report["accepted"])
        self.assertGreaterEqual(report["coverage"], 0.90)

        wrong_target = target.copy()
        wrong_target[:100] = 0
        wrong_path = self.root / "wrong-target.png"
        cv2.imwrite(str(wrong_path), wrong_target)
        self.run_script(
            "register_blend.py",
            "--base",
            base_path,
            "--target",
            wrong_path,
            "--patch",
            patch_path,
            "--output",
            self.root / "wrong-blend.png",
            "--x",
            70,
            "--y",
            60,
            ok=False,
        )


if __name__ == "__main__":
    unittest.main()
