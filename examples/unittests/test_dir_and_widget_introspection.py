#!/usr/bin/env python3
"""
Tests for curated __dir__, WidgetValue wrapping, and _widget_names filtering.

All tests use inline data — no external fixture files required.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


_repo_root = Path(__file__).resolve().parents[2]

# Minimal node_info for KSampler: widgets have opts dicts, connections have bare type strings.
_KSAMPLER_NODE_INFO = {
    "KSampler": {
        "input": {
            "required": {
                "model": ["MODEL"],
                "seed": ["INT", {"default": 0, "min": 0, "max": 2147483647, "tooltip": "Seed value"}],
                "steps": ["INT", {"default": 20, "min": 1, "max": 10000}],
                "cfg": ["FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0}],
                "sampler_name": [["euler", "euler_ancestral", "heun", "dpm_2"], {}],
                "scheduler": [["normal", "karras", "simple"], {}],
                "positive": ["CONDITIONING"],
                "negative": ["CONDITIONING"],
                "latent_image": ["LATENT"],
                "denoise": ["FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0}],
            },
        },
    },
    "SaveImage": {
        "input": {
            "required": {
                "images": ["IMAGE"],
                "filename_prefix": ["STRING", {"default": "ComfyUI"}],
            },
        },
    },
}

# Minimal API payload with KSampler + SaveImage nodes.
_API_PAYLOAD = {
    "1": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "steps": 20,
            "cfg": 8.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["2", 0],
            "positive": ["3", 0],
            "negative": ["4", 0],
            "latent_image": ["5", 0],
        },
    },
    "6": {
        "class_type": "SaveImage",
        "inputs": {
            "images": ["1", 0],
            "filename_prefix": "ComfyUI",
        },
    },
}


def _env_with_repo_root(extra: dict) -> dict:
    env = dict(os.environ)
    pp = env.get("PYTHONPATH", "")
    parts = [p for p in pp.split(os.pathsep) if p]
    if str(_repo_root) not in parts:
        parts.insert(0, str(_repo_root))
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env.update(extra)
    return env


class TestDirAndWidgetIntrospection(unittest.TestCase):
    def _run(self, code: str) -> str:
        out = subprocess.check_output(
            [sys.executable, "-c", code],
            env=_env_with_repo_root({"AUTOFLOW_MODEL_LAYER": "flowtree"}),
            stderr=subprocess.STDOUT,
        )
        return out.decode("utf-8", errors="replace").strip()

    def _inline_preamble(self, *, with_node_info: bool = True) -> str:
        """Return Python preamble that sets up api with inline data."""
        lines = [
            "import json",
            "from autoflow import ApiFlow",
            f"_NI = json.loads({json.dumps(json.dumps(_KSAMPLER_NODE_INFO))!s})",
            f"_API = json.loads({json.dumps(json.dumps(_API_PAYLOAD))!s})",
        ]
        if with_node_info:
            lines.append("api = ApiFlow(_API, node_info=_NI)")
        else:
            lines.append("api = ApiFlow(_API)")
        return "\n".join(lines)

    # ── ApiFlow.__dir__ ──────────────────────────────────────────────

    def test_apiflow_dir_contains_class_types(self):
        code = self._inline_preamble() + """
d = dir(api)
print("KSampler" in d)
print("SaveImage" in d)
"""
        out = self._run(code).splitlines()
        self.assertEqual(out[-2].strip(), "True")
        self.assertEqual(out[-1].strip(), "True")

    def test_apiflow_dir_contains_user_methods(self):
        code = self._inline_preamble() + """
d = dir(api)
for m in ("find", "by_id", "submit", "execute", "save", "to_json", "to_dict",
          "node_info", "dag", "items", "keys", "values"):
    assert m in d, f"{m} missing from ApiFlow.__dir__"
print("OK")
"""
        self.assertIn("OK", self._run(code))

    def test_apiflow_dir_excludes_mutablemapping_internals(self):
        code = self._inline_preamble() + """
d = dir(api)
for m in ("__getitem__", "__setitem__", "__delitem__", "__contains__",
          "__len__", "__iter__", "pop", "update", "setdefault"):
    assert m not in d, f"{m} should not be in ApiFlow.__dir__"
print("OK")
"""
        self.assertIn("OK", self._run(code))

    # ── NodeSet.__dir__ ──────────────────────────────────────────────

    def test_nodeset_dir_contains_widget_attrs(self):
        code = self._inline_preamble() + """
d = dir(api.KSampler)
for w in ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"):
    assert w in d, f"Widget '{w}' missing from NodeSet.__dir__"
print("OK")
"""
        self.assertIn("OK", self._run(code))

    def test_nodeset_dir_excludes_link_inputs(self):
        code = self._inline_preamble() + """
d = dir(api.KSampler)
for link in ("model", "positive", "negative", "latent_image"):
    assert link not in d, f"Link input '{link}' should not be in NodeSet.__dir__"
print("OK")
"""
        self.assertIn("OK", self._run(code))

    def test_nodeset_dir_excludes_classmethods(self):
        code = self._inline_preamble() + """
d = dir(api.KSampler)
for m in ("from_apiflow_find", "from_apiflow_group", "from_flow_find",
          "dictpaths", "paths", "to_list"):
    assert m not in d, f"Internal method '{m}' should not be in NodeSet.__dir__"
