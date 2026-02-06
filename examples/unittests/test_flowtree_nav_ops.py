#!/usr/bin/env python3
"""
Internal tests for flowtree navigation ops (AUTOFLOW_MODEL_LAYER=flowtree).
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path


_repo_root = Path(__file__).resolve().parents[2]
_data_dir = None
try:
    # Reuse the same fixture resolution as other tests.
    from examples.unittests._fixtures import fixture_dir  # type: ignore

    _data_dir = fixture_dir()
except Exception:
    _data_dir = None


def _env_with_repo_root(extra: dict) -> dict:
    env = dict(os.environ)
    pp = env.get("PYTHONPATH", "")
    parts = [p for p in pp.split(os.pathsep) if p]
    if str(_repo_root) not in parts:
        parts.insert(0, str(_repo_root))
    env["PYTHONPATH"] = os.pathsep.join(parts)
    if _data_dir is not None:
        env.setdefault("AUTOFLOW_TESTDATA_DIR", str(_data_dir))
    env.update(extra)
    return env


class TestFlowtreeNavOps(unittest.TestCase):
    def _run(self, code: str) -> str:
        out = subprocess.check_output(
            [sys.executable, "-c", code],
            env=_env_with_repo_root({"AUTOFLOW_MODEL_LAYER": "flowtree"}),
            stderr=subprocess.STDOUT,
        )
        return out.decode("utf-8", errors="replace").strip()

    def test_nodeset_bulk_vs_single_assignment(self):
        code = r"""
from autoflow import ApiFlow

api = ApiFlow({
  "1": {"class_type": "KSampler", "inputs": {"cfg": 1}},
  "2": {"class_type": "KSampler", "inputs": {"cfg": 9}},
})
ks = api.KSampler
ks.cfg = 7
print(api["1"]["inputs"]["cfg"], api["2"]["inputs"]["cfg"])
ks.set(cfg=5)
print(api["1"]["inputs"]["cfg"], api["2"]["inputs"]["cfg"])
"""
        out = self._run(code).splitlines()
        self.assertEqual(out[0].strip(), "7 9")
        self.assertEqual(out[1].strip(), "5 5")

    def test_paths_and_dictpaths_exist(self):
        code = r"""
from autoflow import ApiFlow
api = ApiFlow({
  "18:17:3": {"class_type": "KSampler", "inputs": {"seed": 1}},
  "4": {"class_type": "KSampler", "inputs": {"seed": 2}},
})
ks = api.KSampler
print(ks.paths())
print(ks.dictpaths())
"""
        out = self._run(code).splitlines()
        self.assertTrue(out[0].startswith("["))
        self.assertIn("KSampler[0]", out[0])
        self.assertIn("KSampler[1]", out[0])
        self.assertIn("'18:17:3'", out[1])

    def test_autocomplete_dir_lists_node_types(self):
        code = r"""
import os
from autoflow import Flow
from pathlib import Path
td = Path(os.environ["AUTOFLOW_TESTDATA_DIR"])
f = Flow.load(str(td / "FLOW.json"))
print("KSampler" in dir(f.nodes))
"""
        out = self._run(code).strip()
        self.assertEqual(out, "True")

    def test_find_returns_nodeset(self):
        code = r"""
import os
from autoflow import Flow
import re
from pathlib import Path
td = Path(os.environ["AUTOFLOW_TESTDATA_DIR"])
f = Flow.load(str(td / "FLOW.json"), object_info=str(td / "object_info.json"))
hits = f.nodes.find(type="KSampler")
print(type(hits).__name__)
print(bool(hits.paths()))
"""
        out = self._run(code).splitlines()
        self.assertEqual(out[0].strip(), "NodeSet")
        self.assertEqual(out[1].strip(), "True")

    def test_submit_wrapper_uses_same_network_plumbing(self):
        code = r"""
import os
from pathlib import Path
import autoflow.net as net_mod
from autoflow import Flow

td = Path(os.environ["AUTOFLOW_TESTDATA_DIR"])
f = Flow(td / "FLOW.json")

calls = []
def fake_http_json(url, payload=None, timeout=0, method="POST"):
    calls.append((url, method))
    if url.endswith("/prompt"):
        return {"prompt_id": "p1"}
    raise AssertionError("Unexpected URL: " + str(url))

old = net_mod._http_json
net_mod._http_json = fake_http_json
try:
    sub = f.submit(
        server_url="http://example.invalid",
        object_info=td / "object_info.json",
        wait=False,
        fetch_outputs=False,
    )
finally:
    net_mod._http_json = old

print(isinstance(sub, dict), bool(calls), sub.get("prompt_id"), hasattr(sub, "fetch_files"))
"""
        out = self._run(code).strip()
        self.assertEqual(out, "True True p1 True")


if __name__ == "__main__":
    unittest.main()


