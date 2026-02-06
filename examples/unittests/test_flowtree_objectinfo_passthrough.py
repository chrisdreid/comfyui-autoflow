#!/usr/bin/env python3
"""
Flowtree-mode tests ensuring ObjectInfo wrapper preserves `.source`
when passed into Flow/ApiFlow constructors.
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


class TestFlowtreeObjectInfoPassthrough(unittest.TestCase):
    def _run(self, code: str) -> list[str]:
        out = subprocess.check_output(
            [sys.executable, "-c", code],
            env=_env_with_repo_root({"AUTOFLOW_MODEL_LAYER": "flowtree"}),
            stderr=subprocess.STDOUT,
        )
        s = out.decode("utf-8", errors="replace").strip()
        return [] if not s else s.splitlines()

    def test_apiflow_accepts_flowtree_objectinfo_and_keeps_source(self):
        code = r"""
import os
from pathlib import Path
from autoflow import ApiFlow, ObjectInfo

td = Path(os.environ["AUTOFLOW_TESTDATA_DIR"])
api_path = td / "default-subgraphx2-api.json"
oi_path = td / "object_info.json"

oi = ObjectInfo.load(oi_path)
api = ApiFlow.load(api_path, object_info=oi)
print(api.object_info.source)
"""
        out = self._run(code)
        self.assertTrue(out[0].startswith("file:"), out[0])


if __name__ == "__main__":
    unittest.main()

