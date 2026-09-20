import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from compile_graph_plan import compile_plan
from config_to_graph import convert_config
from validate_graph import validate_graph

CATALOG = {
    "recipes": [
        {"id":"s001-abstract-quartet","sourceCount":{"min":1,"max":1},"sourceCommit":"abc123","output":{"aspectRatio":"1:2"}},
        {"id":"s014-mix","sourceCount":{"min":3,"max":3},"sourceCommit":"mix123","output":{"aspectRatio":"2:3"}}
    ]
}

class NodeGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.catalog = Path(self.temp.name) / "catalog.json"
        self.catalog.write_text(json.dumps(CATALOG), encoding="utf-8")
    def tearDown(self):
        self.temp.cleanup()

    def test_plain_refinement_compiles_normal_recovery(self):
        graph = convert_config({"preset":"natural-cinematic","detail":{"mode":"adaptive","generationBudget":"balanced"}}, source_count=1, graph_id="plain", catalog_path=self.catalog)
        result = validate_graph(graph, self.catalog)
        self.assertEqual(result["flow"], ["source","look","approval","recovery","delivery"])
        plan = compile_plan(graph, self.catalog)
        self.assertEqual(plan["recoveryMode"], "normal")
        self.assertTrue(any(step["kind"] == "render-look" for step in plan["steps"]))

    def test_direct_effect_without_from_base_keeps_direction_only_semantics(self):
        config = {"preset":"natural-cinematic","creativeRecipe":"s001-abstract-quartet","creativeAssemblyMode":"direct-effect","creativeFromBase":False,"detail":{"mode":"adaptive","generationBudget":"balanced"}}
        graph = convert_config(config, source_count=1, graph_id="direct", catalog_path=self.catalog)
        look = next(node for node in graph["nodes"] if node["type"] == "look")
        self.assertEqual(look["config"]["renderMode"], "direction-only")
        recovery = next(node for node in graph["nodes"] if node["type"] == "recovery")
        self.assertEqual(recovery["config"]["mode"], "creative-safe")
        plan = compile_plan(graph, self.catalog)
        creative_step = next(step for step in plan["steps"] if step["kind"] == "render-creative-effect")
        self.assertEqual(creative_step["input"], "SOURCE_MASTER+LOOK_DIRECTION_A")

    def test_two_stage_creative_renders_look_a_first(self):
        config = {"creativeRecipe":"s001-abstract-quartet","creativeAssemblyMode":"direct-effect","creativeFromBase":True,"deliveryMode":"preview-first","detail":{"mode":"adaptive"}}
        graph = convert_config(config, source_count=1, graph_id="two-stage", catalog_path=self.catalog)
        plan = compile_plan(graph, self.catalog)
        kinds = [step["kind"] for step in plan["steps"]]
        self.assertEqual(kinds[:3], ["prepare-source","render-look","render-creative-effect"])
        self.assertEqual(plan["approvalCount"], 2)

    def test_original_assembly_disables_recovery(self):
        config = {"creativeRecipe":"s001-abstract-quartet","creativeAssemblyMode":"original-assembly","creativeFromBase":True,"detail":{"mode":"adaptive"}}
        graph = convert_config(config, source_count=1, graph_id="assembly", catalog_path=self.catalog)
        recovery = next(node for node in graph["nodes"] if node["type"] == "recovery")
        self.assertFalse(recovery["enabled"])
        validate_graph(graph, self.catalog)
        plan = compile_plan(graph, self.catalog)
        self.assertEqual(plan["recoveryMode"], "disabled")
        self.assertFalse(any(step["kind"] == "detail-recovery" for step in plan["steps"]))

    def test_multi_photo_direct_effect_disables_creative_safe_recovery(self):
        config = {"creativeRecipe":"s014-mix","creativeAssemblyMode":"direct-effect","detail":{"mode":"adaptive"}}
        graph = convert_config(config, source_count=3, graph_id="multi", catalog_path=self.catalog)
        recovery = next(node for node in graph["nodes"] if node["type"] == "recovery")
        self.assertFalse(recovery["enabled"])
        validate_graph(graph, self.catalog)

    def test_recipe_source_count_is_validated(self):
        with self.assertRaisesRegex(ValueError, "does not accept 1 source"):
            convert_config({"creativeRecipe":"s014-mix","creativeAssemblyMode":"direct-effect"}, source_count=1, graph_id="bad-count", catalog_path=self.catalog)

    def test_bypass_edge_is_rejected(self):
        graph = convert_config({}, source_count=1, graph_id="bypass", catalog_path=self.catalog)
        graph["edges"].append({"from":"source","to":"delivery","kind":"flow"})
        with self.assertRaisesRegex(ValueError, "continuous chain"):
            validate_graph(graph, self.catalog)

if __name__ == "__main__":
    unittest.main()
