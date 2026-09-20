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

            hd = subprocess.run(base + ["--creative-hd-chain"], check=True, capture_output=True, text=True)
            job = Path(hd.stdout.strip()) / "job.json"
            m = json.loads(job.read_text(encoding="utf-8"))
            self.assertEqual(m["creative_output"]["upstream_binding"], "hd-master")
            self.assertTrue(m["creative_output"]["hd_chain"])
            self.assertTrue(m["creative_preview"]["required"])
            self.assertFalse(m["creative_preview"]["approved"])
            self.assertEqual(m["detail"]["mode"], "adaptive")

            updater = [sys.executable, str(SKILL_ROOT / "scripts" / "update_job.py"), str(job)]
            subprocess.run(updater + ["--status", "prepared"], check=True, capture_output=True, text=True)
            subprocess.run(updater + ["--status", "base_generated"], check=True, capture_output=True, text=True)
            subprocess.run(updater + ["--approve-base-preview"], check=True, capture_output=True, text=True)
            subprocess.run(updater + ["--status", "details_processed"], check=True, capture_output=True, text=True)
            skipped = subprocess.run(updater + ["--status", "completed"], capture_output=True, text=True)
            self.assertNotEqual(skipped.returncode, 0)
            self.assertIn("must pass through creative_generated", skipped.stderr)
            subprocess.run(updater + ["--status", "creative_generated"], check=True, capture_output=True, text=True)
            unapproved = subprocess.run(updater + ["--status", "completed"], capture_output=True, text=True)
            self.assertNotEqual(unapproved.returncode, 0)
            self.assertIn("Approve the creative draft", unapproved.stderr)
            subprocess.run(updater + ["--approve-creative-preview"], check=True, capture_output=True, text=True)
            subprocess.run(updater + ["--status", "completed"], check=True, capture_output=True, text=True)
            m = json.loads(job.read_text(encoding="utf-8"))
            self.assertEqual(m["status"], "completed")
            self.assertTrue(m["creative_preview"]["approved"])

            assembly = subprocess.run(
                base + ["--creative-assembly-mode", "original-assembly", "--creative-hd-chain"],
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
            subprocess.run(updater + ["--approve-base-preview"], check=True, capture_output=True, text=True)
            subprocess.run(updater + ["--status", "completed"], check=True, capture_output=True, text=True)
            manifest = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["workflow"], "batch")
            self.assertIsNone(manifest["batch"]["master_frame_approved"])
            self.assertTrue(manifest["base_preview"]["approved"])
            self.assertEqual(manifest["status"], "completed")


if __name__ == "__main__":
    unittest.main()
