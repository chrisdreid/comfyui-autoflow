#!/usr/bin/env python3
"""
Internal test to verify the import-time model layer switch.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path


_repo_root = Path(__file__).resolve().parents[2]


def _env_with_repo_root(extra: dict) -> dict:
    env = dict(os.environ)
    pp = env.get("PYTHONPATH", "")
    parts = [p for p in pp.split(os.pathsep) if p]
    if str(_repo_root) not in parts:
        parts.insert(0, str(_repo_root))
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env.update(extra)
    return env


class TestModelLayerEnvSwitch(unittest.TestCase):
    def _run(self, code: str, env_extra: dict) -> str:
        out = subprocess.check_output(
            [sys.executable, "-c", code],
            env=_env_with_repo_root(env_extra),
            stderr=subprocess.STDOUT,
        )
        return out.decode("utf-8", errors="replace").strip()

    def test_default_is_flowtree(self):
        code = "from autoflow import Flow; import inspect; print(Flow.__module__)"
        mod = self._run(code, {"AUTOFLOW_MODEL_LAYER": ""})
        self.assertEqual(mod, "autoflow.flowtree")

    def test_models_switch(self):
        code = "from autoflow import Flow; print(Flow.__module__)"
        mod = self._run(code, {"AUTOFLOW_MODEL_LAYER": "models"})
        self.assertEqual(mod, "autoflow.models")

    def test_flowtree_switch(self):
        code = "from autoflow import Flow; print(Flow.__module__)"
        mod = self._run(code, {"AUTOFLOW_MODEL_LAYER": "flowtree"})
        self.assertEqual(mod, "autoflow.flowtree")

    def test_invalid_value_fails_fast(self):
        code = "import autoflow"
        with self.assertRaises(subprocess.CalledProcessError) as ctx:
            _ = self._run(code, {"AUTOFLOW_MODEL_LAYER": "nope"})
        self.assertIn("AUTOFLOW_MODEL_LAYER must be", ctx.exception.output.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    unittest.main()


