#!/usr/bin/env python3
"""Offline tests for find() + path()/address() helpers.

Run:
  python3 -m unittest examples.unittests.test_find_and_path -v
"""

import sys
import unittest
from pathlib import Path
import re

# Allow running this file directly without installing the package.
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root))

from autoflow import ApiFlow, Flow, NodeInfo
from examples.unittests._fixtures import fixture_path


class TestLoaderPathErrors(unittest.TestCase):
    def test_flow_missing_file_is_clear(self):
        with self.assertRaises(FileNotFoundError):
            Flow("this-file-should-not-exist.json")

    def test_api_missing_file_is_clear(self):
        with self.assertRaises(FileNotFoundError):
            ApiFlow("this-file-should-not-exist.json")


class TestFlowFindAndPath(unittest.TestCase):
    def test_find_title_including_subgraphs(self):
        f = Flow(fixture_path("default-subgraphx2-renamed.json"))
        matches = f.nodes.find(title="NewSubgraphName")
        self.assertTrue(matches)
        # Top-level subgraph instance id is 18 in this file.
        self.assertEqual(matches[0].path(), "18")

    def test_dict_drilling_on_flow_nodes(self):
        f = Flow(fixture_path("default.json"))
        # properties should be DictView-wrapped and support attr drilling
        self.assertEqual(
            f.nodes.CheckpointLoaderSimple.properties.models[0]["directory"],
            "checkpoints",
        )
        # single-item list-of-dicts should support ergonomic attr drilling
        self.assertTrue(hasattr(f.nodes.CheckpointLoaderSimple.properties.models, "url"))
        self.assertEqual(
            f.nodes.CheckpointLoaderSimple.properties.models.url,
            f.nodes.CheckpointLoaderSimple.properties.models[0].url,
        )

    def test_find_by_nested_list_key(self):
        # KSampler has inputs as a list of dicts; ensure find traverses lists.
        f = Flow(fixture_path("default.json"))
        matches = f.find(name="model", depth=8)
        self.assertTrue(matches)

    def test_find_by_widget_name_when_node_info_present(self):
        # Workspace nodes store widgets_values as list; with node_info attached, widget names become searchable.
        f = Flow(fixture_path("FLOW.json"), node_info=fixture_path("node_info.json"))
        matches = f.find(seed=200, depth=8)
        self.assertTrue(matches)

    def test_find_supports_regex_value(self):
        f = Flow(fixture_path("FLOW.json"), node_info=fixture_path("node_info.json"))
        matches = f.find(seed=re.compile(r"^200$"), depth=8)
        self.assertTrue(matches)

    def test_find_supports_regex_type(self):
        f = Flow(fixture_path("default.json"))
        matches = f.nodes.find(type=re.compile(r"^K.*", re.IGNORECASE))
        self.assertTrue(matches)


class TestApiFindAndPath(unittest.TestCase):
    def test_api_find_returns_proxy_with_path(self):
        api = ApiFlow(fixture_path("default-subgraphx2-api.json"))
        matches = api.find(class_type="KSampler")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].path(), "18:17:3")
        # attrs() should include both raw node keys and input keys
        a = matches[0].attrs()
        self.assertIn("inputs", a)
        self.assertIn("seed", a)


class TestNodeInfoFind(unittest.TestCase):
    def test_node_info_find(self):
        oi = NodeInfo.load(fixture_path("node_info.json"))
        out = oi.find(class_type="KSampler")
        self.assertTrue(out)
        self.assertEqual(out[0].path(), "KSampler")


if __name__ == "__main__":
    unittest.main()


