#!/usr/bin/env python3
"""Offline test for Flow.submit() wrapper (no real server calls).

Run:
  python3 -m unittest examples.unittests.test_flow_submit -v
"""

import sys
import unittest
from pathlib import Path

# Allow running this file directly without installing the package.
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root))

import autoflow.net as net_mod  # noqa: E402
from autoflow import Flow  # noqa: E402
from examples.unittests._fixtures import fixture_path


class TestFlowSubmitWrapper(unittest.TestCase):
    def test_flow_submit_converts_then_submits(self):
        f = Flow(fixture_path("FLOW.json"))

        calls = []

        def fake_http_json(url, payload=None, timeout=0, method="POST"):
            calls.append({"url": url, "payload": payload, "timeout": timeout, "method": method})
            if url.endswith("/prompt"):
                # Ensure no MarkdownNote made it into the API prompt (it isn't in object_info.json)
                prompt = payload.get("prompt") if isinstance(payload, dict) else None
                self.assertIsInstance(prompt, dict)
                class_types = [v.get("class_type") for v in prompt.values() if isinstance(v, dict)]
                self.assertNotIn("MarkdownNote", class_types)
                return {"prompt_id": "p1"}
            raise AssertionError(f"Unexpected URL in test: {url}")

        old = net_mod._http_json
        net_mod._http_json = fake_http_json
        try:
            sub = f.submit(
                server_url="http://example.invalid",
                object_info=fixture_path("object_info.json"),
                wait=False,
                fetch_outputs=False,
            )
        finally:
            net_mod._http_json = old

        self.assertIsInstance(sub, dict)
        self.assertTrue(calls)
        # When wait=False, SubmissionResult wraps the raw /prompt response.
        self.assertEqual(sub.get("prompt_id"), "p1")
        self.assertTrue(hasattr(sub, "fetch_files"))


if __name__ == "__main__":
    unittest.main()


