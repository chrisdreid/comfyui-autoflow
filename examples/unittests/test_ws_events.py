#!/usr/bin/env python3
"""Offline tests for ComfyUI websocket message parsing.

No network calls.

Run:
  python3 -m unittest examples.unittests.test_ws_events -v
"""

import unittest
import sys
from pathlib import Path

# Allow running this file directly without installing the package.
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root))

from autoflow.ws import parse_comfy_event


class TestWsEventParsing(unittest.TestCase):
    def test_progress_message(self):
        raw = '{"type":"progress","data":{"value":3,"max":10,"node":null}}'
        events = parse_comfy_event(raw, client_id="c", prompt_id="p")
        self.assertTrue(any(e.get("type") == "progress" for e in events))
        ev = [e for e in events if e.get("type") == "progress"][0]
        self.assertEqual(ev.get("client_id"), "c")
        self.assertEqual(ev.get("prompt_id"), "p")
        self.assertEqual(ev.get("data", {}).get("value"), 3)

    def test_executing_completion(self):
        raw = '{"type":"executing","data":{"node":null}}'
        events = parse_comfy_event(raw)
        types = [e.get("type") for e in events]
        self.assertIn("completed", types)
        self.assertIn("executing", types)

    def test_multiple_json_objects_in_one_frame(self):
        raw = '{"type":"progress","data":{}}{"type":"executing","data":{"node":1}}'
        events = parse_comfy_event(raw)
        types = [e.get("type") for e in events]
        self.assertIn("progress", types)
        self.assertIn("executing", types)

    def test_bytes_input(self):
        raw = b'{"type":"executed","data":{"node":5,"output":{}}}'
        events = parse_comfy_event(raw)
        self.assertTrue(any(e.get("type") == "executed" for e in events))


if __name__ == "__main__":
    unittest.main()


