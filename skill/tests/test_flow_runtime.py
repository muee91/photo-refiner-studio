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
sys.path.insert(0, str(SCRIPTS))

from config_to_graph import convert_config

class FlowRuntimeTests(unittest.TestCase):
    def _write_graph_record(self, home: Path, graph: dict) -> Path:
        root = home / ".codex" / "photo-refiner-flow" / "graphs"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{graph['graphId']}.json"
        record = {
            "schemaVersion": 1,
            "graphId": graph["graphId"],
            "confirmedAt": "2026-09-20T00:00:00+00:00",
            "confirmedBy": "photo-refiner-flow-studio",
            "graph": graph,
        }
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _run_init(self, source: Path, graph_path: Path, home: Path, output: Path) -> dict:
        env = dict(os.environ)
        env["HOME"] = str(home)
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "init_job.py"),
                str(source),
                "--graph-file",
                str(graph_path),
                "--output-root",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        return json.loads((Path(result.stdout.strip()) / "job.json").read_text(encoding="utf-8"))

    def test_graph_path_initializes_independent_flow_job(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            source = root / "source.jpg"
            Image.new("RGB", (64, 96), (40, 60, 80)).save(source)
            graph = convert_config(
                {
                    "preset": "natural-cinematic",
                    "styleStrength": 47,
                    "deliveryMode": "preview-first",
                    "outputFormat": "jpg",
                    "detail": {"mode": "adaptive", "generationBudget": "balanced"},
                },
                source_count=1,
                graph_id="flow-a-only",
            )
            graph_path = self._write_graph_record(home, graph)
            manifest = self._run_init(source, graph_path, home, root / "jobs")
            self.assertEqual(manifest["product"], "photo-refiner-flow")
            self.assertEqual(manifest["release_version"], "3.0-flow")
            self.assertEqual(manifest["graph_confirmation"]["id"], "flow-a-only")
            self.assertEqual(manifest["graph_confirmation"]["confirmed_by"], "photo-refiner-flow-studio")
            self.assertEqual(manifest["detail"]["mode"], "adaptive")
            self.assertEqual(manifest["retouch"]["style_strength"], 47)
            self.assertEqual(manifest["retouch"]["source"], "flow-graph")
            self.assertEqual(manifest["flow"]["graph_id"], "flow-a-only")
            self.assertTrue(manifest["flow"]["steps"])
            self.assertTrue(all(step["state"] == "pending" for step in manifest["flow"]["steps"]))

    def test_single_source_direct_effect_enables_creative_safe_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            source = root / "source.jpg"
            Image.new("RGB", (64, 96), (100, 80, 60)).save(source)
            graph = convert_config(
                {
                    "preset": "natural-cinematic",
                    "styleStrength": 45,
                    "creativeRecipe": "s001-abstract-quartet",
                    "creativeAssemblyMode": "direct-effect",
                    "creativeFromBase": False,
                    "deliveryMode": "preview-first",
                    "detail": {"mode": "adaptive", "generationBudget": "balanced"},
                },
                source_count=1,
                graph_id="flow-ab-direct",
            )
            graph_path = self._write_graph_record(home, graph)
            manifest = self._run_init(source, graph_path, home, root / "jobs")
            self.assertEqual(manifest["execution_mode"], "creative-translation")
            self.assertEqual(manifest["creative_output"]["mode"], "direct-effect")
            self.assertEqual(manifest["creative_output"]["upstream_binding"], "direction-only")
            self.assertEqual(manifest["detail"]["mode"], "creative-safe")
            self.assertLessEqual(manifest["detail"]["hard_generated_patch_ceiling"], 3)
            self.assertFalse(manifest["detail"]["background_generation"])
            self.assertEqual(manifest["detail"]["look_authority"], "LOOK_AB")

    def test_original_assembly_disables_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            source = root / "source.jpg"
            Image.new("RGB", (64, 96), (100, 80, 60)).save(source)
            graph = convert_config(
                {
                    "creativeRecipe": "s001-abstract-quartet",
                    "creativeAssemblyMode": "original-assembly",
                    "creativeFromBase": False,
                    "detail": {"mode": "adaptive"},
                },
                source_count=1,
                graph_id="flow-original-assembly",
            )
            graph_path = self._write_graph_record(home, graph)
            manifest = self._run_init(source, graph_path, home, root / "jobs")
            self.assertEqual(manifest["creative_output"]["mode"], "original-assembly")
            self.assertEqual(manifest["detail"]["mode"], "not-applicable")
            self.assertEqual(manifest["detail"]["hard_generated_patch_ceiling"], 0)

    def test_flow_step_state_machine_tracks_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            source = root / "source.jpg"
            Image.new("RGB", (64, 96), (20, 30, 40)).save(source)
            graph = convert_config(
                {"detail": {"mode": "base-only"}, "deliveryMode": "one-click"},
                source_count=1,
                graph_id="flow-state-machine",
            )
            graph_path = self._write_graph_record(home, graph)
            env = dict(os.environ)
            env["HOME"] = str(home)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "init_job.py"),
                    str(source),
                    "--graph-file",
                    str(graph_path),
                    "--output-root",
                    str(root / "jobs"),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            job_path = Path(result.stdout.strip()) / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            first = job["flow"]["steps"][0]["id"]
            subprocess.run(
                [sys.executable, str(SCRIPTS / "update_flow_state.py"), str(job_path), "--step", first, "--state", "running"],
                check=True, capture_output=True, text=True, env=env,
            )
            subprocess.run(
                [sys.executable, str(SCRIPTS / "update_flow_state.py"), str(job_path), "--step", first, "--state", "completed"],
                check=True, capture_output=True, text=True, env=env,
            )
            job = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(job["flow"]["steps"][0]["state"], "completed")
            self.assertEqual(job["status"], "running")

if __name__ == "__main__":
    unittest.main()
