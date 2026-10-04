import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SKILL_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = SKILL_ROOT / "references" / "starryear" / "catalog.json"


def write_approved_preview(job_json: Path, name="approved-preview.png", size=(32, 48)) -> Path:
    """Approvals must bind the exact image the user was shown."""
    path = job_json.parent / name
    Image.new("RGB", size, (10, 20, 30)).save(path)
    return path


def pass_delivery_gate(job_json: Path, size=(32, 48)):
    """Satisfy the current evidence contract at native scale.

    Ordinary lifecycle cases need the automatic working-canvas input record.
    HD creative cases additionally need one audited full-canvas redraw tile; the
    dedicated v2.4 suite owns the deeper tile geometry assertions.
    """
    job_dir = job_json.parent
    data = json.loads(job_json.read_text(encoding="utf-8"))
    hd_master = (data.get("creative_output") or {}).get("upstream_binding") == "hd-master"
    master = job_dir / "gate-master.png"
    final = job_dir / "gate-final.png"
    if hd_master:
        Image.effect_noise(size, 100).convert("RGB").save(master)
    else:
        Image.new("RGB", size, "white").save(master)
    Image.new("RGB", size, "white").save(final)
    subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / "prepare_hd_working_canvas.py"), str(job_json),
         "--input", str(master), "--output", str(job_dir / "intermediates" / "hd-working.png"),
         "--delivery-size", f"{size[0]}x{size[1]}"],
        check=True, capture_output=True, text=True,
    )
    if not hd_master:
        gate_args = ["--master", str(master), "--final", str(final)]
    else:
        prepared = json.loads(job_json.read_text(encoding="utf-8"))["hd_working_canvas"]
        tile_plan = job_dir / "full-canvas-tile-plan.json"
        canvas_hash = prepared["output_sha256"]
        tile_plan.write_text(json.dumps({
            "schema_version": 1,
            "verdict": "pass",
            "canvas": list(size),
            "canvas_path": prepared["output"],
            "canvas_sha256": canvas_hash,
            "observed_patch_size": list(size),
            "tile_count": 1,
            "blend_sequence": [0],
            "provenance": {"source": ["detail_plan", "full_canvas"]},
            "coverage": {
                "target_area": size[0] * size[1],
                "covered_area": size[0] * size[1],
                "uncovered_area": 0,
                "hole_area": 0,
                "sliver_area": 0,
            },
            "tiles": [{
                "index": 0,
                "region_type": "generic",
                "region_role": "full-canvas",
                "box": {"x": 0, "y": 0, "width": size[0], "height": size[1]},
                "requested_size": list(size),
                "budget_ratio": 1.0,
                "threshold": 0.50,
                "blend_order": 10,
            }],
        }, indent=2), encoding="utf-8")
        patch = job_dir / "full-canvas-patch.png"
        target = job_dir / "full-canvas-target.png"
        Image.open(master).save(patch)
        Image.open(master).save(target)
        subprocess.run(
            [sys.executable, str(SKILL_ROOT / "scripts" / "record_patch_observation.py"), str(job_json),
             "--patch", str(patch), "--region-type", "generic", "--region-role", "full-canvas",
             "--requested-size", f"{size[0]}x{size[1]}", "--tile-plan", str(tile_plan), "--tile-index", "0"],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            [sys.executable, str(SKILL_ROOT / "scripts" / "register_blend.py"),
             "--base", str(master), "--target", str(target), "--patch", str(patch),
             "--output", str(final), "--x", "0", "--y", "0", "--region-type", "generic",
             "--model", "homography", "--min-inliers", "3", "--job", str(job_json),
             "--tile-plan", str(tile_plan), "--tile-index", "0"],
            check=True, capture_output=True, text=True,
        )
        gate_args = ["--master", str(final), "--final", str(final), "--tile-plan", str(tile_plan)]
    subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / "delivery_gate.py"), str(job_json), *gate_args],
        check=True, capture_output=True, text=True,
    )


