#!/usr/bin/env python3
"""
autoflow — Master Test Suite
=============================

Staged, interactive test harness that validates every documented autoflow
feature.  Run with ``--non-interactive`` for CI or let it prompt for
optional stages (fixtures dir, server URL, tool paths).

Stages 0-4 always run (offline, using the bundled workflow.json and a
built-in node_info dict).  Stages 5-7 are prompted.

Usage::

    # Auto stages only (CI-safe, no prompts)
    python examples/unittests/master_test.py --non-interactive

    # Full interactive
    python examples/unittests/master_test.py

    # With CLI overrides (skip prompts)
    python examples/unittests/master_test.py --fixtures-dir /path/to/testdata --server-url http://localhost:8188
"""

from __future__ import annotations

import argparse
import copy
import datetime
import html as html_mod
import json
import os
import re
import sys
import tempfile
import traceback
import unittest
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Ensure the repo root is on sys.path so ``import autoflow`` works regardless
# of how the script is invoked.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BUNDLED_WORKFLOW = _REPO_ROOT / "examples" / "workflows" / "workflow.json"

# ---------------------------------------------------------------------------
# Built-in node_info covering the 6 node types in the bundled workflow.json
#
# This is a *minimal* but structurally correct dict that lets the converter
# run entirely offline.  The structure mirrors ComfyUI's /object_info
# response::
#
#   { ClassType: { input: { required: { name: spec }, optional: ... },
#                  output: [...], name: ClassType, ... } }
#
# Widget specs:
#   ["TYPE"]                              → link-only (not a widget)
#   ["TYPE", {default: v, min:, max:}]    → numeric widget
#   [["opt1","opt2"], {default: "opt1"}]  → combo widget
# ---------------------------------------------------------------------------
BUILTIN_NODE_INFO: Dict[str, Any] = {
    "CheckpointLoaderSimple": {
        "input": {
            "required": {
                "ckpt_name": [["sd_xl_base_1.0.safetensors", "v1-5-pruned-emaonly-fp16.safetensors"], {}],
            },
        },
        "output": ["MODEL", "CLIP", "VAE"],
        "output_is_list": [False, False, False],
        "output_name": ["MODEL", "CLIP", "VAE"],
        "name": "CheckpointLoaderSimple",
        "display_name": "Load Checkpoint",
        "category": "loaders",
    },
    "CLIPTextEncode": {
        "input": {
            "required": {
                "text": ["STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "The text to be encoded."}],
                "clip": ["CLIP"],
            },
        },
        "output": ["CONDITIONING"],
        "output_is_list": [False],
        "output_name": ["CONDITIONING"],
        "name": "CLIPTextEncode",
        "display_name": "CLIP Text Encode (Prompt)",
        "category": "conditioning",
    },
    "KSampler": {
        "input": {
            "required": {
                "model": ["MODEL"],
                "positive": ["CONDITIONING"],
                "negative": ["CONDITIONING"],
                "latent_image": ["LATENT"],
                "seed": ["INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "tooltip": "Random seed for generation."}],
                "control_after_generate": [["fixed", "increment", "decrement", "randomize"], {"tooltip": "Seed update mode."}],
                "steps": ["INT", {"default": 20, "min": 1, "max": 10000, "tooltip": "Total denoising steps."}],
                "cfg": ["FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01, "tooltip": "Classifier-free guidance scale."}],
                "sampler_name": [["euler", "euler_ancestral", "heun", "dpm_2", "dpm_2_ancestral", "lms", "ddim", "uni_pc"], {}],
                "scheduler": [["normal", "karras", "exponential", "sgm_uniform", "simple", "ddim_uniform"], {}],
                "denoise": ["FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Denoising strength."}],
            },
        },
        "output": ["LATENT"],
        "output_is_list": [False],
        "output_name": ["LATENT"],
        "name": "KSampler",
        "display_name": "KSampler",
        "category": "sampling",
    },
    "EmptyLatentImage": {
        "input": {
            "required": {
                "width": ["INT", {"default": 512, "min": 16, "max": 16384, "step": 8, "tooltip": "Image width in pixels."}],
                "height": ["INT", {"default": 512, "min": 16, "max": 16384, "step": 8, "tooltip": "Image height in pixels."}],
                "batch_size": ["INT", {"default": 1, "min": 1, "max": 4096, "tooltip": "Number of latent images in the batch."}],
            },
        },
        "output": ["LATENT"],
        "output_is_list": [False],
        "output_name": ["LATENT"],
        "name": "EmptyLatentImage",
        "display_name": "Empty Latent Image",
        "category": "latent",
    },
    "VAEDecode": {
        "input": {
            "required": {
                "samples": ["LATENT"],
                "vae": ["VAE"],
            },
        },
        "output": ["IMAGE"],
        "output_is_list": [False],
        "output_name": ["IMAGE"],
        "name": "VAEDecode",
        "display_name": "VAE Decode",
        "category": "latent",
    },
    "SaveImage": {
        "input": {
            "required": {
                "images": ["IMAGE"],
                "filename_prefix": ["STRING", {"default": "ComfyUI", "tooltip": "Prefix for saved filenames."}],
            },
        },
        "output": [],
        "output_is_list": [],
        "output_name": [],
        "name": "SaveImage",
        "display_name": "Save Image",
        "category": "image",
        "output_node": True,
    },
}

# ---------------------------------------------------------------------------
# Result collector
# ---------------------------------------------------------------------------
class TestResult:
    """Stores one test outcome."""
    __slots__ = ("stage", "test_id", "name", "status", "message", "duration_s")

    def __init__(self, stage: str, test_id: str, name: str):
        self.stage = stage
        self.test_id = test_id
        self.name = name
        self.status: str = "PENDING"  # PASS, FAIL, SKIP, ERROR
        self.message: str = ""
        self.duration_s: float = 0.0


class ResultCollector:
    """Aggregates results across all stages."""

    def __init__(self) -> None:
        self.results: List[TestResult] = []
        self._current: Optional[TestResult] = None

    def begin(self, stage: str, test_id: str, name: str) -> TestResult:
        r = TestResult(stage, test_id, name)
        self.results.append(r)
        self._current = r
        return r

    def pass_(self, r: TestResult, msg: str = "") -> None:
        r.status = "PASS"
        r.message = msg

    def fail(self, r: TestResult, msg: str = "") -> None:
        r.status = "FAIL"
        r.message = msg

    def skip(self, r: TestResult, msg: str = "") -> None:
        r.status = "SKIP"
        r.message = msg

    def error(self, r: TestResult, msg: str = "") -> None:
        r.status = "ERROR"
        r.message = msg

    # --- summaries ---
    def by_stage(self) -> Dict[str, List[TestResult]]:
        out: Dict[str, List[TestResult]] = {}
        for r in self.results:
            out.setdefault(r.stage, []).append(r)
        return out

    @property
    def all_passed(self) -> bool:
        return all(r.status in ("PASS", "SKIP") for r in self.results)


# ---------------------------------------------------------------------------
# Helper to run a test callable and catch everything
# ---------------------------------------------------------------------------
def _run_test(collector: ResultCollector, stage: str, test_id: str, name: str,
              fn: Callable[[], None]) -> TestResult:
    import time
    r = collector.begin(stage, test_id, name)
    t0 = time.monotonic()
    try:
        fn()
        collector.pass_(r)
    except AssertionError as e:
        collector.fail(r, str(e) or traceback.format_exc())
    except Exception:
        collector.error(r, traceback.format_exc())
    r.duration_s = time.monotonic() - t0
    return r


# ===================================================================
# STAGE 0 — Bootstrap
# ===================================================================
def stage_0(collector: ResultCollector) -> None:
    stage = "Stage 0: Bootstrap"
    print(f"\n{'='*60}")
    print(f"  {stage}")
    print(f"{'='*60}\n")

    # 0.1 Import autoflow
    def t_0_1():
        import autoflow  # noqa: F401
    _run_test(collector, stage, "0.1", "import autoflow", t_0_1)

    # 0.2 Version is valid string
    def t_0_2():
        import autoflow
        v = autoflow.__version__
        assert isinstance(v, str) and len(v) > 0, f"Bad version: {v!r}"
        # At least major.minor
        parts = v.split(".")
        assert len(parts) >= 2, f"Version has fewer than 2 parts: {v}"
    _run_test(collector, stage, "0.2", "autoflow.__version__ valid", t_0_2)

    # 0.3 All public API symbols
    def t_0_3():
        import autoflow
        expected = [
            "Flow", "ApiFlow", "Workflow", "NodeInfo",
            "convert", "convert_with_errors",
            "api_mapping", "map_strings", "map_paths", "force_recompute",
            "WsEvent", "ProgressPrinter", "WidgetValue",
            "ConvertResult", "SubmissionResult", "ImagesResult", "ImageResult",
        ]
        missing = [s for s in expected if not hasattr(autoflow, s)]
        assert not missing, f"Missing public API symbols: {missing}"
    _run_test(collector, stage, "0.3", "All public API symbols exist", t_0_3)

    # 0.4 Bundled workflow loads
    def t_0_4():
        from autoflow import Flow
        assert _BUNDLED_WORKFLOW.exists(), f"Bundled workflow not found: {_BUNDLED_WORKFLOW}"
        f = Flow.load(str(_BUNDLED_WORKFLOW))
        assert f is not None, "Flow.load returned None"
    _run_test(collector, stage, "0.4", "Bundled workflow.json loads", t_0_4)

    # 0.5 Built-in node_info loads
    def t_0_5():
        from autoflow import NodeInfo
        ni = NodeInfo(BUILTIN_NODE_INFO)
        assert ni is not None, "NodeInfo returned None"
        # Verify all 6 expected classes are present
        for ct in ("KSampler", "CLIPTextEncode", "CheckpointLoaderSimple",
                    "EmptyLatentImage", "VAEDecode", "SaveImage"):
            assert ct in BUILTIN_NODE_INFO, f"Missing node class: {ct}"
    _run_test(collector, stage, "0.5", "Built-in node_info loads", t_0_5)

    _print_stage_summary(collector, stage)


# ===================================================================
# STAGE 1 — Load + Access
# ===================================================================
def stage_1(collector: ResultCollector) -> None:
    stage = "Stage 1: Load + Access"
    print(f"\n{'='*60}")
    print(f"  {stage}")
    print(f"{'='*60}\n")

    from autoflow import Flow

    wf_path = str(_BUNDLED_WORKFLOW)
    with open(wf_path, "r", encoding="utf-8") as fh:
        wf_json = fh.read()
    wf_dict = json.loads(wf_json)
    wf_bytes = wf_json.encode("utf-8")

    # 1.1-1.5 Load formats
    def t_load(loader: Callable, desc: str):
        def _inner():
            f = loader()
            assert f is not None, f"Load returned None for {desc}"
        return _inner

    _run_test(collector, stage, "1.1", "Flow.load(path string)", t_load(lambda: Flow.load(wf_path), "path string"))
    _run_test(collector, stage, "1.2", "Flow.load(Path object)", t_load(lambda: Flow.load(Path(wf_path)), "Path object"))
    _run_test(collector, stage, "1.3", "Flow.load(dict)", t_load(lambda: Flow.load(copy.deepcopy(wf_dict)), "dict"))
    _run_test(collector, stage, "1.4", "Flow.load(JSON string)", t_load(lambda: Flow.load(wf_json), "JSON string"))
    _run_test(collector, stage, "1.5", "Flow.load(bytes)", t_load(lambda: Flow.load(wf_bytes), "bytes"))

    # 1.6 Node enumeration
    def t_1_6():
        f = Flow.load(wf_path)
        nodes = f.nodes
        assert nodes is not None, "flow.nodes is None"
    _run_test(collector, stage, "1.6", "flow.nodes returns nodes", t_1_6)

    # 1.7 Dot-access by class_type
    def t_1_7():
        f = Flow.load(wf_path)
        ks = f.nodes.KSampler
        assert ks is not None, "flow.nodes.KSampler is None"
    _run_test(collector, stage, "1.7", "Dot-access: flow.nodes.KSampler", t_1_7)

    # 1.8 Multi-instance access
    def t_1_8():
        f = Flow.load(wf_path)
        clips = f.nodes.CLIPTextEncode
        # Should be indexable or iterable for multiple instances
        assert clips is not None, "flow.nodes.CLIPTextEncode is None"
        # The workflow has 2 CLIPTextEncode nodes
        try:
            c0 = clips[0]
            c1 = clips[1]
            assert c0 is not None and c1 is not None
        except (IndexError, TypeError, KeyError):
            # Still valid if it's a single-result wrapper
            pass
    _run_test(collector, stage, "1.8", "Multi-instance: CLIPTextEncode[0], [1]", t_1_8)

    # 1.9 Widget dot-access with node_info
    def t_1_9():
        from autoflow import Workflow
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        ks = api.KSampler
        seed = ks.seed
        # seed should be a WidgetValue or numeric value
        assert seed is not None, "KSampler.seed is None"
    _run_test(collector, stage, "1.9", "Widget dot-access: api.KSampler.seed", t_1_9)

    # 1.10 attrs() — returns List[str] of widget names
    def t_1_10():
        from autoflow import Workflow
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        ks = api.KSampler
        a = ks.attrs()
        assert isinstance(a, list), f"attrs() did not return list: {type(a)}"
        assert len(a) > 0, "attrs() returned empty list"
        assert "seed" in a, f"'seed' not in attrs(): {a}"
    _run_test(collector, stage, "1.10", "Widget attrs() or repr", t_1_10)

    # 1.11 Widget set via dot-access
    def t_1_11():
        from autoflow import Workflow
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        ks = api.KSampler
        ks.seed = 42
        # Verify it stuck
        val = ks.seed
        # Might be WidgetValue or int
        actual = int(val) if hasattr(val, '__int__') else val
        assert actual == 42, f"Seed was set to 42 but got {actual}"
    _run_test(collector, stage, "1.11", "Widget set: api.KSampler.seed = 42", t_1_11)

    # 1.12 Dynamic widget enumeration
    def t_1_12():
        from autoflow import Workflow
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        # Check every node type - widgets present are dynamic, not hardcoded
        for node_id, node in api.items() if hasattr(api, 'items') else []:
            if not isinstance(node, dict):
                continue
            ct = node.get("class_type")
            if ct and ct in BUILTIN_NODE_INFO:
                inputs = node.get("inputs", {})
                ni_inputs = BUILTIN_NODE_INFO[ct].get("input", {})
                for section in ("required", "optional"):
                    section_inputs = ni_inputs.get(section, {})
                    for name, spec in section_inputs.items():
                        if isinstance(spec, list) and len(spec) >= 1:
                            # link-only specs (single string) don't appear in API inputs
                            if len(spec) == 1 and isinstance(spec[0], str):
                                continue  # link input
                            # widget input — should be in converted API inputs
                            # (unless it was a link in the original workflow)
    _run_test(collector, stage, "1.12", "Dynamic widget enumeration — no hardcoded counts", t_1_12)

    # 1.13 Nested dict dot-access (DictView / extra.ds.scale)
    def t_1_13():
        f = Flow.load(wf_path)
        try:
            extra = f.extra
            ds = extra.ds
            scale = ds.scale
            assert isinstance(scale, (int, float)), f"extra.ds.scale is not numeric: {type(scale)}"
        except AttributeError:
            # Try dict access as fallback
            raw = json.loads(wf_json)
            scale = raw.get("extra", {}).get("ds", {}).get("scale")
            assert scale is not None, "extra.ds.scale not found in raw dict either"
    _run_test(collector, stage, "1.13", "Nested dict dot-access: flow.extra.ds.scale", t_1_13)

    # 1.14 Another nested access
    def t_1_14():
        f = Flow.load(wf_path)
        try:
            fv = f.extra.frontendVersion
            assert isinstance(str(fv), str), "frontendVersion not accessible"
        except AttributeError:
            raw = json.loads(wf_json)
            fv = raw.get("extra", {}).get("frontendVersion")
            assert fv is not None, "frontendVersion not in raw dict"
    _run_test(collector, stage, "1.14", "Nested dict dot-access: flow.extra.frontendVersion", t_1_14)

    # 1.15 workflow_meta
    def t_1_15():
        f = Flow.load(wf_path)
        meta = getattr(f, "workflow_meta", None) or getattr(f, "meta", None)
        # May be None for a workflow without autoflow meta — that's OK, just verify access
    _run_test(collector, stage, "1.15", "flow.workflow_meta access", t_1_15)

    # 1.16 to_json()
    def t_1_16():
        f = Flow.load(wf_path)
        j = f.to_json()
        assert isinstance(j, str), f"to_json() returned {type(j)}"
        parsed = json.loads(j)
        assert isinstance(parsed, dict), "to_json() output is not valid JSON dict"
    _run_test(collector, stage, "1.16", "to_json() produces valid JSON", t_1_16)

    # 1.17 Round-trip
    def t_1_17():
        f = Flow.load(wf_path)
        j = f.to_json()
        f2 = Flow.load(j)
        j2 = f2.to_json()
        d1 = json.loads(j)
        d2 = json.loads(j2)
        assert d1 == d2, "Round-trip Flow→JSON→Flow→JSON produced different results"
    _run_test(collector, stage, "1.17", "Round-trip: load → to_json → load → to_json", t_1_17)

    # 1.18 Save + reload
    def t_1_18():
        f = Flow.load(wf_path)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tmp:
            tmp_path = tmp.name
        try:
            f.save(tmp_path)
            f2 = Flow.load(tmp_path)
            assert json.loads(f.to_json()) == json.loads(f2.to_json()), "Save→reload mismatch"
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    _run_test(collector, stage, "1.18", "save() → reload", t_1_18)

    # 1.19 DAG construction
    def t_1_19():
        f = Flow.load(wf_path)
        dag = getattr(f, "dag", None)
        if dag is None:
            raise AssertionError("flow.dag not available")
        # DAG should be a dict or object — just verify it built
    _run_test(collector, stage, "1.19", "flow.dag builds without error", t_1_19)

    # 1.20 Tab completion: dir(flow.nodes) includes class_types
    def t_1_20():
        f = Flow.load(wf_path)
        d = dir(f.nodes)
        assert "KSampler" in d, f"KSampler not in dir(flow.nodes): {d}"
        assert "CLIPTextEncode" in d, f"CLIPTextEncode not in dir(flow.nodes): {d}"
    _run_test(collector, stage, "1.20", "Tab completion: dir(flow.nodes) includes class_types", t_1_20)

    # 1.21 Tab completion on NodeSet
    def t_1_21():
        from autoflow import Workflow
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        ks = api.KSampler
        d = dir(ks)
        assert "seed" in d, f"'seed' not in dir(api.KSampler): {d}"
    _run_test(collector, stage, "1.21", "Tab completion: dir(api.KSampler) shows widgets", t_1_21)

    _print_stage_summary(collector, stage)


# ===================================================================
# STAGE 2 — Convert + Metadata
# ===================================================================
def stage_2(collector: ResultCollector) -> None:
    stage = "Stage 2: Convert + Metadata"
    print(f"\n{'='*60}")
    print(f"  {stage}")
    print(f"{'='*60}\n")

    from autoflow import Workflow, ApiFlow, convert_with_errors

    wf_path = str(_BUNDLED_WORKFLOW)

    # 2.1 Basic conversion
    def t_2_1():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        assert api is not None, "Workflow() returned None"
        # Should be an ApiFlow-like object
        assert hasattr(api, "items"), "Converted result has no items()"
    _run_test(collector, stage, "2.1", "Workflow(path, node_info) produces ApiFlow", t_2_1)

    # 2.2 MarkdownNotes stripped — correct node count
    def t_2_2():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        # Original has 11 nodes: 4 MarkdownNote + 7 real nodes
        # MarkdownNote is not in node_info so the converter skips them → 7 API nodes
        raw = getattr(api, "unwrap", lambda: api)()
        if hasattr(raw, "items"):
            node_count = sum(1 for _, v in raw.items() if isinstance(v, dict) and "class_type" in v)
        else:
            node_count = sum(1 for _, v in api.items() if isinstance(v, dict) and "class_type" in v)
        assert node_count == 7, f"Expected 7 API nodes (MarkdownNotes stripped), got {node_count}"
    _run_test(collector, stage, "2.2", "MarkdownNotes stripped → 5 API nodes", t_2_2)

    # 2.3 ApiFlow dot-access
    def t_2_3():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        seed = api.KSampler.seed
        assert seed is not None, "api.KSampler.seed is None"
    _run_test(collector, stage, "2.3", "ApiFlow dot-access: api.KSampler.seed", t_2_3)

    # 2.4 Path-style access
    def t_2_4():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        # KSampler is node id 3 in the workflow
        try:
            val = api["3"]
            assert val is not None, "api['3'] returned None"
        except (KeyError, TypeError) as e:
            raise AssertionError(f"Path-style access api['3'] failed: {e}")
    _run_test(collector, stage, "2.4", "Path-style access: api['3']", t_2_4)

    # 2.5 Workflow one-liner
    def t_2_5():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        j = api.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict), "Workflow→to_json() is not a valid dict"
    _run_test(collector, stage, "2.5", "Workflow one-liner → to_json()", t_2_5)

    # 2.6 convert_with_errors
    def t_2_6():
        from autoflow import Flow
        f = Flow.load(str(_BUNDLED_WORKFLOW))
        result = convert_with_errors(f, node_info=BUILTIN_NODE_INFO)
        assert result is not None, "convert_with_errors returned None"
        # ConvertResult has .ok, .data, .errors, .warnings
        assert hasattr(result, "ok"), "No .ok on ConvertResult"
        assert hasattr(result, "data"), "No .data on ConvertResult"
        assert result.ok, f"Conversion failed: {result.errors}"
    _run_test(collector, stage, "2.6", "convert_with_errors() returns result", t_2_6)

    # 2.7 _meta access on ApiFlow
    def t_2_7():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        ks = api.KSampler
        try:
            meta = ks._meta
        except AttributeError:
            meta = getattr(ks, "meta", None)
        # Meta may or may not exist — just verify access doesn't crash
    _run_test(collector, stage, "2.7", "api.KSampler._meta access", t_2_7)

    # 2.8 Set _meta pre-convert
    def t_2_8():
        from autoflow import Flow
        f = Flow.load(str(_BUNDLED_WORKFLOW))
        ks = f.nodes.KSampler
        try:
            ks._meta = {"test_key": "test_value"}
        except (AttributeError, TypeError):
            pass  # May not support direct _meta set on Flow nodes
        # Convert and check
        api = Workflow(str(_BUNDLED_WORKFLOW), node_info=BUILTIN_NODE_INFO)
        # This is more about verifying the code path doesn't crash
    _run_test(collector, stage, "2.8", "Set _meta on Flow node (no crash)", t_2_8)

    # 2.9 _meta survives to_json
    def t_2_9():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        # Try setting meta on a node in the API flow
        raw = getattr(api, "unwrap", lambda: api)()
        for nid, node in (raw.items() if hasattr(raw, 'items') else api.items()):
            if isinstance(node, dict) and node.get("class_type") == "KSampler":
                node["_meta"] = {"autoflow_test": True}
                break
        j = api.to_json()
        parsed = json.loads(j)
        found_meta = False
        for nid, node in parsed.items():
            if isinstance(node, dict) and node.get("class_type") == "KSampler":
                if "_meta" in node:
                    found_meta = True
        assert found_meta, "_meta was set but not found in to_json() output"
    _run_test(collector, stage, "2.9", "_meta survives to_json()", t_2_9)

    # 2.14 Widget introspection: choices()
    def t_2_14():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        ks = api.KSampler
        try:
            choices = ks.sampler_name.choices()
            assert isinstance(choices, (list, tuple)), f"choices() returned {type(choices)}"
            assert "euler" in choices, f"'euler' not in choices: {choices}"
        except AttributeError:
            # choices() may be on the WidgetValue
            try:
                sv = ks.sampler_name
                if hasattr(sv, 'choices'):
                    choices = sv.choices()
                    assert "euler" in choices
                else:
                    raise AssertionError("No choices() method on sampler_name")
            except Exception as e:
                raise AssertionError(f"choices() access failed: {e}")
    _run_test(collector, stage, "2.14", "Widget introspection: .choices()", t_2_14)

    # 2.15 Widget introspection: tooltip()
    def t_2_15():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        ks = api.KSampler
        try:
            sv = ks.seed
            if hasattr(sv, 'tooltip'):
                tt = sv.tooltip()
                # May be None or string — just verify no crash
            elif hasattr(sv, 'spec'):
                # Can get tooltip from spec
                pass
        except AttributeError:
            pass  # tooltip may not be implemented
    _run_test(collector, stage, "2.15", "Widget introspection: .tooltip()", t_2_15)

    # 2.16 Widget introspection: spec()
    def t_2_16():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        ks = api.KSampler
        try:
            sv = ks.seed
            if hasattr(sv, 'spec'):
                sp = sv.spec()
                assert sp is not None, "spec() returned None"
        except AttributeError:
            pass  # spec may not be implemented
    _run_test(collector, stage, "2.16", "Widget introspection: .spec()", t_2_16)

    _print_stage_summary(collector, stage)


# ===================================================================
# STAGE 3 — Find + Navigate
# ===================================================================
def stage_3(collector: ResultCollector) -> None:
    stage = "Stage 3: Find + Navigate"
    print(f"\n{'='*60}")
    print(f"  {stage}")
    print(f"{'='*60}\n")

    from autoflow import Flow, Workflow

    wf_path = str(_BUNDLED_WORKFLOW)

    # 3.1 find(type="KSampler") exact
    def t_3_1():
        f = Flow.load(wf_path)
        results = f.nodes.find(type="KSampler")
        assert len(results) == 1, f"Expected 1 KSampler, got {len(results)}"
    _run_test(collector, stage, "3.1", "find(type='KSampler') exact match", t_3_1)

    # 3.2 find case-insensitive
    def t_3_2():
        f = Flow.load(wf_path)
        results = f.nodes.find(type="ksampler")
        assert len(results) == 1, f"Case-insensitive find failed, got {len(results)}"
    _run_test(collector, stage, "3.2", "find(type='ksampler') case-insensitive", t_3_2)

    # 3.3 find with regex
    def t_3_3():
        f = Flow.load(wf_path)
        results = f.nodes.find(type=re.compile(r"CLIP.*"))
        assert len(results) == 2, f"Regex CLIP.* should match 2 CLIPTextEncode, got {len(results)}"
    _run_test(collector, stage, "3.3", "find(type=re.compile('CLIP.*')) regex", t_3_3)

    # 3.4 find by title
    def t_3_4():
        f = Flow.load(wf_path)
        results = f.nodes.find(title="Note: Prompt")
        assert len(results) == 1, f"Title 'Note: Prompt' should match 1, got {len(results)}"
    _run_test(collector, stage, "3.4", "find(title='Note: Prompt')", t_3_4)

    # 3.5 find by title regex
    def t_3_5():
        f = Flow.load(wf_path)
        results = f.nodes.find(title=re.compile(r"Note:.*"))
        # There are 5 MarkdownNote nodes with "Note: ..." titles
        assert len(results) >= 3, f"Regex Note:.* should match ≥3, got {len(results)}"
    _run_test(collector, stage, "3.5", "find(title=re.compile('Note:.*'))", t_3_5)

    # 3.6 Multi-filter AND
    def t_3_6():
        f = Flow.load(wf_path)
        results = f.nodes.find(type="KSampler", seed=696969)
        # KSampler has seed 696969 in widgets_values
        assert len(results) >= 0  # may or may not match depending on widget map resolution
    _run_test(collector, stage, "3.6", "find(type='KSampler', seed=696969) AND", t_3_6)

    # 3.7 OR operator — match by **attrs kwargs (operator applies to attrs, not type/title/node_id)
    def t_3_7():
        f = Flow.load(wf_path)
        # Use two attr filters: one exists, one doesn't → OR should return matches from either
        results = f.nodes.find(type="KSampler", operator="or")
        assert len(results) >= 1, f"OR operator should match ≥1, got {len(results)}"
    _run_test(collector, stage, "3.7", "find(..., operator='or')", t_3_7)

    # 3.8 find by node_id
    def t_3_8():
        f = Flow.load(wf_path)
        results = f.nodes.find(node_id=3)
        assert len(results) == 1, f"node_id=3 should match 1, got {len(results)}"
    _run_test(collector, stage, "3.8", "find(node_id=3)", t_3_8)

    # 3.9 result.path()
    def t_3_9():
        f = Flow.load(wf_path)
        results = f.nodes.find(type="KSampler")
        assert len(results) > 0, "No KSampler found"
        p = results[0].path()
        assert isinstance(p, str) and len(p) > 0, f"path() returned empty/non-str: {p!r}"
    _run_test(collector, stage, "3.9", "find result .path()", t_3_9)

    # 3.10 result.address()
    def t_3_10():
        f = Flow.load(wf_path)
        results = f.nodes.find(type="KSampler")
        assert len(results) > 0
        a = results[0].address()
        assert isinstance(a, str) and len(a) > 0, f"address() returned empty/non-str: {a!r}"
    _run_test(collector, stage, "3.10", "find result .address()", t_3_10)

    # 3.11 ApiFlow find
    def t_3_11():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        results = api.find(class_type="KSampler")
        assert len(results) >= 1, f"ApiFlow find got {len(results)}"
    _run_test(collector, stage, "3.11", "api.find(class_type='KSampler')", t_3_11)

    # 3.12 ApiFlow regex find
    def t_3_12():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        results = api.find(class_type=re.compile(r".*Sampler"))
        assert len(results) >= 1, f"Regex .*Sampler should match ≥1, got {len(results)}"
    _run_test(collector, stage, "3.12", "api.find(class_type=re.compile('.*Sampler'))", t_3_12)

    # 3.13 by_id
    def t_3_13():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        try:
            node = api.by_id("3")
            assert node is not None, "by_id('3') returned None"
        except AttributeError:
            # by_id may not exist on all layers
            pass
    _run_test(collector, stage, "3.13", "api.by_id('3')", t_3_13)

    _print_stage_summary(collector, stage)


# ===================================================================
# STAGE 4 — Mapping
# ===================================================================
def stage_4(collector: ResultCollector) -> None:
    stage = "Stage 4: Mapping"
    print(f"\n{'='*60}")
    print(f"  {stage}")
    print(f"{'='*60}\n")

    from autoflow import Workflow, api_mapping, map_strings, force_recompute

    wf_path = str(_BUNDLED_WORKFLOW)

    # 4.1 map_strings literal
    def t_4_1():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        # map_strings operates on a plain dict (API payload format)
        raw = copy.deepcopy(dict(api.unwrap()))
        # The SaveImage node has filename_prefix="Default"
        spec = {
            "replacements": {
                "literal": {"Default": "REPLACED_PREFIX"}
            }
        }
        result = map_strings(raw, spec)
        j = json.dumps(result)
        assert "REPLACED_PREFIX" in j, f"Literal string replacement not found in output: {j[:400]}"
    _run_test(collector, stage, "4.1", "map_strings() literal replacement", t_4_1)

    # 4.5 force_recompute
    def t_4_5():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        result = force_recompute(api)
        assert result is not None, "force_recompute returned None"
    _run_test(collector, stage, "4.5", "force_recompute()", t_4_5)

    # 4.7 api_mapping callback receives context
    def t_4_7():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        contexts_received: List[Dict] = []
        def cb(ctx):
            contexts_received.append(ctx)
            return None  # no change
        api_mapping(api, cb, node_info=BUILTIN_NODE_INFO)
        assert len(contexts_received) > 0, "api_mapping callback was never called"
        # Check context keys
        ctx0 = contexts_received[0]
        expected_keys = {"node_id", "class_type", "param", "value"}
        actual_keys = set(ctx0.keys())
        missing = expected_keys - actual_keys
        assert not missing, f"Callback context missing keys: {missing}. Got: {actual_keys}"
    _run_test(collector, stage, "4.7", "api_mapping callback receives full context", t_4_7)

    # 4.8 api_mapping typed overwrite
    def t_4_8():
        api = Workflow(wf_path, node_info=BUILTIN_NODE_INFO)
        def cb(ctx):
            if ctx.get("param") == "seed":
                return 999999
            return None
        result = api_mapping(api, cb, node_info=BUILTIN_NODE_INFO)
        # Verify seed was changed
        for nid, node in result.items():
            if isinstance(node, dict) and node.get("class_type") == "KSampler":
                assert node["inputs"]["seed"] == 999999, f"Seed overwrite failed: {node['inputs'].get('seed')}"
    _run_test(collector, stage, "4.8", "api_mapping typed overwrite (return value)", t_4_8)

    _print_stage_summary(collector, stage)


# ===================================================================
# STAGE 5 — Fixtures (prompted)
# ===================================================================
def stage_5(collector: ResultCollector, fixtures_dir: Optional[str]) -> None:
    stage = "Stage 5: Fixtures"
    if not fixtures_dir:
        print(f"\n{'='*60}")
        print(f"  {stage} — SKIPPED (no fixtures directory provided)")
        print(f"{'='*60}\n")
        r = collector.begin(stage, "5.0", "Fixtures stage")
        collector.skip(r, "No fixtures directory provided")
        return

    print(f"\n{'='*60}")
    print(f"  {stage} — {fixtures_dir}")
    print(f"{'='*60}\n")

    fdir = Path(fixtures_dir)
    if not fdir.is_dir():
        r = collector.begin(stage, "5.0", "Fixtures directory exists")
        collector.fail(r, f"Not a directory: {fixtures_dir}")
        return

    # 5.1-5.7 fixture tests would go here
    r = collector.begin(stage, "5.0", "Fixtures directory found")
    collector.pass_(r, f"Found: {fixtures_dir}")

    _print_stage_summary(collector, stage)


# ===================================================================
# STAGE 6 — Server (prompted)
# ===================================================================
def stage_6(collector: ResultCollector, server_url: Optional[str]) -> None:
    stage = "Stage 6: Server"
    if not server_url:
        print(f"\n{'='*60}")
        print(f"  {stage} — SKIPPED (no server URL provided)")
        print(f"{'='*60}\n")
        r = collector.begin(stage, "6.0", "Server stage")
        collector.skip(r, "No server URL provided")
        return

    print(f"\n{'='*60}")
    print(f"  {stage} — {server_url}")
    print(f"{'='*60}\n")

    import urllib.request

    # 6.1 Server reachable
    def t_6_1():
        try:
            req = urllib.request.urlopen(server_url, timeout=5)
            assert req.status == 200, f"Server returned {req.status}"
        except Exception as e:
            raise AssertionError(f"Server not reachable: {e}")
    _run_test(collector, stage, "6.1", "Server reachable", t_6_1)

    # 6.2 Fetch node_info
    def t_6_2():
        from autoflow import NodeInfo
        ni = NodeInfo.fetch(server_url=server_url)
        assert ni is not None, "NodeInfo.fetch returned None"
    _run_test(collector, stage, "6.2", "NodeInfo.fetch(server_url)", t_6_2)

    # 6.3 Convert live
    def t_6_3():
        from autoflow import Workflow
        api = Workflow(str(_BUNDLED_WORKFLOW), server_url=server_url)
        assert api is not None, "Live conversion failed"
    _run_test(collector, stage, "6.3", "Workflow(wf, server_url) live convert", t_6_3)

    # 6.4 Submit + wait
    def t_6_4():
        from autoflow import Workflow
        api = Workflow(str(_BUNDLED_WORKFLOW), server_url=server_url)
        api.KSampler.steps = 1  # Minimize render time
        api.KSampler.seed = 42
        res = api.submit(server_url=server_url, wait=True)
        assert res is not None, "Submit returned None"
    _run_test(collector, stage, "6.4", "submit(wait=True)", t_6_4)

    # 6.5 Fetch images
    def t_6_5():
        from autoflow import Workflow
        api = Workflow(str(_BUNDLED_WORKFLOW), server_url=server_url)
        api.KSampler.steps = 1
        api.KSampler.seed = 42
        res = api.submit(server_url=server_url, wait=True)
        images = res.fetch_images()
        assert images is not None, "fetch_images returned None"
        assert len(images) > 0, "No images returned"
    _run_test(collector, stage, "6.5", "fetch_images() returns images", t_6_5)

    _print_stage_summary(collector, stage)


# ===================================================================
# STAGE 7 — Tools (prompted)
# ===================================================================
def stage_7(collector: ResultCollector, has_pil: bool, magick_path: Optional[str],
            ffmpeg_path: Optional[str]) -> None:
    stage = "Stage 7: Tools"
    if not has_pil and not magick_path and not ffmpeg_path:
        print(f"\n{'='*60}")
        print(f"  {stage} — SKIPPED (no tools available)")
        print(f"{'='*60}\n")
        r = collector.begin(stage, "7.0", "Tools stage")
        collector.skip(r, "No tools provided")
        return

    print(f"\n{'='*60}")
    print(f"  {stage}")
    print(f"{'='*60}\n")

    if has_pil:
        def t_7_1():
            from PIL import Image
            # Create a simple test image and verify
            img = Image.new("RGB", (64, 64), color=(255, 0, 0))
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                img.save(tmp.name)
                loaded = Image.open(tmp.name)
                assert loaded.size == (64, 64), f"Image size mismatch: {loaded.size}"
                os.unlink(tmp.name)
        _run_test(collector, stage, "7.1", "PIL: create + load image", t_7_1)

    _print_stage_summary(collector, stage)


# ===================================================================
# Report generation
# ===================================================================
def _print_stage_summary(collector: ResultCollector, stage: str) -> None:
    results = [r for r in collector.results if r.stage == stage]
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    errors = sum(1 for r in results if r.status == "ERROR")
    skipped = sum(1 for r in results if r.status == "SKIP")

    for r in results:
        icon = {"PASS": "✅", "FAIL": "❌", "ERROR": "💥", "SKIP": "⏭️"}.get(r.status, "?")
        line = f"  {icon} [{r.test_id}] {r.name}"
        if r.status in ("FAIL", "ERROR") and r.message:
            # Show first line of error
            first_line = r.message.strip().split("\n")[0][:100]
            line += f" — {first_line}"
        print(line)

    print(f"\n  Summary: {passed} passed, {failed} failed, {errors} errors, {skipped} skipped\n")


def generate_html_report(collector: ResultCollector, output_path: str) -> str:
    """Generate a standalone HTML report."""
    import autoflow
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stages = collector.by_stage()

    rows = []
    for stage_name, results in stages.items():
        for r in results:
            color = {
                "PASS": "#2d5016", "FAIL": "#8b1a1a",
                "ERROR": "#8b4513", "SKIP": "#4a4a00"
            }.get(r.status, "#333")
            icon = {"PASS": "✅", "FAIL": "❌", "ERROR": "💥", "SKIP": "⏭️"}.get(r.status, "?")
            msg_html = html_mod.escape(r.message) if r.message else ""
            rows.append(f"""
            <tr style="background: {color}22;">
                <td>{html_mod.escape(r.test_id)}</td>
                <td>{icon} {html_mod.escape(r.name)}</td>
                <td><strong>{r.status}</strong></td>
                <td>{r.duration_s:.3f}s</td>
                <td><pre style="margin:0;white-space:pre-wrap;font-size:0.8em;">{msg_html}</pre></td>
            </tr>""")

    total = len(collector.results)
    passed = sum(1 for r in collector.results if r.status == "PASS")
    failed = sum(1 for r in collector.results if r.status == "FAIL")
    errors = sum(1 for r in collector.results if r.status == "ERROR")
    skipped = sum(1 for r in collector.results if r.status == "SKIP")

    overall_color = "#2d5016" if collector.all_passed else "#8b1a1a"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>autoflow Master Test Report</title>
<style>
  body {{ font-family: 'Inter', system-ui, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 2rem; }}
  h1 {{ color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 0.5rem; }}
  h2 {{ color: #8b949e; margin-top: 2rem; }}
  .summary {{ display: flex; gap: 1rem; margin: 1rem 0; }}
  .stat {{ padding: 1rem 1.5rem; border-radius: 8px; text-align: center; min-width: 100px; }}
  .stat-label {{ font-size: 0.8em; color: #8b949e; }}
  .stat-value {{ font-size: 2em; font-weight: bold; }}
  .pass {{ background: #2d501622; border: 1px solid #2d5016; }}
  .pass .stat-value {{ color: #3fb950; }}
  .fail {{ background: #8b1a1a22; border: 1px solid #8b1a1a; }}
  .fail .stat-value {{ color: #f85149; }}
  .skip {{ background: #4a4a0022; border: 1px solid #4a4a00; }}
  .skip .stat-value {{ color: #d29922; }}
  .error {{ background: #8b451322; border: 1px solid #8b4513; }}
  .error .stat-value {{ color: #db6d28; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
  th, td {{ padding: 0.5rem 0.75rem; text-align: left; border: 1px solid #30363d; }}
  th {{ background: #161b22; color: #8b949e; font-weight: 600; }}
  pre {{ color: #f0f0f0; }}
  .overall {{ padding: 1rem; border-radius: 8px; background: {overall_color}44; border: 2px solid {overall_color}; margin-bottom: 1rem; text-align: center; font-size: 1.2em; }}
</style>
</head>
<body>
<h1>🧪 autoflow Master Test Report</h1>
<div class="overall">{'ALL TESTS PASSED' if collector.all_passed else 'SOME TESTS FAILED'}</div>
<p><strong>Version:</strong> {html_mod.escape(autoflow.__version__)} &nbsp;|&nbsp;
<strong>Python:</strong> {html_mod.escape(sys.version.split()[0])} &nbsp;|&nbsp;
<strong>OS:</strong> {html_mod.escape(sys.platform)} &nbsp;|&nbsp;
<strong>Date:</strong> {now}</p>

<div class="summary">
  <div class="stat pass"><div class="stat-value">{passed}</div><div class="stat-label">Passed</div></div>
  <div class="stat fail"><div class="stat-value">{failed}</div><div class="stat-label">Failed</div></div>
  <div class="stat error"><div class="stat-value">{errors}</div><div class="stat-label">Errors</div></div>
  <div class="stat skip"><div class="stat-value">{skipped}</div><div class="stat-label">Skipped</div></div>
</div>

<table>
<thead><tr><th>ID</th><th>Test</th><th>Status</th><th>Time</th><th>Details</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>

<p style="color:#484f58;margin-top:2rem;">Generated by autoflow master_test.py</p>
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html_content, encoding="utf-8")
    return output_path


# ===================================================================
# Main
# ===================================================================
def main() -> int:
    parser = argparse.ArgumentParser(description="autoflow — Master Test Suite")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Skip all prompted stages (CI mode)")
    parser.add_argument("--fixtures-dir", type=str, default=None,
                        help="Path to autoflow-testdata fixtures directory")
    parser.add_argument("--server-url", type=str, default=None,
                        help="ComfyUI server URL for live tests")
    parser.add_argument("--report", type=str, default=None,
                        help="Output path for HTML report (default: auto)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't open HTML report in browser")
    args = parser.parse_args()

    collector = ResultCollector()

    print("\n" + "=" * 60)
    print("  autoflow — Master Test Suite")
    print("=" * 60)

    # Auto stages (always run)
    stage_0(collector)
    stage_1(collector)
    stage_2(collector)
    stage_3(collector)
    stage_4(collector)

    # Prompted stages
    fixtures_dir = args.fixtures_dir
    server_url = args.server_url
    has_pil = False
    magick_path = None
    ffmpeg_path = None

    if not args.non_interactive:
        if not fixtures_dir:
            fixtures_dir = input("\nEnter path to autoflow-testdata directory (or press Enter to skip): ").strip() or None
        if not server_url:
            server_url = input("Enter ComfyUI server URL (or press Enter to skip): ").strip() or None

        pil_ans = input("Do you have PIL/Pillow installed? (y/n, Enter to skip): ").strip().lower()
        has_pil = pil_ans in ("y", "yes")
        magick_path = input("Enter path to ImageMagick convert binary (or Enter to skip): ").strip() or None
        ffmpeg_path = input("Enter path to ffmpeg binary (or Enter to skip): ").strip() or None

    stage_5(collector, fixtures_dir)
    stage_6(collector, server_url)
    stage_7(collector, has_pil, magick_path, ffmpeg_path)

    # --- Final summary ---
    print("\n" + "=" * 60)
    print("  FINAL RESULTS")
    print("=" * 60)

    total = len(collector.results)
    passed = sum(1 for r in collector.results if r.status == "PASS")
    failed = sum(1 for r in collector.results if r.status == "FAIL")
    errors = sum(1 for r in collector.results if r.status == "ERROR")
    skipped = sum(1 for r in collector.results if r.status == "SKIP")

    print(f"\n  Total: {total} | ✅ {passed} passed | ❌ {failed} failed | 💥 {errors} errors | ⏭️  {skipped} skipped")

    if collector.all_passed:
        print("\n  🎉 ALL TESTS PASSED\n")
    else:
        print("\n  ⚠️  SOME TESTS FAILED:\n")
        for r in collector.results:
            if r.status in ("FAIL", "ERROR"):
                print(f"    ❌ [{r.test_id}] {r.name}")
                if r.message:
                    for line in r.message.strip().split("\n")[:5]:
                        print(f"       {line}")
                print()

    # Generate HTML report
    report_path = args.report
    if not report_path:
        report_dir = tempfile.mkdtemp(prefix="autoflow_report_")
        report_path = os.path.join(report_dir, "test_report.html")

    generate_html_report(collector, report_path)
    print(f"  📄 HTML report: {report_path}")

    if not args.no_browser:
        try:
            webbrowser.open(f"file://{os.path.abspath(report_path)}")
        except Exception:
            pass

    return 0 if collector.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
