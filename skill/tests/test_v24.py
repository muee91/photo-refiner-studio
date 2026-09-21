"""v2.4 delivery contract: the working canvas and the delivery canvas are different
spaces, and every budget/upscale decision must be measured in the delivery space.

Regression origin: real job DSC02304 delivered a 1024x1536 composite stretched to
4672x7008 while the Pixel Budget gate reported "accept" for every patch.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"

# Measured in the failing job: source 4672x7008, approved creative preview 1024x1536,
# face crop 245x370 with a 205x276 subject box, patch returned 1254x1254.
REAL_WORKING_CANVAS = (1024, 1536)
REAL_DELIVERY_CANVAS = (4672, 7008)
REAL_FACE_CROP = "472,382,245,370"
REAL_FACE_SUBJECT = "492,415,205,276"
REAL_PATCH = (1254, 1254)


def panel_config(**overrides):
    """A settings-panel shaped config, mirroring plugin/mcp/server.cjs DEFAULTS."""
    config = {
        "sourceCount": 1,
        "uiMode": "simple",
        "workflow": "auto",
        "creativeRecipe": "none",
        "creativeAssemblyMode": "direct-effect",
        "creativeFromBase": False,
        "creativeHdChain": False,
        "creativeUpscale": True,
        "preset": "warm-gold-ancient",
        "customPrompt": "",
        "customAvoid": "",
        "promptFavorite": False,
        "aspectRatio": "original",
        "framing": "preserve",
        "resolution": "source-width",
        "deliveryMode": "preview-first",
        "outputFormat": "jpg",
        "keepIntermediates": False,
        "styleStrength": 68,
        "global": {
            "exposure": 0, "contrast": 0, "highlights": 0, "shadows": 0, "temperature": 0,
            "tint": 0, "saturation": 0, "vibrance": 0, "clarity": 0, "dehaze": 0,
            "denoise": 15, "sharpen": 15, "grain": 10,
        },
        "portrait": {"enabled": False},
        "body": {"enabled": False},
        "clothing": {"wrinkleReduction": 0, "preserveTexture": 90},
        "background": {"cleanup": 0},
        "detail": {
            "mode": "adaptive",
            "strength": 60,
            "regions": "",
            "patchScope": "head-and-face",
            "headPatch": True,
            "generationBudget": "balanced",
        },
        "batch": {"consistency": "balanced"},
    }
    config.update(overrides)
    return config


def canonical_hash(value) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def write_confirmation(home: Path, config: dict) -> Path:
    resolved_prompt = {
        "preset": config["preset"],
        "label": "Warm Gold Ancient",
        "summary": "test",
        "prompt": "muted amber sunset and lantern light",
        "avoid": "orange skin",
        "defaultStrength": config["styleStrength"],
        "presetVersion": 2,
    }
    record = {
        "schemaVersion": 4,
        "confirmationId": "cid-v24",
        "confirmedAt": "2026-09-21T00:00:00.000Z",
        "confirmedBy": "photo-refiner-studio",
        "config": config,
        "executionMode": "photo-refinement",
        "resolvedCreativeRecipe": None,
        "creativeOutput": None,
        "resolvedPrompt": resolved_prompt,
        "promptHash": hashlib.sha256(
            json.dumps(resolved_prompt, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    record["confirmationHash"] = canonical_hash({
        "config": record["config"],
        "executionMode": record["executionMode"],
        "resolvedCreativeRecipe": record["resolvedCreativeRecipe"],
        "creativeOutput": record["creativeOutput"],
        "resolvedPrompt": record["resolvedPrompt"],
    })
    directory = home / ".codex" / "photo-refiner" / "confirmed"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "cid-v24.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


class ConfirmationFieldValidationTests(unittest.TestCase):
    """The confirmation file is treated as authoritative by SKILL.md, so every field it
    supplies must pass the same validators the command line enforces."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.work = Path(self._tmp.name) / "work"
        self.work.mkdir(parents=True)
        self.source = self.work / "src.jpg"
        Image.new("RGB", (4672, 7008), (90, 120, 150)).save(self.source)
        self.env = {**os.environ, "HOME": str(self.home)}

    def tearDown(self):
        self._tmp.cleanup()

    def init_with(self, config):
        confirmation = write_confirmation(self.home, config)
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "init_job.py"), str(self.source),
             "--confirmation-file", str(confirmation)],
            capture_output=True, text=True, env=self.env,
        )

    def assert_rejects(self, config, field_label):
        result = self.init_with(config)
        self.assertNotEqual(result.returncode, 0, f"{field_label} should not be accepted")
        combined = result.stdout + result.stderr
        self.assertNotIn("Traceback", combined, f"{field_label} must fail cleanly, not crash")
        self.assertIn(field_label, combined, f"{field_label} should be named in the error")

    def test_rejects_output_format_outside_the_supported_set(self):
        config = panel_config(outputFormat="webp")
        self.assert_rejects(config, "output_format")

    def test_rejects_unknown_detail_mode(self):
        config = panel_config()
        config["detail"]["mode"] = "teleport"
        self.assert_rejects(config, "detail.mode")

    def test_rejects_unknown_batch_consistency(self):
        config = panel_config()
        config["batch"]["consistency"] = "loose"
        self.assert_rejects(config, "batch.consistency")

    def test_rejects_unknown_generation_budget_without_traceback(self):
        config = panel_config()
        config["detail"]["generationBudget"] = "ultra"
        self.assert_rejects(config, "generationBudget")

    def test_accepts_a_wellformed_panel_confirmation(self):
        result = self.init_with(panel_config())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        job_path = Path(result.stdout.strip().splitlines()[-1]).joinpath("job.json")
        job = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(job["output_format"], "jpg")
        self.assertEqual(job["detail"]["generation_budget"], "balanced")
        self.assertEqual(job["hd_working_canvas_policy"]["mode"], "automatic")
        self.assertEqual(job["hd_working_canvas_policy"]["model_native_information_scale"], 4)
        self.assertEqual(job["upscale_passes"], [])

    def test_one_click_cannot_treat_an_unbound_master_as_native(self):
        config = panel_config(deliveryMode="one-click")
        config["detail"]["mode"] = "base-only"
        result = self.init_with(config)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        job_dir = Path(result.stdout.strip().splitlines()[-1])
        job_path = job_dir / "job.json"
        master = job_dir / "master.png"
        Image.new("RGB", REAL_WORKING_CANVAS, (90, 120, 150)).save(master)
        gate = subprocess.run(
            [sys.executable, str(SCRIPTS / "delivery_gate.py"), str(job_path),
             "--master", str(master), "--final", str(master)],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(gate.returncode, 3, gate.stdout + gate.stderr)
        report = json.loads(gate.stdout)
        self.assertFalse(report["geometry"]["reference_evidence_ok"])
        self.assertIn("prepare_hd_working_canvas", report["required_action"])

    def test_one_click_native_route_binds_original_generated_bitmap(self):
        config = panel_config(deliveryMode="one-click", resolution="1024x1536")
        config["detail"]["mode"] = "base-only"
        result = self.init_with(config)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        job_dir = Path(result.stdout.strip().splitlines()[-1])
        job_path = job_dir / "job.json"
        generated = job_dir / "intermediates" / "generated-base.png"
        Image.new("RGB", REAL_WORKING_CANVAS, (90, 120, 150)).save(generated)
        prepared = job_dir / "intermediates" / "hd-working.png"
        prep = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_hd_working_canvas.py"), str(job_path),
             "--input", str(generated), "--output", str(prepared)],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(prep.returncode, 0, prep.stdout + prep.stderr)
        prep_report = json.loads(prep.stdout)
        self.assertEqual(prep_report["route"], "native-detail")
        gate = subprocess.run(
            [sys.executable, str(SCRIPTS / "delivery_gate.py"), str(job_path),
             "--master", str(prepared), "--final", str(prepared)],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
        report = json.loads(gate.stdout)
        self.assertEqual(report["geometry"]["reference_source"], "hd_working_canvas_input")
        self.assertTrue(report["geometry"]["reference_evidence_ok"])

    def test_accepts_pro_ui_mode_from_studio(self):
        result = self.init_with(panel_config(uiMode="pro"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        job = json.loads(Path(result.stdout.strip().splitlines()[-1]).joinpath("job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["ui_mode"], "pro")

    def test_confirmation_hash_rejects_config_tampering(self):
        confirmation = write_confirmation(self.home, panel_config())
        record = json.loads(confirmation.read_text(encoding="utf-8"))
        record["config"]["creativeUpscale"] = False
        confirmation.write_text(json.dumps(record, indent=2), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "init_job.py"), str(self.source),
             "--confirmation-file", str(confirmation)],
            capture_output=True, text=True, env=self.env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("settings hash mismatch", result.stdout + result.stderr)

    def test_confirmation_schema_downgrade_is_rejected(self):
        confirmation = write_confirmation(self.home, panel_config())
        record = json.loads(confirmation.read_text(encoding="utf-8"))
        record["schemaVersion"] = 3
        record.pop("confirmationHash", None)
        confirmation.write_text(json.dumps(record, indent=2), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "init_job.py"), str(self.source),
             "--confirmation-file", str(confirmation)],
            capture_output=True, text=True, env=self.env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("confirmation schema", (result.stdout + result.stderr).lower())

    def test_panel_generation_budget_reaches_the_manifest(self):
        # fast/max were unreachable from Studio: the panel carried no such field.
        config = panel_config()
        config["detail"]["generationBudget"] = "max"
        result = self.init_with(config)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        job = json.loads(Path(result.stdout.strip().splitlines()[-1]).joinpath("job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["detail"]["generation_budget"], "max")
        self.assertEqual(job["detail"]["soft_generated_patch_budget"], 5)
        self.assertEqual(job["detail"]["hard_generated_patch_ceiling"], 8)


class BudgetTableSingleSourceTests(unittest.TestCase):
    """Soft/hard ceilings were stated three times and already disagreed: init_job wrote
    balanced creative-safe as soft 2 / hard 5 while the planner narrows a close portrait
    to 2 / 3, so job.json overstated what an agent may generate."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.master = tmp / "master.png"
        Image.new("RGB", (1024, 1536), (90, 120, 150)).save(self.master)
        self.analysis = tmp / "vision.json"
        self.analysis.write_text(json.dumps({
            "schema_version": 1,
            "coordinate_space": "pixel",
            "subject_type": "classical-portrait",
            "portrait_extent": "close",
            "detail_complexity": "normal",
            "regions": {
                "subject": {"x": 100, "y": 100, "width": 800, "height": 1300},
                "face": {"x": 472, "y": 382, "width": 245, "height": 370},
            },
        }), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, profile):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "plan_detail_tiles.py"), "--image", str(self.master),
             "--vision-analysis", str(self.analysis), "--detail-budget", "balanced",
             "--recovery-profile", profile],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_normal_budgets_match_between_planner_and_job_contract(self):
        sys.path.insert(0, str(SCRIPTS))
        try:
            import job_contract
        finally:
            sys.path.pop(0)
        for budget in ("fast", "balanced", "max"):
            self.assertEqual(
                (job_contract.BUDGET_POLICY[budget]["soft"], job_contract.BUDGET_POLICY[budget]["hard"]),
                job_contract.normal_budget(budget),
                f"normal {budget} budget must have one source",
            )

    def test_creative_safe_manifest_never_overstates_the_operative_ceiling(self):
        plan = self.plan("creative-safe")
        self.assertEqual((plan["soft_generated_patch_budget"], plan["hard_generated_patch_ceiling"]), (2, 3))
        ceiling = plan["hard_generated_patch_ceiling"]
        sys.path.insert(0, str(SCRIPTS))
        try:
            import job_contract
        finally:
            sys.path.pop(0)
        # The manifest must expose the stage table rather than a single permissive number.
        self.assertEqual(job_contract.creative_safe_budget("balanced", "close"), (2, 3))
        self.assertEqual(job_contract.creative_safe_budget("balanced", "complex-full"), (4, 5))
        self.assertLessEqual(ceiling, job_contract.creative_safe_ceiling("balanced"))

    def test_init_job_creative_manifest_uses_the_stage_table(self):
        sys.path.insert(0, str(SCRIPTS))
        try:
            import job_contract
        finally:
            sys.path.pop(0)
        source = self.master.with_suffix(".jpg")
        Image.new("RGB", (4672, 7008), (90, 120, 150)).save(source)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "init_job.py"), str(source),
             "--preset", "warm-gold-ancient", "--creative-recipe", "s015-diffuse-gradient",
             "--creative-assembly-mode", "direct-effect", "--confirmed"],
            capture_output=True, text=True, cwd=self._tmp.name,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        job = json.loads(Path(result.stdout.strip().splitlines()[-1]).joinpath("job.json").read_text(encoding="utf-8"))
        detail = job["detail"]
        self.assertEqual(detail["mode"], "creative-safe-adaptive")
        self.assertNotIn("hard_generated_patch_ceiling", detail,
                         "a flat creative ceiling invites over-generation; the stage table is authoritative")
        self.assertEqual(detail["portrait_budget_policy"]["close"], dict(zip(("soft", "hard"), job_contract.creative_safe_budget("balanced", "close"))))
        self.assertEqual(detail["portrait_budget_policy"]["complex-full"], dict(zip(("soft", "hard"), job_contract.creative_safe_budget("balanced", "complex-full"))))
        self.assertEqual(detail["absolute_generated_patch_ceiling"], job_contract.creative_safe_ceiling("balanced"))


class PixelBudgetCanvasSpaceTests(unittest.TestCase):
    def run_budget(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "pixel_budget.py"), *args],
            capture_output=True, text=True,
        )

    def test_working_canvas_numbers_cannot_be_mistaken_for_delivery_numbers(self):
        result = self.run_budget(
            "--patch-size", f"{REAL_PATCH[0]}x{REAL_PATCH[1]}",
            "--working-canvas", f"{REAL_WORKING_CANVAS[0]}x{REAL_WORKING_CANVAS[1]}",
            "--delivery-canvas", f"{REAL_DELIVERY_CANVAS[0]}x{REAL_DELIVERY_CANVAS[1]}",
            "--region-crop", REAL_FACE_CROP,
            "--region-subject", REAL_FACE_SUBJECT,
            "--region-type", "face",
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["accepted"])
        self.assertLess(report["detail_ratio"]["minimum"], report["threshold"])
        self.assertAlmostEqual(report["delivery_scale"], 4.5625, places=4)

    def test_same_numbers_at_scale_one_are_accepted(self):
        result = self.run_budget(
            "--patch-size", f"{REAL_PATCH[0]}x{REAL_PATCH[1]}",
            "--working-canvas", f"{REAL_WORKING_CANVAS[0]}x{REAL_WORKING_CANVAS[1]}",
            "--delivery-canvas", f"{REAL_WORKING_CANVAS[0]}x{REAL_WORKING_CANVAS[1]}",
            "--region-crop", REAL_FACE_CROP,
            "--region-subject", REAL_FACE_SUBJECT,
            "--region-type", "face",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["accepted"])

    def test_rejects_mismatched_canvas_aspect(self):
        result = self.run_budget(
            "--patch-size", "1254x1254",
            "--working-canvas", "1024x1536",
            "--delivery-canvas", "4672x4672",
            "--region-crop", REAL_FACE_CROP,
            "--region-subject", REAL_FACE_SUBJECT,
            "--region-type", "face",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("aspect", result.stdout + result.stderr)


class DeliveryGateTests(unittest.TestCase):
    """The delivered file may not be a larger copy of a smaller approved image.

    Regression origin: DSC02304 recorded "Final sRGB JPG delivered at source
    dimensions" for a 4672x7008 file that was a 1024x1536 composite stretched by
    resize_output.py, and reached status completed with no gate objecting.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = self.root / "source.jpg"
        Image.new("RGB", REAL_DELIVERY_CANVAS, (90, 120, 150)).save(self.source, quality=95)

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, script, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / script), *[str(a) for a in args]],
            capture_output=True, text=True,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def start_job(self):
        result = self.run_script(
            "init_job.py", self.source, "--preset", "warm-gold-ancient", "--confirmed",
            "--detail-mode", "base-only", "--output-root", self.root / "jobs",
        )
        return Path(result.stdout.strip().splitlines()[-1])

    def drive_to_details_processed(self, job_dir: Path, master_size):
        master = job_dir / "master.png"
        Image.new("RGB", master_size, (90, 120, 150)).save(master)
        self.run_script("update_job.py", job_dir / "job.json", "--status", "prepared")
        self.run_script("update_job.py", job_dir / "job.json", "--status", "base_generated")
        self.run_script("update_job.py", job_dir / "job.json", "--approve-base-preview",
                        "--artifact", f"base_preview={master}")
        self.run_script("update_job.py", job_dir / "job.json", "--status", "details_processed")
        return master

    def test_completed_is_refused_when_the_final_is_an_upscaled_master(self):
        job_dir = self.start_job()
        master = self.drive_to_details_processed(job_dir, REAL_WORKING_CANVAS)
        final = job_dir / "final.jpg"
        Image.open(master).resize(REAL_DELIVERY_CANVAS, Image.LANCZOS).save(final, quality=95)
        self.run_script(
            "update_job.py", job_dir / "job.json", "--artifact", f"final_jpg={final}",
        )
        gate = self.run_script(
            "delivery_gate.py", job_dir / "job.json", "--master", master, "--final", final,
            ok=False,
        )
        self.assertEqual(gate.returncode, 3, gate.stdout + gate.stderr)
        report = json.loads(gate.stdout)
        self.assertEqual(report["verdict"], "fail")
        self.assertAlmostEqual(report["delivery_scale"], 4.5625, places=4)
        self.assertIn("upscale_image.py", report["required_action"])

        refused = self.run_script(
            "update_job.py", job_dir / "job.json", "--status", "completed", ok=False,
        )
        combined = refused.stdout + refused.stderr
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("delivery gate", combined)
        self.assertEqual(json.loads((job_dir / "job.json").read_text())["status"], "details_processed")

    def test_completed_is_allowed_when_delivery_is_native_scale(self):
        job_dir = self.start_job()
        master = self.drive_to_details_processed(job_dir, REAL_DELIVERY_CANVAS)
        final = job_dir / "final.jpg"
        Image.open(master).save(final, quality=95)
        self.run_script("update_job.py", job_dir / "job.json", "--artifact", f"final_jpg={final}")
        gate = self.run_script("delivery_gate.py", job_dir / "job.json", "--master", master, "--final", final)
        self.assertEqual(json.loads(gate.stdout)["verdict"], "pass")
        self.run_script("update_job.py", job_dir / "job.json", "--status", "completed")
        self.assertEqual(json.loads((job_dir / "job.json").read_text())["status"], "completed")

    def test_recovery_enabled_delivery_refuses_missing_detail_plan(self):
        result = self.run_script(
            "init_job.py", self.source, "--preset", "warm-gold-ancient", "--confirmed",
            "--detail-mode", "adaptive", "--output-root", self.root / "detail-jobs",
        )
        job_dir = Path(result.stdout.strip().splitlines()[-1])
        master = self.drive_to_details_processed(job_dir, REAL_DELIVERY_CANVAS)
        final = job_dir / "final.jpg"
        Image.open(master).save(final, quality=95)
        gate = self.run_script(
            "delivery_gate.py", job_dir / "job.json", "--master", master, "--final", final,
            ok=False,
        )
        self.assertEqual(gate.returncode, 3, gate.stdout + gate.stderr)
        report = json.loads(gate.stdout)
        self.assertEqual(report["budget"]["reason"], "missing_detail_plan")
        self.assertIn("--plan", report["required_action"])

    def test_hd_master_delivery_requires_tile_plan_even_with_passing_detail_plan(self):
        job_dir = self.start_job()
        master = self.drive_to_details_processed(job_dir, REAL_DELIVERY_CANVAS)
        final = job_dir / "final.jpg"
        Image.open(master).save(final, quality=95)
        job_path = job_dir / "job.json"
        data = json.loads(job_path.read_text(encoding="utf-8"))
        data["detail"]["mode"] = "adaptive"
        data["creative_output"] = {"upstream_binding": "hd-master"}
        job_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        detail_plan = job_dir / "detail-plan.json"
        detail_plan.write_text(json.dumps({
            "region_count": 0,
            "regions_dropped_for_budget": [],
            "delivery_feasibility": {"verdict": "native"},
        }), encoding="utf-8")
        gate = self.run_script(
            "delivery_gate.py", job_path, "--master", master, "--final", final,
            "--plan", detail_plan, ok=False,
        )
        self.assertEqual(gate.returncode, 3, gate.stdout + gate.stderr)
        report = json.loads(gate.stdout)
        self.assertEqual(report["budget"]["reason"], "missing_tile_plan")
        self.assertIn("--tile-plan", report["required_action"])

    def test_hd_master_delivery_accepts_a_valid_tile_plan(self):
        job_dir = self.start_job()
        master = self.drive_to_details_processed(job_dir, REAL_DELIVERY_CANVAS)
        final = job_dir / "final.jpg"
        Image.open(master).save(final, quality=95)
        job_path = job_dir / "job.json"
        data = json.loads(job_path.read_text(encoding="utf-8"))
        data["detail"]["mode"] = "adaptive"
        data["creative_output"] = {"upstream_binding": "hd-master"}
        job_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tile_plan = job_dir / "tile-plan.json"
        tile_plan.write_text(json.dumps({
            "verdict": "pass",
            "canvas": list(REAL_DELIVERY_CANVAS),
            "observed_patch_size": [1254, 1254],
            "tile_count": 1,
            "blend_sequence": [0],
            "coverage": {"hole_area": 0, "sliver_area": 0},
            "tiles": [{
                "index": 0, "region_type": "face", "region_role": "face",
                "box": {"x": 100, "y": 100, "width": 1000, "height": 1000},
                "requested_size": [900, 900],
                "budget_ratio": 0.90, "threshold": 0.85,
            }],
        }), encoding="utf-8")
        tile_patch = job_dir / "intermediates" / "tiles" / "tile-0.png"
        tile_patch.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (900, 900), (120, 100, 90)).save(tile_patch)
        observation = self.run_script(
            "record_patch_observation.py", job_path,
            "--patch", tile_patch,
            "--region-type", "face",
            "--region-role", "face",
            "--requested-size", "900x900",
            "--tile-plan", tile_plan,
            "--tile-index", 0,
        )
        observed = json.loads(observation.stdout)
        self.assertTrue(observed["budget_recheck"]["accepted"])
        data = json.loads(job_path.read_text(encoding="utf-8"))
        data["tile_blend_receipts"] = [{
            "schema_version": 1,
            "sequence": 1,
            "kind": "tile-redraw",
            "tile_plan_sha256": hashlib.sha256(tile_plan.read_bytes()).hexdigest(),
            "tile_index": 0,
            "patch_sha256": observed["patch_sha256"],
            "input_base_sha256": "fixture-first-base",
            "output_path": str(master.resolve()),
            "output_sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
            "registration": {"accepted": True},
        }]
        job_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        gate = self.run_script(
            "delivery_gate.py", job_path, "--master", master, "--final", final,
            "--tile-plan", tile_plan,
        )
        report = json.loads(gate.stdout)
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["budget"]["tile_redraw"]["verdict"], "pass")

    def test_hd_master_tile_plan_without_generated_tile_evidence_is_rejected(self):
        job_dir = self.start_job()
        master = self.drive_to_details_processed(job_dir, REAL_DELIVERY_CANVAS)
        final = job_dir / "final.jpg"
        Image.open(master).save(final, quality=95)
        job_path = job_dir / "job.json"
        data = json.loads(job_path.read_text(encoding="utf-8"))
        data["detail"]["mode"] = "adaptive"
        data["creative_output"] = {"upstream_binding": "hd-master"}
        job_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tile_plan = job_dir / "tile-plan-no-execution.json"
        tile_plan.write_text(json.dumps({
            "verdict": "pass",
            "canvas": list(REAL_DELIVERY_CANVAS),
            "observed_patch_size": [1254, 1254],
            "tile_count": 1,
            "blend_sequence": [0],
            "coverage": {"hole_area": 0, "sliver_area": 0},
            "tiles": [{
                "index": 0, "region_type": "face", "region_role": "face",
                "box": {"x": 100, "y": 100, "width": 1000, "height": 1000},
                "requested_size": [900, 900],
                "budget_ratio": 0.90, "threshold": 0.85,
            }],
        }), encoding="utf-8")
        gate = self.run_script(
            "delivery_gate.py", job_path, "--master", master, "--final", final,
            "--tile-plan", tile_plan, ok=False,
        )
        self.assertEqual(gate.returncode, 3, gate.stdout + gate.stderr)
        report = json.loads(gate.stdout)
        self.assertEqual(report["budget"]["tile_redraw"]["missing_tile_evidence"], [0])
        self.assertIn("record_patch_observation", report["required_action"])

    def test_hd_master_tile_plan_canvas_must_match_final(self):
        job_dir = self.start_job()
        master = self.drive_to_details_processed(job_dir, REAL_DELIVERY_CANVAS)
        final = job_dir / "final.jpg"
        Image.open(master).save(final, quality=95)
        job_path = job_dir / "job.json"
        data = json.loads(job_path.read_text(encoding="utf-8"))
        data["detail"]["mode"] = "adaptive"
        data["creative_output"] = {"upstream_binding": "hd-master"}
        job_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tile_plan = job_dir / "tile-plan-wrong-canvas.json"
        tile_plan.write_text(json.dumps({
            "verdict": "pass",
            "canvas": list(REAL_WORKING_CANVAS),
            "observed_patch_size": [1254, 1254],
            "tile_count": 1,
            "blend_sequence": [0],
            "coverage": {"hole_area": 0, "sliver_area": 0},
            "tiles": [{
                "index": 0, "region_type": "face", "region_role": "face",
                "box": {"x": 100, "y": 100, "width": 1000, "height": 1000},
                "requested_size": [900, 900],
                "budget_ratio": 0.90, "threshold": 0.85,
            }],
        }), encoding="utf-8")
        gate = self.run_script(
            "delivery_gate.py", job_path, "--master", master, "--final", final,
            "--tile-plan", tile_plan, ok=False,
        )
        self.assertEqual(gate.returncode, 3, gate.stdout + gate.stderr)
        report = json.loads(gate.stdout)
        self.assertFalse(report["budget"]["tile_redraw"]["canvas_matches"])
        self.assertIn("canvas", report["required_action"].lower())

    def test_completed_is_refused_without_running_the_gate(self):
        job_dir = self.start_job()
        master = self.drive_to_details_processed(job_dir, REAL_DELIVERY_CANVAS)
        final = job_dir / "final.jpg"
        Image.open(master).save(final, quality=95)
        self.run_script("update_job.py", job_dir / "job.json", "--artifact", f"final_jpg={final}")
        refused = self.run_script("update_job.py", job_dir / "job.json", "--status", "completed", ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("delivery gate", refused.stdout + refused.stderr)

    def test_gate_result_is_invalidated_when_the_final_changes_afterwards(self):
        job_dir = self.start_job()
        master = self.drive_to_details_processed(job_dir, REAL_DELIVERY_CANVAS)
        final = job_dir / "final.jpg"
        Image.open(master).save(final, quality=95)
        self.run_script("update_job.py", job_dir / "job.json", "--artifact", f"final_jpg={final}")
        self.run_script("delivery_gate.py", job_dir / "job.json", "--master", master, "--final", final)
        Image.new("RGB", (REAL_DELIVERY_CANVAS[0] // 2, REAL_DELIVERY_CANVAS[1] // 2)).save(final, quality=95)
        refused = self.run_script("update_job.py", job_dir / "job.json", "--status", "completed", ok=False)
        self.assertIn("stale", (refused.stdout + refused.stderr).lower())


class PlannerRefusesDoomedRegionsTests(unittest.TestCase):
    """The planner recommended 1536x1536 patches while the client returned 1254x1254,
    so five doomed patches were generated, "accepted", and then stretched 4.56x.
    Planning must happen in delivery space against the observed return size."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.master = tmp / "master.png"
        Image.new("RGB", REAL_WORKING_CANVAS, (90, 120, 150)).save(self.master)
        self.analysis = tmp / "vision.json"
        self.analysis.write_text(json.dumps({
            "schema_version": 1,
            "coordinate_space": "pixel",
            "subject_type": "classical-portrait",
            "portrait_extent": "complex-full",
            "detail_complexity": "complex",
            "regions": {
                "subject": {"x": 116, "y": 249, "width": 812, "height": 1205},
                "face": {"x": 472, "y": 382, "width": 245, "height": 370},
                "hands": [{"x": 377, "y": 534, "width": 250, "height": 376}],
            },
        }), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, *extra):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "plan_detail_tiles.py"), "--image", str(self.master),
             "--vision-analysis", str(self.analysis), "--detail-budget", "balanced", *extra],
            capture_output=True, text=True,
        )

    def test_doomed_regions_are_dropped_before_generation(self):
        result = self.plan("--recovery-profile", "creative-safe",
                           "--delivery-canvas", f"{REAL_DELIVERY_CANVAS[0]}x{REAL_DELIVERY_CANVAS[1]}",
                           "--observed-patch-size", "1254x1254")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["working_canvas"], list(REAL_WORKING_CANVAS))
        self.assertEqual(plan["delivery_canvas"], list(REAL_DELIVERY_CANVAS))
        self.assertAlmostEqual(plan["delivery_scale"], 4.5625, places=4)
        self.assertEqual(plan["regions"], [], "no 1254px patch can serve a 4.56x larger delivery")
        self.assertTrue(plan["regions_dropped_for_budget"])
        for dropped in plan["regions_dropped_for_budget"]:
            self.assertLess(dropped["detail_ratio"], dropped["threshold"])
        self.assertLess(plan["delivery_feasibility"]["max_honest_delivery_width"], plan["delivery_canvas"][0])

    def test_regions_survive_when_delivery_is_native_scale(self):
        result = self.plan("--recovery-profile", "creative-safe",
                           "--delivery-canvas", f"{REAL_WORKING_CANVAS[0]}x{REAL_WORKING_CANVAS[1]}",
                           "--observed-patch-size", "1254x1254")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan = json.loads(result.stdout)
        self.assertGreater(len(plan["regions"]), 0)
        self.assertEqual(plan["regions_dropped_for_budget"], [])
        self.assertEqual(plan["delivery_scale"], 1.0)

    def test_observed_patch_size_is_required_when_delivery_is_enlarged(self):
        result = self.plan("--recovery-profile", "creative-safe",
                           "--delivery-canvas", f"{REAL_DELIVERY_CANVAS[0]}x{REAL_DELIVERY_CANVAS[1]}")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--observed-patch-size", result.stdout + result.stderr)


class PatchObservationBudgetRecheckTests(unittest.TestCase):
    """A patch that comes back smaller than the planner budgeted must fail at
    record time. DSC02304 requested 1536x1536, got 1254x1254 ten times over, and
    nothing recomputed the budget from the measured return."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = self.root / "source.jpg"
        Image.new("RGB", REAL_WORKING_CANVAS, (90, 120, 150)).save(self.source, quality=95)
        self.analysis = self.root / "vision.json"
        self.analysis.write_text(json.dumps({
            "schema_version": 1,
            "coordinate_space": "pixel",
            "subject_type": "classical-portrait",
            "portrait_extent": "close",
            "regions": {
                "subject": {"x": 100, "y": 100, "width": 800, "height": 1300},
                "face": {"x": 472, "y": 382, "width": 245, "height": 370},
            },
        }), encoding="utf-8")
        job = self.invoke("init_job.py", self.source, "--preset", "warm-gold-ancient",
                       "--confirmed", "--output-root", self.root / "jobs")
        self.job_dir = Path(job.stdout.strip().splitlines()[-1])
        self.plan_result = self.invoke(
            "plan_detail_tiles.py", "--image", self.source, "--vision-analysis", self.analysis,
            "--detail-budget", "balanced",
            "--delivery-canvas", f"{REAL_WORKING_CANVAS[0]}x{REAL_WORKING_CANVAS[1]}",
            "--observed-patch-size", f"{REAL_PATCH[0]}x{REAL_PATCH[1]}",
        )
        self.plan_path = self.job_dir / "detail-plan.json"
        self.plan_path.write_text(self.plan_result.stdout, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def invoke(self, script, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / script), *[str(a) for a in args]],
            capture_output=True, text=True,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def face_region_index(self):
        plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        for index, region in enumerate(plan["regions"]):
            if region["region_type"] == "face":
                return index, region
        self.fail(f"planner produced no face region: {sorted(r['region_type'] for r in plan['regions'])}")

    def record(self, patch_size, index):
        patch = self.job_dir / "intermediates" / "patches" / f"p-{index}-{patch_size[0]}.png"
        patch.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", patch_size, (10, 20, 30)).save(patch)
        result = self.invoke(
            "record_patch_observation.py", self.job_dir / "job.json",
            "--patch", patch, "--region-type", "face", "--region-role", "face",
            "--requested-size", f"{REAL_PATCH[0]}x{REAL_PATCH[1]}",
            "--planner-region-index", index, "--plan", self.plan_path,
        )
        return json.loads(result.stdout)

    def test_smaller_than_planned_patch_fails_the_budget_recheck(self):
        index, region = self.face_region_index()
        observation = self.record((40, 40), index)
        self.assertFalse(observation["budget_recheck"]["accepted"])
        self.assertLess(observation["budget_recheck"]["detail_ratio"], observation["budget_recheck"]["threshold"])
        self.assertEqual(observation["budget_recheck"]["planned_patch_size"], region["patch_size_planned"])

    def test_patch_matching_the_plan_passes_the_recheck(self):
        index, region = self.face_region_index()
        planned = region["patch_size_planned"]
        observation = self.record(tuple(planned), index)
        self.assertTrue(observation["budget_recheck"]["accepted"])


class DeliveryFeasibilityRoutingTests(unittest.TestCase):
    """Route by subject coverage instead of silently returning an empty plan:
    tell the caller the widest delivery the evidence can honestly carry, and how
    many tiles would be needed to reach the requested size."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.master = tmp / "master.png"
        Image.new("RGB", REAL_WORKING_CANVAS, (90, 120, 150)).save(self.master)
        self.analysis = tmp / "vision.json"
        self.analysis.write_text(json.dumps({
            "schema_version": 1,
            "coordinate_space": "pixel",
            "subject_type": "classical-portrait",
            "portrait_extent": "complex-full",
            "detail_complexity": "complex",
            "regions": {
                "subject": {"x": 116, "y": 249, "width": 812, "height": 1205},
                "face": {"x": 472, "y": 382, "width": 245, "height": 370},
                "hands": [{"x": 377, "y": 534, "width": 250, "height": 376}],
            },
        }), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, delivery):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "plan_detail_tiles.py"), "--image", str(self.master),
             "--vision-analysis", str(self.analysis), "--detail-budget", "balanced",
             "--recovery-profile", "creative-safe",
             "--delivery-canvas", delivery, "--observed-patch-size", "1254x1254"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_reports_honest_ceiling_and_tile_route_for_an_large_subject(self):
        plan = self.plan(f"{REAL_DELIVERY_CANVAS[0]}x{REAL_DELIVERY_CANVAS[1]}")
        verdict = plan["delivery_feasibility"]
        self.assertEqual(verdict["verdict"], "needs-tiling")
        # Measured: the full-body costume block is the binding region at ~0.50.
        self.assertLess(verdict["max_honest_delivery_width"], 3200)
        self.assertGreater(verdict["max_honest_delivery_width"], 1800)
        self.assertEqual(verdict["requested_delivery_width"], REAL_DELIVERY_CANVAS[0])
        tiling = plan["tiling_requirement"]
        self.assertGreater(tiling["tile_count"], 4, "a half-frame subject needs many tiles")
        self.assertEqual(tiling["tile_size"][0], 1254)
        self.assertEqual(tiling["estimated_generation_calls"], tiling["tile_count"])
        self.assertIn("4672", tiling["consent_prompt"])

    def test_native_delivery_needs_no_tiling(self):
        plan = self.plan("2048x3072")
        self.assertEqual(plan["delivery_feasibility"]["verdict"], "native")
        self.assertEqual(plan["tiling_requirement"], None)
        self.assertGreater(len(plan["regions"]), 0)
        self.assertEqual(plan["regions_dropped_for_budget"], [])


class GateReadsBudgetNotGeometryTests(unittest.TestCase):
    """The hole: a Lanczos-inflated master makes the geometry ratio look fine while
    the subject regions are still starved, so the gate must consult the plan."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = self.root / "source.jpg"
        Image.new("RGB", REAL_DELIVERY_CANVAS, (90, 120, 150)).save(self.source, quality=95)
        job = self.invoke("init_job.py", self.source, "--preset", "warm-gold-ancient",
                          "--confirmed", "--output-root", self.root / "jobs")
        self.job_dir = Path(job.stdout.strip().splitlines()[-1])
        self.job = self.job_dir / "job.json"

    def tearDown(self):
        self._tmp.cleanup()

    def invoke(self, script, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPTS / script), *[str(a) for a in args]],
                                capture_output=True, text=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def gate(self, *extra):
        return self.invoke("delivery_gate.py", self.job, *extra, ok=False)

    def make(self, path, size):
        Image.new("RGB", size, (90, 120, 150)).save(path)
        return path

    def test_budget_failure_rejects_even_when_geometry_looks_native(self):
        # Master and final are the same size, so the old geometry-only gate passed.
        master = self.make(self.job_dir / "master.png", (4672, 7008))
        final = self.make(self.job_dir / "final.jpg", (4672, 7008))
        plan = self.job_dir / "detail-plan.json"
        plan.write_text(json.dumps({
            "working_canvas": [4096, 6144], "delivery_canvas": [4672, 7008],
            "regions": [], "region_count": 0,
            "regions_dropped_for_budget": [{
                "region_type": "face", "region_role": "face", "planned_patch_size": [830, 1254],
                "detail_ratio": 0.743, "threshold": 0.85, "reason": "cannot serve the delivery canvas",
            }],
        }), encoding="utf-8")
        result = self.gate("--master", master, "--final", final, "--plan", plan)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["verdict"], "fail")
        self.assertEqual(report["geometry"]["verdict"], "pass")
        self.assertEqual(report["budget"]["verdict"], "fail")
        self.assertIn("tile", report["required_action"].lower())

    def test_lanczos_inflation_does_not_count_as_raising_the_canvas(self):
        approved = self.make(self.job_dir / "approved.png", (1024, 1536))
        final = self.make(self.job_dir / "final.jpg", (4672, 7008))
        data = json.loads(self.job.read_text(encoding="utf-8"))
        # A recorded Lanczos pass must not license the 4.56x geometry claim.
        data["upscale_passes"] = [{"engine": "fallback-lanczos", "adds_information": False,
                                   "from": [1024, 1536], "to": [4096, 6144]}]
        self.job.write_text(json.dumps(data), encoding="utf-8")
        result = self.gate("--master", approved, "--final", final)
        self.assertEqual(json.loads(result.stdout)["geometry"]["effective_scale"], 4.5625)
        self.assertEqual(result.returncode, 3)

    def test_real_engine_pass_licenses_a_smaller_geometry_scale(self):
        approved = self.make(self.job_dir / "approved.png", (1024, 1536))
        final = self.make(self.job_dir / "final.jpg", (4672, 7008))
        data = json.loads(self.job.read_text(encoding="utf-8"))
        data["upscale_passes"] = [{"engine": "4x-ultrasharp-ncnn", "adds_information": True,
                                   "from": [1024, 1536], "to": [4096, 6144]}]
        data["delivery_gate"] = None
        self.job.write_text(json.dumps(data), encoding="utf-8")
        result = self.gate("--master", approved, "--final", final)
        self.assertEqual(json.loads(result.stdout)["geometry"]["effective_scale"], 1.140625)


class ApprovalBindingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = self.root / "source.jpg"
        Image.new("RGB", REAL_WORKING_CANVAS, (90, 120, 150)).save(self.source, quality=95)
        job = self.invoke("init_job.py", self.source, "--preset", "warm-gold-ancient",
                          "--confirmed", "--detail-mode", "base-only", "--output-root", self.root / "jobs")
        self.job_dir = Path(job.stdout.strip().splitlines()[-1])
        self.job = self.job_dir / "job.json"
        self.invoke("update_job.py", self.job, "--status", "prepared")
        self.invoke("update_job.py", self.job, "--status", "base_generated")

    def tearDown(self):
        self._tmp.cleanup()

    def invoke(self, script, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPTS / script), *[str(a) for a in args]],
                                capture_output=True, text=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_approval_without_an_artifact_is_refused(self):
        result = self.invoke("update_job.py", self.job, "--approve-base-preview", ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--artifact", result.stdout + result.stderr)

    def test_approval_binds_path_size_and_hash_of_the_approved_image(self):
        preview = self.job_dir / "intermediates" / "approved-preview.png"
        preview.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", REAL_WORKING_CANVAS, (90, 120, 150)).save(preview)
        self.invoke("update_job.py", self.job, "--approve-base-preview", "--artifact", f"base_preview={preview}")
        record = json.loads(self.job.read_text(encoding="utf-8"))["approved_preview"]
        self.assertEqual(record["size"], list(REAL_WORKING_CANVAS))
        self.assertEqual(len(record["sha256"]), 64)
        self.assertEqual(Path(record["path"]), preview.resolve())

    def test_gate_writes_a_diff_image_against_the_approved_preview(self):
        preview = self.job_dir / "intermediates" / "approved-preview.png"
        preview.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", REAL_WORKING_CANVAS, (90, 120, 150)).save(preview)
        self.invoke("update_job.py", self.job, "--approve-base-preview", "--artifact", f"base_preview={preview}")
        composite = self.job_dir / "composite.png"
        Image.new("RGB", REAL_WORKING_CANVAS, (140, 120, 150)).save(composite)
        final = self.job_dir / "final.jpg"
        Image.open(composite).save(final, quality=95)
        self.invoke("delivery_gate.py", self.job, "--master", composite, "--final", final)
        report = json.loads(self.job.read_text(encoding="utf-8"))["delivery_gate"]
        diff = Path(report["diff"]["path"])
        self.assertTrue(diff.is_file(), "preview_vs_final_diff.png must exist for the user to inspect")
        self.assertGreater(report["diff"]["changed_pixel_share"], 0)
        self.assertEqual(report["diff"]["compared_at_size"], list(REAL_WORKING_CANVAS))


class HdCreativeContractTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = self.root / "source.jpg"
        Image.new("RGB", (1200, 1800), (90, 120, 150)).save(self.source, quality=95)

    def tearDown(self):
        self._tmp.cleanup()

    def test_hd_master_has_stage_authorities_and_does_not_run_whole_image_upscale(self):
        result = subprocess.run(
            [
                sys.executable, str(SCRIPTS / "init_job.py"), str(self.source),
                "--preset", "warm-gold-ancient",
                "--creative-recipe", "s001-abstract-quartet",
                "--creative-assembly-mode", "direct-effect",
                "--creative-hd-chain",
                "--confirmed",
                "--output-root", str(self.root / "jobs"),
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        job = json.loads(Path(result.stdout.strip().splitlines()[-1]).joinpath("job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["creative_output"]["upstream_binding"], "hd-master")
        self.assertFalse(job["creative_output"]["upscale"]["enabled"])
        self.assertEqual(job["detail"]["mode"], "adaptive")
        self.assertIn("stage_1_refinement", job["authority_model"])
        self.assertIn("stage_2_creative", job["authority_model"])
        self.assertIn("stage_3_tile_redraw", job["authority_model"])


class RegisterBlendReceiptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.job = self.root / "job.json"
        self.tile_plan = self.root / "tile-plan.json"

        rng = __import__("numpy").random.default_rng(12345)
        base_array = rng.integers(0, 256, size=(512, 512, 3), dtype="uint8")
        self.base = self.root / "base.png"
        Image.fromarray(base_array, "RGB").save(self.base)
        self.target = self.root / "target.png"
        Image.fromarray(base_array[128:384, 128:384], "RGB").save(self.target)
        self.patch = self.root / "tile.png"
        Image.open(self.target).save(self.patch)
        self.output = self.root / "composite.png"

        self.tile_plan.write_text(json.dumps({
            "verdict": "pass",
            "canvas": [512, 512],
            "observed_patch_size": [256, 256],
            "tile_count": 1,
            "blend_sequence": [0],
            "coverage": {"hole_area": 0, "sliver_area": 0},
            "tiles": [{
                "index": 0,
                "region_type": "face",
                "region_role": "face",
                "box": {"x": 128, "y": 128, "width": 256, "height": 256},
                "requested_size": [256, 256],
                "budget_ratio": 1.0,
                "threshold": 0.85,
            }],
        }), encoding="utf-8")
        self.job.write_text(json.dumps({
            "execution_mode": "creative-translation",
            "detail": {"mode": "adaptive"},
            "creative_output": {"upstream_binding": "hd-master"},
            "patch_observations": [],
            "artifacts": [],
        }), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def invoke(self, script, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / script), *[str(a) for a in args]],
            capture_output=True, text=True,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_detail_plan_requires_real_patch_and_blend_execution(self):
        detail_plan = self.root / "detail-plan.json"
        detail_plan.write_text(json.dumps({
            "working_canvas": [512, 512],
            "delivery_canvas": [512, 512],
            "delivery_scale": 1.0,
            "region_count": 1,
            "regions_dropped_for_budget": [],
            "delivery_feasibility": {"verdict": "native"},
            "regions": [{
                "region_type": "face",
                "region_role": "face",
                "crop": {"x": 128, "y": 128, "width": 256, "height": 256},
                "subject_box": {"x": 128, "y": 128, "width": 256, "height": 256},
                "patch_size_planned": [256, 256],
            }],
        }), encoding="utf-8")
        data = json.loads(self.job.read_text(encoding="utf-8"))
        data["execution_mode"] = "photo-refinement"
        data["creative_output"] = None
        self.job.write_text(json.dumps(data, indent=2), encoding="utf-8")

        no_execution = self.invoke(
            "delivery_gate.py", self.job,
            "--master", self.base,
            "--final", self.base,
            "--plan", detail_plan,
            ok=False,
        )
        self.assertEqual(no_execution.returncode, 3, no_execution.stdout + no_execution.stderr)
        self.assertFalse(json.loads(no_execution.stdout)["budget"]["execution_evidence"]["accepted"])

        observed = self.invoke(
            "record_patch_observation.py", self.job,
            "--patch", self.patch,
            "--region-type", "face",
            "--region-role", "face",
            "--requested-size", "256x256",
            "--plan", detail_plan,
            "--planner-region-index", 0,
        )
        self.assertTrue(json.loads(observed.stdout)["budget_recheck"]["accepted"])

        blended = self.invoke(
            "register_blend.py",
            "--base", self.base,
            "--target", self.target,
            "--patch", self.patch,
            "--output", self.output,
            "--x", 128,
            "--y", 128,
            "--region-type", "face",
            "--min-inliers", 20,
            "--job", self.job,
            "--plan", detail_plan,
            "--planner-region-index", 0,
        )
        receipt = json.loads(blended.stdout)["blend_receipt"]
        self.assertEqual(receipt["kind"], "detail-patch")
        self.assertEqual(receipt["planner_region_index"], 0)

        gate = self.invoke(
            "delivery_gate.py", self.job,
            "--master", self.output,
            "--final", self.output,
            "--plan", detail_plan,
        )
        gate_report = json.loads(gate.stdout)
        self.assertEqual(gate_report["verdict"], "pass")
        self.assertTrue(gate_report["budget"]["execution_evidence"]["accepted"])

    def test_full_canvas_redraw_can_honestly_replace_global_interpolation(self):
        approved = self.root / "approved-small.png"
        with Image.open(self.base) as image:
            image.resize((128, 128), Image.Resampling.LANCZOS).save(approved)

        full_plan = self.root / "full-canvas-plan.json"
        full_plan.write_text(json.dumps({
            "schema_version": 1,
            "verdict": "pass",
            "canvas": [512, 512],
            "observed_patch_size": [512, 512],
            "tile_count": 1,
            "blend_sequence": [0],
            "provenance": {"source": ["detail_plan", "full_canvas"]},
            "coverage": {
                "target_area": 512 * 512,
                "covered_area": 512 * 512,
                "uncovered_area": 0,
                "hole_area": 0,
                "sliver_area": 0,
            },
            "tiles": [{
                "index": 0,
                "region_type": "generic",
                "region_role": "full-canvas",
                "box": {"x": 0, "y": 0, "width": 512, "height": 512},
                "requested_size": [512, 512],
                "budget_ratio": 1.0,
                "threshold": 0.50,
                "blend_order": 10,
            }],
        }), encoding="utf-8")

        full_patch = self.root / "full-tile.png"
        Image.open(self.base).save(full_patch)
        full_output = self.root / "full-composite.png"
        data = json.loads(self.job.read_text(encoding="utf-8"))
        data["execution_mode"] = "photo-refinement"
        data["detail"] = {"mode": "adaptive"}
        data["creative_output"] = None
        data["approved_preview"] = {
            "kind": "base_preview",
            "path": str(approved.resolve()),
            "size": [128, 128],
            "sha256": hashlib.sha256(approved.read_bytes()).hexdigest(),
        }
        data["patch_observations"] = []
        data["tile_blend_receipts"] = []
        self.job.write_text(json.dumps(data, indent=2), encoding="utf-8")

        observed = self.invoke(
            "record_patch_observation.py", self.job,
            "--patch", full_patch,
            "--region-type", "generic",
            "--region-role", "full-canvas",
            "--requested-size", "512x512",
            "--tile-plan", full_plan,
            "--tile-index", 0,
        )
        self.assertTrue(json.loads(observed.stdout)["budget_recheck"]["accepted"])

        self.invoke(
            "register_blend.py",
            "--base", self.base,
            "--target", self.base,
            "--patch", full_patch,
            "--output", full_output,
            "--x", 0, "--y", 0,
            "--region-type", "generic",
            "--min-inliers", 20,
            "--job", self.job,
            "--tile-plan", full_plan,
            "--tile-index", 0,
        )
        gate = self.invoke(
            "delivery_gate.py", self.job,
            "--master", full_output,
            "--final", full_output,
            "--tile-plan", full_plan,
        )
        report = json.loads(gate.stdout)
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["geometry"]["geometry_override"], "full-canvas-tile-redraw")
        self.assertEqual(report["geometry"]["information_canvas"], [128, 128])
        self.assertTrue(report["budget"]["tile_redraw"]["full_canvas_native_ok"])

    def test_register_blend_records_a_live_tile_hash_chain_receipt(self):
        observed = self.invoke(
            "record_patch_observation.py", self.job,
            "--patch", self.patch,
            "--region-type", "face",
            "--region-role", "face",
            "--requested-size", "256x256",
            "--tile-plan", self.tile_plan,
            "--tile-index", 0,
        )
        self.assertTrue(json.loads(observed.stdout)["budget_recheck"]["accepted"])

        blended = self.invoke(
            "register_blend.py",
            "--base", self.base,
            "--target", self.target,
            "--patch", self.patch,
            "--output", self.output,
            "--x", 128,
            "--y", 128,
            "--region-type", "face",
            "--min-inliers", 20,
            "--job", self.job,
            "--tile-plan", self.tile_plan,
            "--tile-index", 0,
        )
        report = json.loads(blended.stdout)
        self.assertTrue(report["accepted"])
        receipt = report["tile_blend_receipt"]
        self.assertEqual(receipt["tile_index"], 0)
        self.assertEqual(receipt["output_sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())

        gate = self.invoke(
            "delivery_gate.py", self.job,
            "--master", self.output,
            "--final", self.output,
            "--tile-plan", self.tile_plan,
        )
        gate_report = json.loads(gate.stdout)
        self.assertEqual(gate_report["verdict"], "pass")
        self.assertTrue(gate_report["budget"]["tile_redraw"]["blend_evidence"]["accepted"])


class HdWorkingCanvasRoutingTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import prepare_hd_working_canvas
        import delivery_gate
        self.router = prepare_hd_working_canvas
        self.delivery_gate = delivery_gate

    def tearDown(self):
        sys.path.pop(0)

    def test_native_canvas_does_not_upscale_without_need(self):
        route = self.router.choose_route((2000, 3000), (2048, 3072), True)
        self.assertEqual(route["route"], "native-detail")
        self.assertFalse(route["requires_full_canvas_redraw"])

    def test_model_route_is_used_inside_native_4x_information_span(self):
        route = self.router.choose_route((1024, 1536), (3072, 4608), True)
        self.assertEqual(route["route"], "ultrasharp-detail")
        self.assertEqual(route["model_scale"], 3)

    def test_source_width_beyond_4x_routes_to_full_canvas_redraw(self):
        route = self.router.choose_route((1024, 1536), (4672, 7008), True)
        self.assertEqual(route["route"], "full-canvas-tile-redraw")
        self.assertTrue(route["requires_full_canvas_redraw"])
        self.assertEqual(route["model_scale"], 4)

    def test_missing_ai_engine_routes_to_full_canvas_redraw(self):
        route = self.router.choose_route((1024, 1536), (2048, 3072), False)
        self.assertEqual(route["route"], "full-canvas-tile-redraw")
        self.assertEqual(route["model_scale"], 1)

    def test_delivery_gate_caps_six_x_file_at_four_x_information(self):
        data = {"upscale_passes": [{
            "engine": "4x-ultrasharp-spandrel",
            "adds_information": True,
            "from": [1024, 1536],
            "to": [6144, 9216],
            "information_to": [4096, 6144],
            "native_information_scale": 4,
            "interpolated_tail": [2048, 3072],
        }]}
        factor, passes = self.delivery_gate.information_raise(data, [1024, 1536])
        self.assertEqual(factor, 4.0)
        self.assertEqual(passes[0]["to"], [6144, 9216])
        self.assertEqual(passes[0]["information_to"], [4096, 6144])

    def test_interpolated_tail_cannot_be_laundered_into_second_ai_pass(self):
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
        factor, passes = self.delivery_gate.information_raise(data, [1024, 1536])
        self.assertEqual(factor, 4.0)
        self.assertEqual(len(passes), 1)


class UltraSharpIntegrityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        sys.path.insert(0, str(SCRIPTS))
        import upscale_image
        self.upscale_image = upscale_image
        self.original_model_path = upscale_image.MODEL_PATH

    def tearDown(self):
        self.upscale_image.MODEL_PATH = self.original_model_path
        sys.path.pop(0)
        self._tmp.cleanup()

    def test_model_digest_is_repository_pinned(self):
        self.assertEqual(
            self.upscale_image.MODEL_EXPECTED_SHA256,
            "a5812231fc936b42af08a5edba784195495d303d5b3248c24489ef0c4021fe01",
        )

    def test_untrusted_cached_pickle_is_rejected_even_without_a_sidecar(self):
        fake = Path(self._tmp.name) / "4x-UltraSharp.pth"
        fake.write_bytes(b"not the pinned model")
        self.upscale_image.MODEL_PATH = fake
        self.assertFalse(self.upscale_image.cached_model_matches_digest())


class VersionConsistencyTests(unittest.TestCase):
    """The version was restated in five places and had drifted (docs said v2.3
    while the code wrote 2.4), so the constants and the prose are now pinned."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import job_contract
        self.job_contract = job_contract
        self.root = SKILL_ROOT.parent

    def test_skill_heading_matches_the_constant(self):
        heading = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8").splitlines()[5]
        self.assertEqual(heading, f"# Photo Refiner v{self.job_contract.SKILL_VERSION}")

    def test_config_schema_matches_the_constant(self):
        schema = (SKILL_ROOT / "references" / "config-schema.md").read_text(encoding="utf-8")
        self.assertIn(f'release_version: "{self.job_contract.SKILL_VERSION}"', schema)
        self.assertNotIn("Version 2.3", schema)

    def test_manifest_release_version_is_the_constant(self):
        source = (SCRIPTS / "init_job.py").read_text(encoding="utf-8")
        self.assertIn('"release_version": RELEASE_VERSION', source)
        self.assertNotIn('"release_version": "', source)

    def test_no_script_still_calls_itself_an_older_version(self):
        stale = []
        for path in SCRIPTS.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if path.name != "job_contract.py" and "Photo Refiner v" in text:
                stale.append(path.name)
        self.assertEqual(stale, [], "script docstrings must not hardcode the product version")

    def test_plugin_prose_does_not_carry_the_skill_version(self):
        manifest = json.loads((self.root / "plugin" / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        blob = json.dumps(manifest, ensure_ascii=False)
        import re
        found = re.findall(r"Photo Refiner v\d+\.\d+", blob)
        self.assertEqual(found, [], f"plugin text must not duplicate the skill version: {found}")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$",
                         "repo manifest holds the base version; the build step adds the +codex stamp")


class TileRedrawPlannerTests(unittest.TestCase):
    """needs-tiling must become real tile boxes, not a number the agent guesses at.

    Tiles are cut at `observed cap / region threshold` so each generated patch meets
    its own budget, gaps are rejected, and overlapping region boxes must not produce
    duplicate generations.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # A canvas already raised to the delivery size: tiling happens in delivery space.
        self.canvas = self.root / "canvas.png"
        Image.new("RGB", (4672, 7008), (90, 120, 150)).save(self.canvas)
        self.analysis = self.root / "vision.json"
        self.analysis.write_text(json.dumps({
            "schema_version": 1,
            "coordinate_space": "pixel",
            "subject_type": "classical-portrait",
            "portrait_extent": "complex-full",
            "detail_complexity": "complex",
            "regions": {
                "subject": {"x": 620, "y": 1140, "width": 3704, "height": 5500},
                "face": {"x": 2150, "y": 1740, "width": 1118, "height": 1688},
                "hands": [{"x": 1720, "y": 2435, "width": 1141, "height": 1716}],
            },
        }), encoding="utf-8")
        plan = self.invoke(
            "plan_detail_tiles.py", "--image", self.canvas, "--vision-analysis", self.analysis,
            "--detail-budget", "balanced", "--recovery-profile", "creative-safe",
            "--delivery-canvas", "4672x7008", "--observed-patch-size", "1254x1254",
        )
        self.plan_path = self.root / "detail-plan.json"
        self.plan_path.write_text(plan.stdout, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def invoke(self, script, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPTS / script), *[str(a) for a in args]],
                                capture_output=True, text=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def tile_plan(self, *extra):
        result = self.invoke("plan_tile_redraw.py", "--image", self.canvas,
                             "--observed-patch-size", "1254x1254", *extra)
        return json.loads(result.stdout)

    def test_a_thin_overhang_does_not_force_a_near_duplicate_tile(self):
        """A box 2% wider than one tile's reach must not cost a second full tile.

        The remainder is a thin strip that the already-raised base canvas serves;
        emitting a 98%-identical generation for it is waste the user pays in latency.
        """
        from job_contract import tiles_for_span
        self.assertEqual(tiles_for_span((1962, 1962), (1254, 1254), 0.65), 4)
        plan = self.tile_plan("--region-box", "1729,1135,1962,2497", "--region-type", "head",
                              "--sliver-margin", "0.05")
        head = [t for t in plan["tiles"] if t["region_type"] == "head"]
        self.assertEqual(len(head), 2, "both near-duplicate columns should be dropped")
        self.assertGreater(plan["coverage"]["uncovered_area"], 0)
        self.assertLessEqual(plan["coverage"]["largest_sliver_fraction"], 0.05)
        self.assertEqual(plan["verdict"], "pass")

    def test_tiles_sit_where_the_regions_actually_are(self):
        """Guards against rebuilding dropped regions at the canvas origin, which makes
        every grid overlap in one corner and fakes a lower tile count."""
        plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        face = next((r for r in (plan.get("regions") or []) + (plan.get("regions_dropped_for_budget") or [])
                     if r["region_type"] == "face"), None)
        self.assertIsNotNone(face, "the plan must still report the face region")
        origin = (face.get("crop") or {}).get("x")
        size = face.get("crop_size") or [face["crop"]["width"], face["crop"]["height"]]
        expected = (origin if origin is not None else 0, size)
        tile_plan = self.tile_plan("--detail-plan", self.plan_path)
        face_tiles = [t for t in tile_plan["tiles"] if t["region_type"] == "face"]
        self.assertTrue(face_tiles)
        # The face is mid-frame in this fixture, so no face tile may start at (0,0).
        for tile in face_tiles:
            self.assertGreater(tile["box"]["x"] + tile["box"]["y"], 1000,
                               f"face tile landed at the origin: {tile['box']} (expected near {expected})")

    def test_no_gaps_and_no_unreachable_tiles(self):
        plan = self.tile_plan("--detail-plan", self.plan_path)
        self.assertEqual(plan["verdict"], "pass")
        self.assertEqual(plan["coverage"]["hole_area"], 0,
                         "no real hole may remain; thin remainders are tracked separately")
        self.assertGreater(plan["tile_count"], 0)
        self.assertEqual(plan["estimated_generation_calls"], plan["tile_count"])
        for tile in plan["tiles"]:
            self.assertGreaterEqual(tile["budget_ratio"], tile["threshold"],
                                    f"tile {tile['index']} cannot be served at its own threshold")
            self.assertLessEqual(tile["requested_size"][0], 1254)
            self.assertLessEqual(tile["requested_size"][1], 1254)
            box = tile["box"]
            self.assertLessEqual(box["x"] + box["width"], plan["canvas"][0])
            self.assertLessEqual(box["y"] + box["height"], plan["canvas"][1])

    def test_overlapping_region_boxes_do_not_duplicate_tiles(self):
        plan = self.tile_plan("--detail-plan", self.plan_path)
        boxes = [(t["box"]["x"], t["box"]["y"], t["box"]["width"], t["box"]["height"]) for t in plan["tiles"]]
        self.assertEqual(len(boxes), len(set(boxes)), "the same tile must not be generated twice")
        naive = sum(entry["tiles"] for entry in (plan["source_tiling_request"] or {}).get("regions", []))
        self.assertLess(plan["tile_count"], naive, "dedupe must lower the naive per-region sum")
        self.assertEqual(plan["deduplicated_tiles"], naive - plan["tile_count"])

    def test_face_tiles_are_blended_last(self):
        plan = self.tile_plan("--detail-plan", self.plan_path)
        ordered = sorted(plan["tiles"], key=lambda tile: tile["blend_order"])
        self.assertEqual(ordered[-1]["region_type"], "face")
        self.assertEqual(ordered[0]["blend_order"], min(t["blend_order"] for t in plan["tiles"]))

    def test_full_canvas_mode_covers_the_whole_canvas(self):
        plan = self.tile_plan("--full-canvas", "--sliver-margin", "0")
        self.assertEqual(plan["coverage"]["uncovered_area"], 0)
        self.assertEqual(plan["coverage"]["hole_area"], 0)
        self.assertEqual(plan["coverage"]["target_area"], 4672 * 7008)

    def test_refuses_missing_observed_patch_size(self):
        result = self.invoke("plan_tile_redraw.py", "--image", self.canvas,
                            "--detail-plan", self.plan_path, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--observed-patch-size", result.stdout + result.stderr)


    def test_estimator_and_grid_agree_on_every_framing(self):
        """tiling_requirement's count is what the user consents to; it must match what
        the tiler actually emits, or the consent is for a different job."""
        sys.path.insert(0, str(SCRIPTS))
        try:
            from job_contract import tiles_for_span
            from plan_tile_redraw import grid_tiles
        finally:
            sys.path.pop(0)
        threshold = 0.85  # the face bar the user chose to keep
        cases = [(888, 1191), (1308, 1475), (1475, 1475), (2056, 2943), (2900, 1689), (1962, 2497)]
        for width, height in cases:
            reach = int(1254 / threshold)
            estimated = tiles_for_span((width, height), (1254, 1254), threshold)
            gridded = len(grid_tiles({"x": 0, "y": 0, "width": width, "height": height},
                                     reach, reach, 0.15, 4672, 7008))
            self.assertEqual(estimated, gridded, f"{width}x{height} estimate/grid mismatch")

    def test_face_bar_of_085_scales_the_count_with_framing(self):
        """Kept at 0.85 on purpose: a close-up must cost more generations than a wide
        shot rather than be allowed to coarsen, so quality stays framing-independent."""
        wide = self.tile_plan("--region-box", "2150,1741,888,1191", "--region-type", "face")
        close = self.tile_plan("--region-box", "1308,841,2056,2943", "--region-type", "face")
        self.assertEqual(wide["tile_count"], 1)
        self.assertGreater(close["tile_count"], wide["tile_count"] + 2)
        for plan in (wide, close):
            for tile in plan["tiles"]:
                self.assertGreaterEqual(tile["budget_ratio"], 0.85)


if __name__ == "__main__":
    unittest.main()