class StarryearCreativeTranslationTests(unittest.TestCase):
    def test_catalog_paths_and_previews_are_complete(self):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        recipes = catalog["recipes"]
        self.assertEqual(len(recipes), 15)
        self.assertEqual(len({recipe["id"] for recipe in recipes}), 15)
        missing = []
        for recipe in recipes:
            source_count = recipe["sourceCount"]
            self.assertGreaterEqual(source_count["min"], 1)
            self.assertGreaterEqual(source_count["max"], source_count["min"])
            recipe_root = CATALOG_PATH.parent / recipe["recipePath"]
            skill_path = recipe_root / "SKILL.md"
            self.assertTrue(skill_path.is_file(), recipe["id"])
            for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", skill_path.read_text(encoding="utf-8")):
                if "://" in target or target.startswith("#"):
                    continue
                if target.rstrip("/") == "assets/examples":
                    # The integrated selector carries one compact approved thumbnail
                    # per recipe instead of duplicating full upstream galleries.
                    continue
                self.assertTrue((recipe_root / target).exists(), f"{recipe['id']}: missing linked resource {target}")
            if recipe["preview"]["status"] == "available":
                self.assertTrue((CATALOG_PATH.parent / recipe["preview"]["path"]).is_file(), recipe["id"])
            else:
                missing.append(recipe["id"])
        self.assertEqual(
            missing,
            ["s013-vesak"],
        )
        self.assertTrue((CATALOG_PATH.parent / "recipes" / "S.015-Starryear-Diffuse-Gradient" / "scripts" / "compose_9x16.py").is_file())

    def test_vesak_and_mix_are_distinct_entries_with_shared_current_workflow(self):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        recipes = {recipe["id"]: recipe for recipe in catalog["recipes"]}
        vesak = recipes["s013-vesak"]
        mix = recipes["s014-mix"]
        self.assertNotEqual(vesak["titleZh"], mix["titleZh"])
        self.assertNotEqual(vesak["sourceCommit"], mix["sourceCommit"])
        self.assertEqual(vesak["sharedWorkflowWith"], mix["id"])
        self.assertEqual(mix["sharedWorkflowWith"], vesak["id"])
        self.assertEqual(
            (CATALOG_PATH.parent / vesak["recipePath"] / "SKILL.md").read_bytes(),
            (CATALOG_PATH.parent / mix["recipePath"] / "SKILL.md").read_bytes(),
        )

    def test_init_job_routes_creative_recipe_and_rejects_wrong_source_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.jpg"
            Image.new("RGB", (32, 48), (80, 100, 120)).save(source)
            output = root / "jobs"
            command = [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "init_job.py"),
                str(source),
                "--output-root",
                str(output),
                "--preset",
                "natural-cinematic",
                "--creative-recipe",
                "s001-abstract-quartet",
                "--confirmed",
            ]
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            manifest = json.loads((Path(result.stdout.strip()) / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["execution_mode"], "creative-translation")
            self.assertEqual(manifest["creative_recipe"]["id"], "s001-abstract-quartet")
            self.assertEqual(manifest["resolved_prompt"]["preset"], "natural-cinematic")
            self.assertEqual(manifest["detail"]["mode"], "creative-safe-adaptive")
            self.assertTrue(manifest["base_preview"]["required"])
            self.assertEqual(manifest["creative_output"]["mode"], "direct-effect")
            self.assertFalse(manifest["creative_output"]["original_assembly"])

            incompatible_command = list(command)
            incompatible_command[incompatible_command.index("s001-abstract-quartet")] = "s013-vesak"
            rejected = subprocess.run(
                incompatible_command,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("requires 3 source photographs", rejected.stderr)

    def test_init_job_preserves_original_assembly_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.jpg"
            Image.new("RGB", (32, 48), (80, 100, 120)).save(source)
            initialized = subprocess.run(
                [
                    sys.executable, str(SKILL_ROOT / "scripts" / "init_job.py"), str(source),
                    "--output-root", str(root / "jobs"), "--preset", "natural-cinematic",
                    "--creative-recipe", "s001-abstract-quartet", "--creative-assembly-mode", "original-assembly", "--confirmed",
                ], check=True, capture_output=True, text=True,
            )
            manifest = json.loads((Path(initialized.stdout.strip()) / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["creative_output"]["mode"], "original-assembly")
            self.assertTrue(manifest["creative_output"]["original_assembly"])
            self.assertIn("original assembled", manifest["detail"]["note"])

    def test_single_source_direct_effect_inherits_panel_aspect_ratio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.jpg"
            Image.new("RGB", (32, 48), (10, 20, 30)).save(source)
            base = [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "init_job.py"),
                str(source),
                "--output-root",
                str(root / "jobs"),
                "--preset",
                "natural-cinematic",
                "--creative-recipe",
                "s001-abstract-quartet",
                "--confirmed",
            ]
            direct = subprocess.run(
                base + ["--aspect-ratio", "16:9", "--framing", "contain"],
                check=True, capture_output=True, text=True,
            )
            manifest = json.loads((Path(direct.stdout.strip()) / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["creative_output"]["aspect_ratio_source"], "panel")
            self.assertEqual(manifest["creative_output"]["effective_aspect_ratio"], "16:9")
            self.assertEqual(manifest["creative_output"]["recipe_aspect_ratio"], "1:2")

            default_ratio = subprocess.run(base, check=True, capture_output=True, text=True)
            manifest = json.loads((Path(default_ratio.stdout.strip()) / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["creative_output"]["aspect_ratio_source"], "panel")
            self.assertEqual(manifest["creative_output"]["effective_aspect_ratio"], "original")

            assembly = subprocess.run(
                base + ["--creative-assembly-mode", "original-assembly"],
                check=True, capture_output=True, text=True,
            )
            manifest = json.loads((Path(assembly.stdout.strip()) / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["creative_output"]["aspect_ratio_source"], "recipe")
            self.assertEqual(manifest["creative_output"]["effective_aspect_ratio"], "1:2")

    def test_two_stage_creative_from_base_and_creative_brief(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.jpg"
            Image.new("RGB", (32, 48), (10, 20, 30)).save(source)
            base = [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "init_job.py"),
                str(source),
                "--output-root",
                str(root / "jobs"),
                "--preset",
                "natural-cinematic",
                "--creative-recipe",
                "s001-abstract-quartet",
                "--confirmed",
            ]

            single = subprocess.run(base, check=True, capture_output=True, text=True)
            job = Path(single.stdout.strip()) / "job.json"
            manifest = json.loads(job.read_text(encoding="utf-8"))
            self.assertEqual(manifest["creative_output"]["upstream_binding"], "direction-only")
            brief = json.loads(
                subprocess.run(
                    [sys.executable, str(SKILL_ROOT / "scripts" / "build_edit_prompt.py"), str(job)],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
            )
            self.assertIn("Starryear", brief["recipe_instruction"])
            self.assertIn("upstream look direction", brief["upstream_style_direction"])
            self.assertNotIn("Keep natural skin and material texture", brief["invariants"])
            self.assertNotIn("base_prompt", brief)
            self.assertEqual(brief["aspect_ratio"], "original")

            two_stage = subprocess.run(base + ["--creative-from-base"], check=True, capture_output=True, text=True)
            job = Path(two_stage.stdout.strip()) / "job.json"
            manifest = json.loads(job.read_text(encoding="utf-8"))
            self.assertEqual(manifest["creative_output"]["upstream_binding"], "look-master")
            brief = json.loads(
                subprocess.run(
                    [sys.executable, str(SKILL_ROOT / "scripts" / "build_edit_prompt.py"), str(job)],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
            )
            self.assertIn("Keep natural skin and material texture", brief["invariants"])
            self.assertIn("base_prompt", brief)
            self.assertTrue(any("stage 1" in item for item in brief["requested_adjustments"]))

            assembly = subprocess.run(
                base + ["--creative-assembly-mode", "original-assembly", "--creative-from-base"],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads((Path(assembly.stdout.strip()) / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["creative_output"]["upstream_binding"], "direction-only")

    def test_hd_creative_chain_states_and_gates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.jpg"
            Image.new("RGB", (32, 48), (10, 20, 30)).save(source)
            base = [sys.executable, str(SKILL_ROOT / "scripts" / "init_job.py"), str(source),
                    "--output-root", str(root / "jobs"), "--preset", "natural-cinematic",
                    "--creative-recipe", "s001-abstract-quartet", "--confirmed"]

            single = subprocess.run(base, check=True, capture_output=True, text=True)
            job = Path(single.stdout.strip()) / "job.json"
            m = json.loads(job.read_text(encoding="utf-8"))
            self.assertEqual(m["creative_output"]["upstream_binding"], "direction-only")
            self.assertFalse(m["creative_preview"]["required"])

            hd = subprocess.run(base + ["--creative-hd-chain", "--creative-upscale"], check=True, capture_output=True, text=True)
            job = Path(hd.stdout.strip()) / "job.json"
            m = json.loads(job.read_text(encoding="utf-8"))
            self.assertEqual(m["creative_output"]["upstream_binding"], "hd-master")
            self.assertTrue(m["creative_output"]["hd_chain"])
            self.assertTrue(m["creative_preview"]["required"])
            self.assertFalse(m["creative_preview"]["approved"])
            self.assertEqual(m["detail"]["mode"], "adaptive")
            # The HD chain prepares the photographic master once; the final
            # creative delivery is tiled redraw, so a separate creative upscale
            # pass is intentionally disabled.
            self.assertFalse(m["creative_output"]["upscale"]["enabled"])

            updater = [sys.executable, str(SKILL_ROOT / "scripts" / "update_job.py"), str(job)]
            subprocess.run(updater + ["--status", "prepared"], check=True, capture_output=True, text=True)
            subprocess.run(updater + ["--status", "base_generated"], check=True, capture_output=True, text=True)
            subprocess.run(updater + ["--approve-base-preview", "--artifact",
                                      f"base_preview={write_approved_preview(job)}"],
                         check=True, capture_output=True, text=True)
            subprocess.run(updater + ["--status", "details_processed"], check=True, capture_output=True, text=True)
            skipped = subprocess.run(updater + ["--status", "completed"], capture_output=True, text=True)
            self.assertNotEqual(skipped.returncode, 0)
            self.assertIn("must pass through creative_generated", skipped.stderr)
            subprocess.run(updater + ["--status", "creative_generated"], check=True, capture_output=True, text=True)
            unapproved = subprocess.run(updater + ["--status", "completed"], capture_output=True, text=True)
            self.assertNotEqual(unapproved.returncode, 0)
            self.assertIn("Approve the creative draft", unapproved.stderr)
            subprocess.run(updater + ["--approve-creative-preview", "--artifact",
                                      f"creative_preview={write_approved_preview(job, 'creative-draft.png')}"],
                         check=True, capture_output=True, text=True)
            pass_delivery_gate(job)
            subprocess.run(updater + ["--status", "completed"], check=True, capture_output=True, text=True)
            m = json.loads(job.read_text(encoding="utf-8"))
            self.assertEqual(m["status"], "completed")
            self.assertTrue(m["creative_preview"]["approved"])

            # The current contract rejects HD chaining for the original multi-panel
            # assembly; exercise that mode independently here.
            assembly = subprocess.run(
                base + ["--creative-assembly-mode", "original-assembly"],
                check=True, capture_output=True, text=True)
            m = json.loads((Path(assembly.stdout.strip()) / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(m["creative_output"]["upstream_binding"], "direction-only")

    def test_multi_photo_creative_recipe_uses_effect_preview_not_batch_master(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sources = []
            for index in range(3):
                source = root / f"source-{index}.jpg"
                Image.new("RGB", (32, 48), (80 + index, 100, 120)).save(source)
                sources.append(str(source))
            output = root / "jobs"
            initialized = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_ROOT / "scripts" / "init_job.py"),
                    *sources,
                    "--output-root",
                    str(output),
                    "--preset",
                    "natural-cinematic",
                    "--creative-recipe",
                    "s014-mix",
                    "--confirmed",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            job_path = Path(initialized.stdout.strip()) / "job.json"
            updater = [sys.executable, str(SKILL_ROOT / "scripts" / "update_job.py"), str(job_path)]
            subprocess.run(updater + ["--status", "prepared"], check=True, capture_output=True, text=True)
            subprocess.run(updater + ["--status", "base_generated"], check=True, capture_output=True, text=True)
            subprocess.run(updater + ["--approve-base-preview", "--artifact",
                                      f"base_preview={write_approved_preview(job_path, size=(24, 32))}"],
                         check=True, capture_output=True, text=True)
            pass_delivery_gate(job_path, size=(24, 32))
            subprocess.run(updater + ["--status", "completed"], check=True, capture_output=True, text=True)
            manifest = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["workflow"], "batch")
            self.assertIsNone(manifest["batch"]["master_frame_approved"])
            self.assertTrue(manifest["base_preview"]["approved"])
            self.assertEqual(manifest["status"], "completed")


    def test_upscale_image_fallback_is_honest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "small.png"
            Image.new("RGB", (100, 80), (30, 40, 50)).save(source)
            output = root / "big.png"
            result = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "scripts" / "upscale_image.py"),
                 "--input", str(source), "--output", str(output), "--scale", "4", "--engine", "fallback"],
                check=True, capture_output=True, text=True)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["engine"], "fallback-lanczos")
            self.assertTrue(payload["note"])
            self.assertEqual(Image.open(output).size, (400, 320))

    def test_register_blend_rejects_patch_aspect_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            import numpy as np
            from PIL import Image as PILImage
            rng = np.random.default_rng(7)
            base_arr = rng.integers(0, 255, (160, 200, 3), dtype=np.uint8)
            PILImage.fromarray(base_arr).save(root / "base.png")
            PILImage.fromarray(base_arr[10:90, 10:70]).save(root / "target.png")
            PILImage.fromarray(rng.integers(0, 255, (60, 60, 3), dtype=np.uint8)).save(root / "patch.png")
            result = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "scripts" / "register_blend.py"),
                 "--base", str(root / "base.png"), "--target", str(root / "target.png"),
                 "--patch", str(root / "patch.png"), "--output", str(root / "out.png"),
                 "--x", "10", "--y", "10", "--region-type", "generic"],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("deviates from target region aspect", result.stderr)

if __name__ == "__main__":
    unittest.main()
