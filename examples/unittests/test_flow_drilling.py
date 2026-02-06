#!/usr/bin/env python3
"""Offline tests for schema-aware attribute drilling on Flow nodes.

Run:
  python3 -m unittest examples.unittests.test_flow_drilling -v
"""

import sys
import unittest
from pathlib import Path
import os

# Allow running this file directly without installing the package.
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root))

from autoflow import Flow, NodeInfoError  # noqa: E402
from examples.unittests._fixtures import fixture_path


class TestFlowSchemaAwareDrilling(unittest.TestCase):
    def test_seed_requires_object_info(self):
        f = Flow(fixture_path("FLOW.json"))
        with self.assertRaises(NodeInfoError):
            _ = f.nodes.KSampler[0].seed

    def test_seed_works_with_object_info(self):
        f = Flow(fixture_path("FLOW.json"), object_info=fixture_path("object_info.json"))
        self.assertEqual(f.nodes.KSampler[0].seed, 200)

    def test_attrs_lists_raw_keys_and_widgets(self):
        f = Flow(fixture_path("FLOW.json"), object_info=fixture_path("object_info.json"))
        a1 = f.nodes.KSampler[0].attrs()
        a2 = f.nodes.KSampler.attrs()
        # Raw node keys
        self.assertIn("id", a1)
        self.assertIn("type", a1)
        self.assertIn("widgets_values", a1)
        # Widget names (schema-derived)
        self.assertIn("seed", a1)
        self.assertIn("steps", a1)
        self.assertIn("seed", a2)

    def test_setting_widget_updates_convert(self):
        f = Flow(fixture_path("FLOW.json"), object_info=fixture_path("object_info.json"))
        # Modify via a proxy returned from find() (different proxy instance, same underlying node dict)
        n = f.nodes.find(type="KSampler")[0]
        n.seed = 123
        api = f.convert(object_info=fixture_path("object_info.json"))
        self.assertEqual(api.KSampler[0].seed, 123)

    def test_fetch_object_info_attaches_schema_offline(self):
        f = Flow(fixture_path("FLOW.json"))
        self.assertIsNone(getattr(f, "object_info", None))
        oi = f.fetch_object_info(fixture_path("object_info.json"))
        self.assertIsInstance(oi, dict)
        self.assertIsInstance(getattr(f, "object_info", None), dict)
        self.assertEqual(f.nodes.KSampler[0].seed, 200)

    def test_fetch_object_info_no_args_requires_env_or_server_url(self):
        f = Flow(fixture_path("FLOW.json"))
        old = os.environ.pop("AUTOFLOW_COMFYUI_SERVER_URL", None)
        try:
            with self.assertRaises(ValueError):
                f.fetch_object_info()
        finally:
            if old is not None:
                os.environ["AUTOFLOW_COMFYUI_SERVER_URL"] = old


if __name__ == "__main__":
    unittest.main()