print("OK")
"""
        self.assertIn("OK", self._run(code))

    def test_nodeset_dir_contains_methods(self):
        code = self._inline_preamble() + """
d = dir(api.KSampler)
for m in ("set", "apply", "first", "attrs", "find", "items", "keys", "values"):
    assert m in d, f"Method '{m}' missing from NodeSet.__dir__"
print("OK")
"""
        self.assertIn("OK", self._run(code))

    # ── NodeRef.__dir__ ──────────────────────────────────────────────

    def test_noderef_dir_contains_widgets(self):
        code = self._inline_preamble() + """
d = dir(api.KSampler[0])
for w in ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"):
    assert w in d, f"Widget '{w}' missing from NodeRef.__dir__"
print("OK")
"""
        self.assertIn("OK", self._run(code))

    def test_noderef_dir_excludes_internal_fields(self):
        code = self._inline_preamble() + """
d = dir(api.KSampler[0])
for f in ("kind", "addr", "group", "index", "path", "dictpath"):
    assert f not in d, f"Internal field '{f}' should not be in NodeRef.__dir__"
print("OK")
"""
        self.assertIn("OK", self._run(code))

    # ── WidgetValue wrapping ─────────────────────────────────────────

    def test_widgetvalue_returned_with_node_info(self):
        code = self._inline_preamble(with_node_info=True) + """
seed = api.KSampler[0].seed
print(type(seed).__name__)
print(hasattr(seed, "choices"))
print(hasattr(seed, "tooltip"))
print(hasattr(seed, "spec"))
"""
        out = self._run(code).splitlines()
        self.assertEqual(out[-4].strip(), "WidgetValue")
        self.assertEqual(out[-3].strip(), "True")
        self.assertEqual(out[-2].strip(), "True")
        self.assertEqual(out[-1].strip(), "True")

    def test_raw_value_without_node_info(self):
        code = """
import os
os.environ.pop("AUTOFLOW_COMFYUI_SERVER_URL", None)
os.environ.pop("AUTOFLOW_NODE_INFO_SOURCE", None)
""" + self._inline_preamble(with_node_info=False) + """
seed = api.KSampler[0].seed
print(type(seed).__name__)
print(seed)
"""
        out = self._run(code).splitlines()
        self.assertEqual(out[-2].strip(), "int")
        self.assertEqual(out[-1].strip(), "42")

    def test_widgetvalue_transparent_comparison(self):
        code = self._inline_preamble() + """
seed = api.KSampler[0].seed
print(seed == 42)
print(seed == seed.value)
"""
        out = self._run(code).splitlines()
        self.assertEqual(out[-2].strip(), "True")
        self.assertEqual(out[-1].strip(), "True")

    def test_widgetvalue_choices(self):
        code = self._inline_preamble() + """
sn = api.KSampler[0].sampler_name
choices = sn.choices()
print(type(choices).__name__)
print("euler" in choices)
# INT has no choices
seed = api.KSampler[0].seed
print(seed.choices())
"""
        out = self._run(code).splitlines()
        self.assertEqual(out[-3].strip(), "list")
        self.assertEqual(out[-2].strip(), "True")
        self.assertEqual(out[-1].strip(), "None")

    def test_widgetvalue_tooltip(self):
        code = self._inline_preamble() + """
seed = api.KSampler[0].seed
tt = seed.tooltip()
print(tt)
"""
        out = self._run(code).splitlines()
        self.assertEqual(out[-1].strip(), "Seed value")

    def test_widgetvalue_dir_only_user_facing(self):
        code = self._inline_preamble() + """
wv = api.KSampler[0].seed
d = sorted(dir(wv))
print(d)
assert d == ["choices", "spec", "tooltip", "value"], f"Unexpected __dir__: {d}"
print("OK")
"""
        self.assertIn("OK", self._run(code))

    # ── _widget_names filtering ──────────────────────────────────────

    def test_widget_names_excludes_links(self):
        code = self._inline_preamble() + """
nr = api.KSampler[0]
wn = nr._widget_names()
for link in ("model", "positive", "negative", "latent_image"):
    assert link not in wn, f"Link '{link}' should not be a widget name"
for w in ("seed", "steps", "cfg"):
    assert w in wn, f"Widget '{w}' missing from _widget_names"
print("OK")
"""
        self.assertIn("OK", self._run(code))

    def test_widget_names_fallback_no_nodeinfo(self):
        code = self._inline_preamble(with_node_info=False) + """
nr = api.KSampler[0]
wn = nr._widget_names()
assert "seed" in wn
assert "steps" in wn
assert "model" not in wn
assert "positive" not in wn
print("OK")
"""
        self.assertIn("OK", self._run(code))

    # ── ApiFlow.items/keys/values ────────────────────────────────────

    def test_apiflow_items_keys_values(self):
        code = self._inline_preamble() + """
items = api.items()
keys = api.keys()
values = api.values()
print(type(items).__name__)
print(len(keys) > 0)
print(len(values) > 0)
print(len(items) == len(keys))
"""
        out = self._run(code).splitlines()
        self.assertEqual(out[-4].strip(), "list")
        self.assertEqual(out[-3].strip(), "True")
        self.assertEqual(out[-2].strip(), "True")
        self.assertEqual(out[-1].strip(), "True")


if __name__ == "__main__":
    unittest.main()
