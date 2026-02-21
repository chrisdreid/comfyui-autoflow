#!/usr/bin/env python3
"""
Legacy-layer tests for `.source` provenance strings.
"""

import unittest

from autoflow.models import Flow, ApiFlow, Workflow, NodeInfo
from examples.unittests._fixtures import fixture_path


class TestLegacySourceMetadata(unittest.TestCase):
    def test_flow_and_apiflow_source_for_file_loads(self):
        flow_path = fixture_path("FLOW.json")
        api_path = fixture_path("default-subgraphx2-api.json")
        oi_path = fixture_path("node_info.json")

        f = Flow.load(flow_path)
        self.assertTrue(isinstance(f.source, str) and f.source.startswith("file:"), f.source)

        a = ApiFlow.load(api_path)
        self.assertTrue(isinstance(a.source, str) and a.source.startswith("file:"), a.source)

        f2 = Flow(flow_path, node_info=oi_path)
        self.assertIsInstance(f2.node_info, NodeInfo)
        self.assertTrue(isinstance(f2.node_info.source, str) and f2.node_info.source.startswith("file:"), f2.node_info.source)

    def test_workflow_conversion_propagates_source(self):
        flow_path = fixture_path("FLOW.json")
        oi_path = fixture_path("node_info.json")

        api = Workflow(str(flow_path), node_info=oi_path)
        self.assertTrue(isinstance(api.source, str) and api.source.startswith("converted_from("), api.source)
        self.assertIsNotNone(api.node_info)
        self.assertTrue(isinstance(api.node_info.source, str) and api.node_info.source.startswith("file:"), api.node_info.source)


if __name__ == "__main__":
    unittest.main()

