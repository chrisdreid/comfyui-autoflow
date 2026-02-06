#!/usr/bin/env python3
"""Offline test ensuring submit(wait=True, on_event=...) emits a terminal event.

Simulates a websocket stream that yields `submitted` then dies, and a history poll that
immediately reports completed (common for cached runs).
"""

import sys
import unittest
from pathlib import Path

# Allow running this file directly without installing the package.
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root))

import autoflow.net as net_mod  # noqa: E402
import autoflow.ws as ws_mod  # noqa: E402
from autoflow import ApiFlow  # noqa: E402


class TestSubmitTerminalEvent(unittest.TestCase):
    def test_submit_emits_completed_when_ws_is_silent(self):
        events = []

        def on_event(ev):
            events.append(ev)

        def fake_http_json(url, payload=None, timeout=0, method="POST"):
            if url.endswith("/prompt"):
                return {"prompt_id": "p1"}
            if url.endswith("/history/p1") and method == "GET":
                return {
                    "p1": {
                        "status": {
                            "completed": True,
                            "messages": [
                                ["execution_cached", {"nodes": ["1", "2"]}],
                            ],
                        },
                        "outputs": {"2": {"images": [{"filename": "x.png", "subfolder": "", "type": "output"}]}},
                        "meta": {"2": {"node_id": "2"}},
                        "prompt": [1, "p1", {"1": {}, "2": {}}, {"client_id": "autoflow"}, ["2"]],
                    }
                }
            if url.endswith("/queue") and method == "GET":
                return {"queue_running": [], "queue_pending": []}
            raise AssertionError(f"Unexpected URL in test: {url} ({method})")

        def fake_stream_comfy_events(*args, **kwargs):
            # Yield submitted (as real stream does) then become silent (no further yields).
            # results.py should probe /history after ~1s of inactivity and emit completed.
            yield ws_mod.WsEvent(type="submitted", data={}, ts=1.0, client_id="autoflow", prompt_id="p1", raw={})
            return

        old_http = net_mod._http_json
        old_stream = ws_mod.stream_comfy_events
        net_mod._http_json = fake_http_json
        ws_mod.stream_comfy_events = fake_stream_comfy_events
        try:
            api = ApiFlow(
                {
                    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
                    "2": {"class_type": "KSampler", "inputs": {"model": ["1", 0]}},
                }
            )
            api.submit(
                server_url="http://example.invalid",
                wait=True,
                fetch_outputs=False,
                poll_interval=0.01,
                wait_timeout=1,
                on_event=on_event,
            )
        finally:
            net_mod._http_json = old_http
            ws_mod.stream_comfy_events = old_stream

        types = [e.get("type") for e in events if isinstance(e, dict)]
        self.assertIn("submitted", types)
        self.assertIn("completed", types)
        completed = [e for e in events if isinstance(e, dict) and e.get("type") == "completed"]
        self.assertTrue(completed)
        ev = completed[-1]
        self.assertEqual(ev.get("detected_by"), "history")
        self.assertIsInstance(ev.get("data"), dict)
        self.assertTrue(isinstance(ev["data"].get("status"), dict) and ev["data"]["status"].get("completed") is True)
        self.assertIn("outputs", ev["data"])


if __name__ == "__main__":
    unittest.main()


