#!/usr/bin/env python3
"""Offline tests for Flow.execute() / ApiFlow.execute() (serverless in-process).

Run:
  python3 -m unittest examples.unittests.test_execute_stageA -v
"""

import sys
import unittest
from pathlib import Path

# Allow running this file directly without installing the package.
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root))

from autoflow import ApiFlow, Flow  # noqa: E402
import autoflow.inprocess as inprocess_mod  # noqa: E402
from examples.unittests._fixtures import fixture_path  # noqa: E402


class TestExecuteStageA(unittest.TestCase):
    def test_apiflow_execute_rejects_server_args(self):
        api = ApiFlow({}, node_info=None)
        with self.assertRaises(TypeError):
            api.execute(server_url="http://example.invalid")  # type: ignore[arg-type]

    def test_apiflow_execute_calls_inprocess_execute_prompt(self):
        api = ApiFlow({"1": {"class_type": "KSampler", "inputs": {"seed": 1}}}, node_info=None)
        calls = []

        def fake_execute_prompt(prompt, **kwargs):
            calls.append({"prompt": prompt, "kwargs": kwargs})
            return {"prompt_id": "p_execute", "history": {}}

        old = inprocess_mod.execute_prompt
        inprocess_mod.execute_prompt = fake_execute_prompt  # type: ignore[assignment]
        try:
            res = api.execute(client_id="cid", extra={"x": 1}, cleanup=False)
        finally:
            inprocess_mod.execute_prompt = old  # type: ignore[assignment]

        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("prompt_id"), "p_execute")
        self.assertTrue(calls)
        self.assertIn("1", calls[0]["prompt"])
        self.assertEqual(calls[0]["kwargs"].get("client_id"), "cid")
        self.assertEqual(calls[0]["kwargs"].get("extra"), {"x": 1})
        self.assertEqual(calls[0]["kwargs"].get("cleanup"), False)

    def test_flow_execute_converts_then_calls_inprocess_execute_prompt(self):
        f = Flow(fixture_path("FLOW.json"), node_info=None)
        calls = []

        def fake_execute_prompt(prompt, **kwargs):
            calls.append({"prompt": prompt, "kwargs": kwargs})
            return {"prompt_id": "p_execute", "history": {}}

        old = inprocess_mod.execute_prompt
        inprocess_mod.execute_prompt = fake_execute_prompt  # type: ignore[assignment]
        try:
            res = f.execute(node_info=fixture_path("node_info.json"), cleanup=True)
        finally:
            inprocess_mod.execute_prompt = old  # type: ignore[assignment]

        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("prompt_id"), "p_execute")
        self.assertTrue(calls)
        # Converted API prompt dict should be non-empty
        self.assertTrue(isinstance(calls[0]["prompt"], dict) and bool(calls[0]["prompt"]))


if __name__ == "__main__":
    unittest.main()


