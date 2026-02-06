#!/usr/bin/env python3
"""
Flowtree-mode tests for ObjectInfo constructor and fetch ergonomics.

These are subprocess-based to ensure AUTOFLOW_MODEL_LAYER=flowtree is honored,
since model layer selection happens at import time.
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


class TestFlowtreeObjectInfoInit(unittest.TestCase):
    def _run(self, code: str, extra_env: dict | None = None) -> list[str]:
        env = _env_with_repo_root({"AUTOFLOW_MODEL_LAYER": "flowtree"})
        if extra_env:
            env.update(extra_env)
        out = subprocess.check_output([sys.executable, "-c", code], env=env, stderr=subprocess.STDOUT)
        s = out.decode("utf-8", errors="replace").strip()
        return [] if not s else s.splitlines()

    def test_objectinfo_empty_by_default_but_auto_resolves_with_env(self):
        code = r"""
import os
from pathlib import Path

from autoflow import ObjectInfo
import autoflow.models as models

td = Path(os.environ["AUTOFLOW_TESTDATA_DIR"])
oi_path = td / "object_info.json"

# 1) No env source => empty ObjectInfo (no error)
os.environ.pop("AUTOFLOW_OBJECT_INFO_SOURCE", None)
o = ObjectInfo()
print(len(o))

# 2) Env source pointing at file => auto-resolve and populate
os.environ["AUTOFLOW_OBJECT_INFO_SOURCE"] = str(oi_path)
o2 = ObjectInfo()
print("KSampler" in o2)

# 3) Explicit source= should work without env
os.environ.pop("AUTOFLOW_OBJECT_INFO_SOURCE", None)
o3 = ObjectInfo(source=str(oi_path))
print("KSampler" in o3)

# 4) Instance fetch should mutate in-place.
# Patch legacy fetch to avoid network and return a fixture-loaded ObjectInfo.
def _fake_fetch(cls, server_url=None, *, timeout=0, output_path=None):
    return models.ObjectInfo.load(oi_path)
models.ObjectInfo.fetch = classmethod(_fake_fetch)

o4 = ObjectInfo()
o4.fetch(server_url="http://example.invalid")
print("KSampler" in o4)
"""
        out = self._run(code)
        self.assertEqual(out[0].strip(), "0")
        self.assertEqual(out[1].strip(), "True")
        self.assertEqual(out[2].strip(), "True")
        self.assertEqual(out[3].strip(), "True")


if __name__ == "__main__":
    unittest.main()

