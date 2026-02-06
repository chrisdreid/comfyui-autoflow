#!/usr/bin/env python3
"""Offline tests for DAG building (Flow + ApiFlow).

No network calls.

Run:
  python3 -m unittest examples.unittests.test_dag -v
"""

import sys
import unittest
from pathlib import Path

# Allow running this file directly without installing the package.
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root))

from autoflow import ApiFlow, Flow  # noqa: E402


class TestApiDag(unittest.TestCase):
    def test_api_dag_edges(self):
        api = ApiFlow(
            {
                "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "x.safetensors"}},
                "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
                "3": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "latent_image": ["5", 0], "steps": 10}},
                "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            }
        )
        d = api.dag
        self.assertEqual(d.cls, "ApiFlow")
        self.assertIn(("4", "3"), d.edges)
        self.assertIn(("5", "3"), d.edges)
        self.assertIn(("3", "8"), d.edges)
        self.assertIn(("4", "8"), d.edges)

        self.assertEqual(d.deps("3"), ["4", "5"])
        self.assertEqual(d.ancestors("8"), ["4", "5", "3"])

        dot = d.to_dot(label="class_type")
        self.assertIn("digraph comfyui", dot)
        mm = d.to_mermaid()  # default shows "id: class_type"
        self.assertIn("flowchart", mm)
        self.assertIn('["3: KSampler"]', mm)
        mm2 = d.to_mermaid(label="{id} - {class_type}")
        self.assertIn('["3 - KSampler"]', mm2)
        mm3 = d.to_mermaid(label="id")
        self.assertIn('["3"]', mm3)

        # toposort() returns a Dag-like object with render helpers.
        mm4 = d.toposort().to_mermaid()
        self.assertIn("flowchart", mm4)
        # toposort() should change ordering; ensure node declarations are present
        self.assertIn('n_4["4: CheckpointLoaderSimple"]', mm4)


class TestFlowDag(unittest.TestCase):
    def test_flow_dag_edges(self):
        flow = Flow(
            {
                "nodes": [
                    {"id": 4, "type": "CheckpointLoaderSimple", "title": "Loader"},
                    {"id": 5, "type": "EmptyLatentImage", "title": "Latent"},
                    {"id": 3, "type": "KSampler", "title": "Sampler"},
                ],
                "links": [
                    [1, 4, 0, 3, 0, "MODEL"],
                    [2, 5, 0, 3, 1, "LATENT"],
                ],
                "last_node_id": 5,
                "last_link_id": 2,
            }
        )
        d = flow.dag
        self.assertEqual(d.cls, "Flow")
        self.assertIn(("4", "3"), d.edges)
        self.assertIn(("5", "3"), d.edges)
        self.assertEqual(d.deps("3"), ["4", "5"])

    def test_flow_dag_filters_by_object_info(self):
        flow = Flow(
            {
                "nodes": [
                    {"id": 4, "type": "CheckpointLoaderSimple", "title": "Loader"},
                    {"id": 15, "type": "MarkdownNote", "title": "Note: Prompt"},
                    {"id": 3, "type": "KSampler", "title": "Sampler"},
                ],
                "links": [
                    [1, 4, 0, 3, 0, "MODEL"],
                ],
                "last_node_id": 15,
                "last_link_id": 1,
            },
            object_info={"CheckpointLoaderSimple": {}, "KSampler": {}},
        )
        d = flow.dag
        self.assertEqual(d.cls, "Flow")
        self.assertIn("4", d.nodes)
        self.assertIn("3", d.nodes)
        self.assertNotIn("15", d.nodes)  # MarkdownNote excluded by object_info
        self.assertIn(("4", "3"), d.edges)


if __name__ == "__main__":
    unittest.main()


