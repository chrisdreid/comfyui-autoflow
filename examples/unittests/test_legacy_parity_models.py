#!/usr/bin/env python3
"""
Parity tests to lock in legacy model ergonomics.

These tests encode behaviors that existed in the legacy monolith implementation and are expected
to remain stable even after internal refactors/splits.
"""

import sys
import unittest
from pathlib import Path
import re

# Allow running this file directly without installing the package.
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root))

# These parity checks are specifically for the legacy-parity dict-subclass layer.
from autoflow.models import Flow, ApiFlow, ObjectInfo, Workflow  # noqa: E402
from examples.unittests._fixtures import fixture_path


class TestLegacyParityModels(unittest.TestCase):
    def test_dict_subclass_identity(self):
        f = Flow.load(fixture_path("FLOW.json"))
        a = ApiFlow.load(fixture_path("default-subgraphx2-api.json"))
        oi = ObjectInfo.load(fixture_path("object_info.json"))

        self.assertIsInstance(f, dict)
        self.assertIsInstance(a, dict)
        self.assertIsInstance(oi, dict)

    def test_flow_nodes_view_repr_and_dir(self):
        f = Flow.load(fixture_path("FLOW.json"))
        r = repr(f.nodes)
        self.assertIn("FlowNodesView", r)

        # dir(flow.nodes) should include available node types for discoverability.
        node_types = sorted({n.get("type") for n in f.get("nodes", []) if isinstance(n, dict) and isinstance(n.get("type"), str)})
        d = dir(f.nodes)
        for t in node_types:
            self.assertIn(t, d)

    def test_flow_node_proxy_widget_drilling_and_dir(self):
        f = Flow(fixture_path("FLOW.json"), object_info=fixture_path("object_info.json"))
        n = f.nodes.KSampler[0]
        self.assertEqual(n.seed, 200)
        self.assertIn("seed", n.attrs())
        self.assertIn("seed", dir(n))

    def test_flow_nodes_find_star_means_key_exists(self):
        f = Flow.load(fixture_path("FLOW.json"))
        all_nodes = [n for n in f.get("nodes", []) if isinstance(n, dict)]

        # "id='*'" is an existence query via **attrs (not the node_id= filter).
        matches = f.nodes.find(id="*")
        self.assertEqual(len(matches), len(all_nodes))

        # Regex should also work as expected.
        matches2 = f.nodes.find(id=re.compile(r".*"))
        self.assertEqual(len(matches2), len(all_nodes))

    def test_apiflow_path_get_set(self):
        api = Workflow(str(fixture_path("FLOW.json")), object_info=fixture_path("object_info.json"))
        self.assertIsInstance(api, ApiFlow)

        # By class_type selector (first matching node).
        api["ksampler/seed"] = 123
        self.assertEqual(api.ksampler[0].seed, 123)

        # By explicit index selector.
        api["ksampler/0/seed"] = 321
        self.assertEqual(api.ksampler[0].seed, 321)

        # By node id selector.
        node_id = api.find(class_type="KSampler")[0].id
        api[f"{node_id}/seed"] = 111
        self.assertEqual(api.ksampler[0].seed, 111)

    def test_objectinfo_attr_and_path_drilling(self):
        oi = ObjectInfo.load(fixture_path("object_info.json"))
        # attribute access should drill into dicts
        self.assertIn("input", oi.KSampler)
        # path access should work too
        seed_spec = oi["KSampler/input/required/seed"]
        self.assertTrue(seed_spec)


if __name__ == "__main__":
    unittest.main()


