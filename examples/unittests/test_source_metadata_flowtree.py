#!/usr/bin/env python3
"""
Flowtree-mode tests for `.source` provenance strings.

Subprocess-based because model layer selection happens at import time.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path


_repo_root = Path(__file__).resolve().parents[2]
_data_dir = None
try:
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


class TestFlowtreeSourceMetadata(unittest.TestCase):
    def _run(self, code: str) -> list[str]:
        out = subprocess.check_output(
            [sys.executable, "-c", code],
            env=_env_with_repo_root({"AUTOFLOW_MODEL_LAYER": "flowtree"}),
            stderr=subprocess.STDOUT,
        )
        s = out.decode("utf-8", errors="replace").strip()
        return [] if not s else s.splitlines()

    def test_flow_apiflow_and_objectinfo_sources(self):
        code = r"""
import os
from pathlib import Path
from autoflow import Flow, ApiFlow, Workflow

td = Path(os.environ["AUTOFLOW_TESTDATA_DIR"])
flow_path = td / "FLOW.json"
api_path = td / "default-subgraphx2-api.json"
oi_path = td / "node_info.json"

f = Flow.load(flow_path, node_info=oi_path)
print(f.source)
print(f.node_info.source)

a = ApiFlow.load(api_path, node_info=oi_path)
print(a.source)
print(a.node_info.source)

api = Workflow(str(flow_path), node_info=oi_path)
print(api.source)
print(api.node_info.source)
"""
        out = self._run(code)
        self.assertTrue(out[0].startswith("file:"), out[0])
        self.assertTrue(out[1].startswith("file:"), out[1])
        self.assertTrue(out[2].startswith("file:"), out[2])
        self.assertTrue(out[3].startswith("file:"), out[3])
        self.assertTrue(out[4].startswith("converted_from("), out[4])
        self.assertTrue(out[5].startswith("file:"), out[5])


if __name__ == "__main__":
    unittest.main()

