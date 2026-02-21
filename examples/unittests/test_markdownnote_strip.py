#!/usr/bin/env python3
"""Offline tests for stripping UI-only nodes like MarkdownNote.

Run:
  python3 -m unittest examples.unittests.test_markdownnote_strip -v
"""

import sys
import unittest
from pathlib import Path

# Allow running this file directly without installing the package.
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root))

from autoflow.api import ApiFlow, convert_workflow, _sanitize_api_prompt  # noqa: E402
from examples.unittests._fixtures import fixture_path


class TestMarkdownNoteStripping(unittest.TestCase):
    def test_submit_sanitizer_drops_unknown_nodes_when_node_info_present(self):
        prompt = {
            "1": {"class_type": "TotallyFakeNode", "inputs": {}},
            "2": {"class_type": "KSampler", "inputs": {}},
        }
        node_info = {"KSampler": {"input": {}}}
        out = _sanitize_api_prompt(prompt, node_info=node_info)
        self.assertIn("2", out)
        self.assertNotIn("1", out)

    def test_convert_workflow_skips_markdownnote(self):
        # FLOW.json contains MarkdownNote workspace nodes; conversion should not emit them in API payload.
        wf = convert_workflow(
            fixture_path("FLOW.json"),
            node_info=fixture_path("node_info.json"),
            server_url=None,
        )
        class_types = [n.get("class_type") for n in wf.values() if isinstance(n, dict)]
        self.assertNotIn("MarkdownNote", class_types)


if __name__ == "__main__":
    unittest.main()


