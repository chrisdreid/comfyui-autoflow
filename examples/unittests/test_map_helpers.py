#!/usr/bin/env python3
"""Offline tests for autoflow mapping helpers.

Run:
  python3 -m unittest examples.unittests.test_map_helpers -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Allow running this file directly without installing the package.
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root))

from autoflow import ApiFlow, Flow, Workflow
from autoflow.map import api_mapping, map_strings, map_paths, force_recompute


class TestMapStrings(unittest.TestCase):
    def test_env_expansion_in_rules_and_replacements(self):
        os.environ["AUTOFLOW_TEST_NODE"] = "LoadImage"
        os.environ["AUTOFLOW_TEST_PARAM"] = "image"

        flow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "${ROOT}/a.png", "other": "nope"}},
            "2": {"class_type": "Other", "inputs": {"image": "${ROOT}/b.png"}},
        }

        spec = {
            "replacements": {"literal": {"${ROOT}": "/data"}},
            "rules": {
                "mode": "and",
                "node": {"regex": "${AUTOFLOW_TEST_NODE}"},
                "param": {"regex": "${AUTOFLOW_TEST_PARAM}"},
            },
        }

        out = map_strings(flow, spec)
        self.assertEqual(out["1"]["inputs"]["image"], "/data/a.png")
        self.assertEqual(out["1"]["inputs"]["other"], "nope")
        # node 2 shouldn't match node rule
        self.assertEqual(out["2"]["inputs"]["image"], "${ROOT}/b.png")

    def test_rule_regex_from_file_path(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "node_regex.txt"
            p.write_text(r"LoadImage", encoding="utf-8")

            flow = {
                "1": {"class_type": "LoadImage", "inputs": {"image": "X"}},
                "2": {"class_type": "SaveImage", "inputs": {"image": "X"}},
            }
            spec = {
                "replacements": {"literal": {"X": "Y"}},
                "rules": {"node": {"regex": str(p)}},
            }
            out = map_strings(flow, spec)
            self.assertEqual(out["1"]["inputs"]["image"], "Y")
            self.assertEqual(out["2"]["inputs"]["image"], "X")

    def test_literal_and_regex(self):
        flow = {"1": {"class_type": "X", "inputs": {"text": "${A} {B}"}}}
        spec = {
            "replacements": {
                "literal": {"${A}": "hello"},
                "regex": [{"pattern": r"\{B\}", "replace": "world"}],
            }
        }
        out = map_strings(flow, spec)
        self.assertEqual(out["1"]["inputs"]["text"], "hello world")


class TestMapPaths(unittest.TestCase):
    def test_default_param_filter(self):
        flow = {
            "1": {"class_type": "X", "inputs": {"image": "${ROOT}/a.png", "prompt": "${ROOT}"}},
        }
        spec = {"replacements": {"literal": {"${ROOT}": "/data"}}}
        out = map_paths(flow, spec)
        # image should be replaced (path-like key)
        self.assertEqual(out["1"]["inputs"]["image"], "/data/a.png")
        # prompt should likely not be replaced by default
        self.assertEqual(out["1"]["inputs"]["prompt"], "${ROOT}")


class TestCacheBuster(unittest.TestCase):
    def test_force_recompute_opt_in_defaults(self):
        flow = {
            "1": {"class_type": "KSampler", "inputs": {}},
            "2": {"class_type": "NotInList", "inputs": {}},
        }
        out = force_recompute(flow, use_defaults=True)
        self.assertIn("_autoflow_force_recompute_", out["1"]["inputs"])
        self.assertNotIn("_autoflow_force_recompute_", out["2"]["inputs"])


class TestConvertMappingAndApiMapping(unittest.TestCase):
    def test_convert_mapping_transfers_workflow_meta(self):
        workflow = {
            "nodes": [
                {
                    "id": 1,
                    "type": "TestNode",
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": [42],
                }
            ],
            "links": [],
            "last_node_id": 1,
            "last_link_id": 0,
            "extra": {"meta": {"show": "SHOW_A"}},
        }
        node_info = {
            "TestNode": {
                "input": {
                    "required": {
                        "seed": ["INT", {"default": 0}],
                    }
                }
            }
        }

        wf = Flow.load(workflow)
        api = wf.convert(node_info=node_info)
        self.assertIsInstance(api.workflow_meta, dict)
        self.assertEqual(api.workflow_meta["meta"]["show"], "SHOW_A")
        self.assertIsInstance(api, ApiFlow)

    def test_api_mapping_callback_typed_overwrite_and_link_context(self):
        node_info = {
            "A": {"input": {"required": {"x": ["INT", {"default": 0}]}}},
            "B": {"input": {"required": {"img": ["IMAGE"]}}},
        }
        flow = ApiFlow(
            {
                "1": {"class_type": "A", "inputs": {"x": 1}},
                "2": {"class_type": "B", "inputs": {"img": ["1", 0]}},
            },
            node_info=node_info,
            use_api=True,
            workflow_meta={"meta": {"show": "SHOW_A"}},
        )

        def cb(ctx):
            # Typed overwrite.
            if ctx["class_type"] == "A" and ctx["param_type"] == "INT":
                return 123
            # Link context + meta write.
            if ctx["class_type"] == "B" and ctx["param"] == "img":
                self.assertEqual(ctx["upstream_node_id"], "1")
                self.assertIsInstance(ctx["upstream_node"], dict)
                # workflow extra should be accessible for apps/pipelines (when attached)
                self.assertIsInstance(ctx.get("workflow_extra"), dict)
                return {"meta": {"linked_from": ctx["upstream_node_id"]}}
            return None

        out = api_mapping(flow, cb)
        self.assertEqual(out["1"]["inputs"]["x"], 123)
        self.assertEqual(out["2"]["inputs"]["img"], ["1", 0])
        self.assertEqual(out["2"]["_meta"]["meta"]["linked_from"], "1")

    def test_convert_apply_autoflow_meta_merge_add_replace(self):
        workflow = {
            "nodes": [
                {"id": 1, "type": "TestNode", "inputs": [], "outputs": [], "widgets_values": [200]},
            ],
            "links": [],
            "last_node_id": 1,
            "last_link_id": 0,
            "extra": {
                # Also support generic extra.meta.nodes patching
                "meta": {
                    "nodes": {
                        "1": {
                            "properties": {"from": "extra.meta.nodes"},
                        }
                    }
                },
                "autoflow": {
                    "meta": {
                        "nodes": {
                            # default mode: merge
                            "1": {
                                "inputs": {"seed": 123, "new_key": 9},
                                "properties": {"cnr_id": "comfy-core", "meta": {"hello": "world"}},
                            }
                        }
                    }
                }
            },
        }
        node_info = {
            "TestNode": {"input": {"required": {"seed": ["INT", {"default": 0}]}}},
        }

        api = Flow.load(workflow).convert(node_info=node_info)
        # merge overwrites existing input and adds new keys
        self.assertEqual(api["1"]["inputs"]["seed"], 123)
        self.assertEqual(api["1"]["inputs"]["new_key"], 9)
        # merge adds arbitrary non-standard keys at node root (power feature)
        self.assertEqual(api["1"]["properties"]["cnr_id"], "comfy-core")
        self.assertEqual(api["1"]["properties"]["meta"]["hello"], "world")
        # extra.meta.nodes applies too (and autoflow can override keys if needed)
        self.assertEqual(api["1"]["properties"]["from"], "extra.meta.nodes")

        # add-only: should not overwrite existing seed
        workflow["extra"]["autoflow"]["meta"]["nodes"]["1"] = {"mode": "add", "data": {"inputs": {"seed": 555}}}
        api2 = Flow.load(workflow).convert(node_info=node_info)
        self.assertEqual(api2["1"]["inputs"]["seed"], 200)

        # replace: replace entire node dict
        workflow["extra"]["autoflow"]["meta"]["nodes"]["1"] = {
            "mode": "replace",
            "data": {"class_type": "Replaced", "inputs": {"x": [1, 2, 3]}},
        }
        api3 = Flow.load(workflow).convert(node_info=node_info)
        self.assertEqual(api3["1"]["class_type"], "Replaced")
        self.assertEqual(api3["1"]["inputs"]["x"], [1, 2, 3])

    def test_convert_apply_autoflow_meta_prefix_ops(self):
        workflow = {
            "nodes": [
                {"id": 1, "type": "TestNode", "inputs": [], "outputs": [], "widgets_values": [200]},
            ],
            "links": [],
            "last_node_id": 1,
            "last_link_id": 0,
            "extra": {
                "autoflow": {
                    "meta": {
                        "nodes": {
                            "1": {
                                # add-only key: do not overwrite existing seed
                                "+inputs": {"seed": 999, "added": 1},
                                # force overwrite for one key
                                "*inputs": {"seed": 123},
                                # delete keys
                                "-gone": True,
                                "!gone2": True,
                            }
                        }
                    }
                }
            },
        }
        node_info = {
            "TestNode": {"input": {"required": {"seed": ["INT", {"default": 0}]}}},
        }

        api = Flow.load(workflow).convert(node_info=node_info)
        # *inputs overwrote seed
        self.assertEqual(api["1"]["inputs"]["seed"], 123)
        # +inputs added new key
        self.assertEqual(api["1"]["inputs"]["added"], 1)
        # deletes are no-ops if key not present (should not raise)
        self.assertNotIn("gone", api["1"])
        self.assertNotIn("gone2", api["1"])

    def test_convert_with_errors_warns_on_missing_patch_node(self):
        from autoflow.convert import convert_workflow_with_errors

        workflow = {
            "nodes": [
                {"id": 1, "type": "TestNode", "inputs": [], "outputs": [], "widgets_values": [42]},
            ],
            "links": [],
            "last_node_id": 1,
            "last_link_id": 0,
            "extra": {"autoflow": {"meta": {"nodes": {"999": {"inputs": {"seed": 1}}}}}},
        }
        node_info = {
            "TestNode": {"input": {"required": {"seed": ["INT", {"default": 0}]}}},
        }
        r = convert_workflow_with_errors(workflow, node_info=node_info)
        self.assertTrue(any("999" in w.message for w in (r.warnings or [])))

        # Opt-out should disable patch warnings too.
        r2 = convert_workflow_with_errors(workflow, node_info=node_info, disable_autoflow_meta=True)
        self.assertFalse(any("999" in w.message for w in (r2.warnings or [])))

    def test_strict_api_load_rejects_workspace(self):
        workflow = {"nodes": [], "links": []}
        with self.assertRaises(ValueError):
            ApiFlow.load(workflow)

    def test_workflow_wrapper_converts_both(self):
        workflow = {"nodes": [], "links": [], "last_node_id": 0, "last_link_id": 0, "extra": {"meta": {"show": "SHOW_A"}}}
        w = Workflow(workflow, auto_convert=False)
        r = Flow.load(workflow).convert_with_errors()
        self.assertFalse(r.ok)

        # Workflow with auto_convert=False returns a Flow, so conversion is manual.
        self.assertIsInstance(w, Flow)

    def test_constructors_accept_load_inputs(self):
        # Flow first-arg strict load
        wf = {
            "nodes": [],
            "links": [],
            "last_node_id": 1,
            "last_link_id": 2,
            "extra": {"meta": {"show": "SHOW_A"}},
        }
        f = Flow(wf)
        self.assertIsInstance(f.workflow_meta, dict)
        self.assertEqual(f.workflow_meta["meta"]["show"], "SHOW_A")

        # ApiFlow first-arg strict load
        api = {"1": {"class_type": "A", "inputs": {"x": 1}}}
        a = ApiFlow(api)
        self.assertEqual(a["1"]["inputs"]["x"], 1)

        # Workflow first-arg load + detect
        w = Workflow(wf, auto_convert=False)
        self.assertIsInstance(w, Flow)


if __name__ == "__main__":
    unittest.main()


