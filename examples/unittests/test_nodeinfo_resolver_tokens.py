#!/usr/bin/env python3
"""
Tests for node_info resolution tokens and provenance metadata.

These tests are offline and patch network/module loaders.
"""

import unittest
import importlib
from pathlib import Path
from unittest.mock import patch

conv = importlib.import_module("autoflow.convert")
from autoflow.models import NodeInfo
from autoflow.origin import NodeInfoOrigin
from examples.unittests._fixtures import fixture_path


class TestNodeInfoResolverTokens(unittest.TestCase):
    def test_fetch_token_uses_server_url_and_sets_origin(self):
        calls = []

        def fake_fetch(server_url: str, timeout: int = 0):
            calls.append((server_url, timeout))
            return {"KSampler": {"display_name": "KSampler"}}

        with patch.object(conv, "fetch_node_info", fake_fetch):
            oi, use_api, origin = conv.resolve_node_info_with_origin(
                "fetch",
                server_url="http://example.invalid",
                timeout=12,
                allow_env=False,
                require_source=True,
            )

        self.assertTrue(use_api)
        self.assertIsInstance(oi, dict)
        self.assertEqual(calls, [("http://example.invalid", 12)])
        self.assertEqual(origin.resolved, "server")
        self.assertEqual(origin.effective_server_url, "http://example.invalid")

    def test_fetch_token_falls_back_to_modules_offline_when_patched(self):
        def fake_modules():
            return {"KSampler": {"display_name": "KSampler"}}

        root = Path("/tmp/ComfyUI").resolve()
        with (
            patch.object(conv, "node_info_from_comfyui_modules", fake_modules),
            patch.object(conv, "_detect_comfyui_root_from_imports", lambda: root),
        ):
            oi, use_api, origin = conv.resolve_node_info_with_origin(
                "fetch",
                server_url=None,
                timeout=1,
                allow_env=False,
                require_source=True,
            )

        self.assertTrue(use_api)
        self.assertIn("KSampler", oi or {})
        self.assertEqual(origin.resolved, "modules")
        self.assertEqual(origin.modules_root, str(root))

    def test_dict_subclass_objectinfo_is_preserved_by_resolver(self):
        oi_obj = NodeInfo.load(fixture_path("node_info.json"))
        oi, use_api, origin = conv.resolve_node_info_with_origin(
            oi_obj,
            server_url=None,
            timeout=1,
            allow_env=False,
            require_source=True,
        )
        self.assertTrue(use_api)
        self.assertIs(oi, oi_obj)  # should not be dict() copied
        self.assertIsNotNone(origin)

    def test_objectinfo_source_formats_modules_root(self):
        oi = NodeInfo({})
        setattr(
            oi,
            "_autoflow_origin",
            NodeInfoOrigin(requested="modules", resolved="modules", via_env=False, modules_root="/abs/ComfyUI"),
        )
        self.assertEqual(oi.source, "modules:/abs/ComfyUI")

        setattr(
            oi,
            "_autoflow_origin",
            NodeInfoOrigin(requested="modules", resolved="modules", via_env=True, modules_root="/abs/ComfyUI"),
        )
        self.assertEqual(oi.source, "env:modules:/abs/ComfyUI")


if __name__ == "__main__":
    unittest.main()

