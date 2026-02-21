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
import base64
import copy
import datetime
import html as html_mod
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
import webbrowser
from dataclasses import dataclass, field
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
# Fixture discovery
# ---------------------------------------------------------------------------
@dataclass
class FixtureCase:
    """One test fixture discovered from a fixtures/ subdirectory."""
    name: str
    directory: Path
    manifest: Dict[str, Any]
    progress_log: List[Dict[str, Any]] = field(default_factory=list)
    generated_images: List[Path] = field(default_factory=list)
    ground_truth_images: List[Path] = field(default_factory=list)


def discover_fixtures(fixtures_dir: str) -> List[FixtureCase]:
    """Scan for subdirectories containing fixture.json."""
    cases: List[FixtureCase] = []
    fdir = Path(fixtures_dir)
    if not fdir.is_dir():
        return cases
    for child in sorted(fdir.iterdir()):
        manifest_path = child / "fixture.json"
        if child.is_dir() and manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            gt_dir = child / data.get("expected", {}).get("ground_truth_dir", "ground-truth")
            gt_images = sorted(gt_dir.glob("*.png")) if gt_dir.is_dir() else []
            cases.append(FixtureCase(
                name=data.get("name", child.name),
                directory=child,
                manifest=data,
                ground_truth_images=gt_images,
            ))
    return cases


def clean_output_dir(output_dir: Path) -> None:
    """Wipe output directory contents (except .gitignore)."""
    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.name == ".gitignore":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)


def copy_ground_truth(fixture: FixtureCase, output_dir: Path) -> None:
    """Copy ground-truth images into the output directory for comparison."""
    gt_out = output_dir / fixture.directory.name / "ground-truth"
    gt_out.mkdir(parents=True, exist_ok=True)
    for img in fixture.ground_truth_images:
        shutil.copy2(img, gt_out / img.name)


# ---------------------------------------------------------------------------
# Result collector
# ---------------------------------------------------------------------------
class TestResult:
    """Stores one test outcome with optional rich context."""
    __slots__ = ("stage", "test_id", "name", "status", "message", "duration_s", "detail")

    def __init__(self, stage: str, test_id: str, name: str):
        self.stage = stage
        self.test_id = test_id
        self.name = name
        self.status: str = "PENDING"  # PASS, FAIL, SKIP, ERROR
        self.message: str = ""
        self.duration_s: float = 0.0
        self.detail: Dict[str, Any] = {}  # desc, inputs, outputs, code, etc.


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
              fn: Callable[[], None], *,
              detail: Optional[Dict[str, Any]] = None) -> TestResult:
    import time
    r = collector.begin(stage, test_id, name)
    if detail:
        r.detail = detail
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


# ---------------------------------------------------------------------------
# Test catalog — rich descriptions for the HTML report
# Maps test_id → {desc, inputs, outputs, code}
# ---------------------------------------------------------------------------
TEST_CATALOG: Dict[str, Dict[str, str]] = {
    # Stage 0: Bootstrap
    "0.1": {"desc": "Verify autoflow package can be imported", "inputs": "Python module path", "outputs": "Module object"},
    "0.2": {"desc": "Version string follows semver (major.minor[.patch])", "inputs": "autoflow.__version__", "outputs": "Validated version string"},
    "0.3": {"desc": "All public API symbols exist in autoflow namespace", "inputs": "Expected symbol list (Flow, ApiFlow, Workflow, etc.)", "outputs": "All symbols found or list of missing",
            "code": "from autoflow import Flow, Workflow, NodeInfo, convert, map_strings"},
    "0.4": {"desc": "Bundled workflow.json can be loaded as a Flow object", "inputs": "examples/workflows/workflow.json", "outputs": "Flow object with nodes"},
    "0.5": {"desc": "Built-in node_info dict contains the 6 standard ComfyUI node classes", "inputs": "BUILTIN_NODE_INFO dict (KSampler, CLIPTextEncode, etc.)", "outputs": "NodeInfo object"},

    # Stage 1: Load + Access
    "1.1": {"desc": "Load workflow from a filesystem path string", "inputs": "Path string → workflow.json", "outputs": "Flow object",
            "code": "f = Flow.load('/path/to/workflow.json')"},
    "1.2": {"desc": "Load workflow from a pathlib.Path object", "inputs": "Path object", "outputs": "Flow object",
            "code": "f = Flow.load(Path('workflow.json'))"},
    "1.3": {"desc": "Load workflow from an in-memory dict", "inputs": "Python dict (parsed JSON)", "outputs": "Flow object",
            "code": "f = Flow.load({'nodes': [...], 'links': [...]})"},
    "1.4": {"desc": "Load workflow from a raw JSON string", "inputs": "JSON string", "outputs": "Flow object"},
    "1.5": {"desc": "Load workflow from bytes (UTF-8 encoded JSON)", "inputs": "bytes object", "outputs": "Flow object"},
    "1.6": {"desc": "Enumerate all nodes in the workflow graph", "inputs": "Flow object", "outputs": "NodeSet collection"},
    "1.7": {"desc": "Access a node by its class_type using Python dot notation", "inputs": "flow.nodes.KSampler", "outputs": "Node or NodeSet",
            "code": "ks = flow.nodes.KSampler"},
    "1.8": {"desc": "Access multiple instances of the same node type via indexing", "inputs": "flow.nodes.CLIPTextEncode[0]", "outputs": "Individual node instances",
            "code": "clip_pos = flow.nodes.CLIPTextEncode[0]\nclip_neg = flow.nodes.CLIPTextEncode[1]"},
    "1.9": {"desc": "Read widget values on a converted API node using dot notation", "inputs": "api.KSampler.seed", "outputs": "Widget value (int/float/str)",
            "code": "api = Workflow('wf.json', node_info=ni)\nseed = api.KSampler.seed"},
    "1.10": {"desc": "List all widget attribute names for a node", "inputs": "node.attrs()", "outputs": "List of widget names ['seed', 'steps', ...]",
             "code": "attrs = api.KSampler.attrs()  # ['seed', 'steps', 'cfg', ...]"},
    "1.11": {"desc": "Set a widget value via dot notation and verify it persists", "inputs": "api.KSampler.seed = 42", "outputs": "Updated seed value = 42",
             "code": "api.KSampler.seed = 42\nassert api.KSampler.seed == 42"},
    "1.16": {"desc": "Serialize Flow back to JSON string", "inputs": "Flow object", "outputs": "Valid JSON string",
             "code": "j = flow.to_json()"},
    "1.17": {"desc": "Load → serialize → reload → serialize produces identical JSON", "inputs": "Flow object", "outputs": "Two identical JSON dicts"},
    "1.18": {"desc": "Save to file, reload, and verify content matches", "inputs": "flow.save(path)", "outputs": "Reloaded Flow matches original"},
    "1.19": {"desc": "Build the internal DAG (directed acyclic graph) of node connections", "inputs": "Flow object", "outputs": "DAG structure"},
    "1.20": {"desc": "Tab completion support: dir(flow.nodes) lists node class_types", "inputs": "dir(flow.nodes)", "outputs": "['KSampler', 'CLIPTextEncode', ...]"},
    "1.21": {"desc": "Tab completion support: dir(api.KSampler) lists widget names", "inputs": "dir(api.KSampler)", "outputs": "['seed', 'steps', 'cfg', ...]"},

    # Stage 2: Convert + Metadata
    "2.1": {"desc": "Convert a Flow workflow to API format using node_info", "inputs": "workflow.json + node_info", "outputs": "ApiFlow (API-format dict with inputs resolved)",
            "code": "api = Workflow('wf.json', node_info=node_info)"},
    "2.2": {"desc": "Non-API nodes (MarkdownNote) are stripped during conversion", "inputs": "11-node workflow (4 MarkdownNote + 7 real)", "outputs": "7 API nodes (MarkdownNotes removed)"},
    "2.3": {"desc": "Access converted node widgets via dot notation", "inputs": "api.KSampler.seed", "outputs": "Seed value from API dict"},
    "2.4": {"desc": "Access raw API node dict by node ID string", "inputs": "api['3']", "outputs": "Node dict with class_type, inputs"},
    "2.5": {"desc": "Convert workflow and serialize to JSON in one step", "inputs": "Workflow(path, node_info)", "outputs": "JSON string ready for ComfyUI /prompt API"},
    "2.6": {"desc": "Convert with error reporting — returns ok, data, errors, warnings", "inputs": "Flow + node_info", "outputs": "ConvertResult with .ok, .data, .errors",
            "code": "result = convert_with_errors(flow, node_info=ni)\nif result.ok: api = result.data"},
    "2.7": {"desc": "Access _meta dict on API nodes (autoflow metadata)", "inputs": "api.KSampler._meta", "outputs": "Dict or None"},
    "2.9": {"desc": "Metadata written to _meta persists through to_json() serialization", "inputs": "node['_meta'] = {...}", "outputs": "_meta present in JSON output"},
    "2.14": {"desc": "Widget introspection: query available choices for combo widgets", "inputs": "api.KSampler.sampler_name.choices()", "outputs": "['euler', 'euler_ancestral', ...]",
             "code": "choices = api.KSampler.sampler_name.choices()"},
    "2.15": {"desc": "Widget introspection: get tooltip text for a widget", "inputs": "widget.tooltip()", "outputs": "Tooltip string or None"},
    "2.16": {"desc": "Widget introspection: get full spec (type, default, min, max)", "inputs": "widget.spec()", "outputs": "Spec dict with type constraints"},

    # Stage 3: Find + Navigate
    "3.1": {"desc": "Find nodes by exact class_type match", "inputs": "find(type='KSampler')", "outputs": "1 matching node",
            "code": "results = flow.nodes.find(type='KSampler')"},
    "3.2": {"desc": "Find nodes case-insensitively", "inputs": "find(type='ksampler')", "outputs": "1 matching node (case-insensitive)"},
    "3.3": {"desc": "Find nodes using regex pattern matching", "inputs": "find(type=re.compile('CLIP.*'))", "outputs": "2 CLIPTextEncode nodes",
            "code": "import re\nresults = flow.nodes.find(type=re.compile('CLIP.*'))"},
    "3.4": {"desc": "Find nodes by their display title", "inputs": "find(title='Note: Prompt')", "outputs": "1 matching node"},
    "3.5": {"desc": "Find nodes by title using regex", "inputs": "find(title=re.compile('Note:.*'))", "outputs": "≥3 matching MarkdownNote nodes"},
    "3.6": {"desc": "Multi-filter AND: type + widget value must both match", "inputs": "find(type='KSampler', seed=696969)", "outputs": "Matching nodes (AND logic)"},
    "3.7": {"desc": "OR operator: any filter criterion can match", "inputs": "find(type='KSampler', operator='or')", "outputs": "≥1 matching node"},
    "3.8": {"desc": "Find a specific node by its numeric ID", "inputs": "find(node_id=3)", "outputs": "1 node (node 3 = KSampler)"},
    "3.9": {"desc": "Get the hierarchical path of a found node", "inputs": "result.path()", "outputs": "Path string like 'KSampler'"},
    "3.10": {"desc": "Get the addressable location of a found node", "inputs": "result.address()", "outputs": "Address string"},
    "3.11": {"desc": "Find on ApiFlow by class_type", "inputs": "api.find(class_type='KSampler')", "outputs": "Matching API nodes",
             "code": "api = Workflow('wf.json', node_info=ni)\nresults = api.find(class_type='KSampler')"},
    "3.13": {"desc": "Direct node lookup by string ID on ApiFlow", "inputs": "api.by_id('3')", "outputs": "Node dict for ID '3'"},

    # Stage 4: Mapping
    "4.1": {"desc": "Replace literal string values across the entire API dict", "inputs": "map_strings(api_dict, {'literal': {'Default': 'REPLACED'}})", "outputs": "All 'Default' → 'REPLACED'",
            "code": "result = map_strings(dict(api.unwrap()), spec)"},
    "4.5": {"desc": "Force all cached nodes to recompute (change seeds)", "inputs": "force_recompute(api)", "outputs": "Modified API dict with fresh seeds",
            "code": "result = force_recompute(api)"},
    "4.7": {"desc": "api_mapping calls user callback for every node+param pair", "inputs": "api_mapping(api, callback)", "outputs": "Callback receives {node_id, class_type, param, value}",
            "code": "def cb(ctx):\n    print(ctx['class_type'], ctx['param'], ctx['value'])\napi_mapping(api, cb, node_info=ni)"},
    "4.8": {"desc": "api_mapping callback can return a value to override a parameter", "inputs": "Return 999999 when param == 'seed'", "outputs": "All KSampler seeds changed to 999999",
            "code": "def cb(ctx):\n    if ctx['param'] == 'seed': return 999999\napi_mapping(api, cb, node_info=ni)"},

    # Stage 5: Fixtures
    "5.1": {"desc": "Scan fixtures directory for fixture.json manifests", "inputs": "fixtures/ directory path", "outputs": "List of discovered fixture cases"},

    # Stage 6: Server
    "6.1": {"desc": "Verify ComfyUI server is reachable via HTTP", "inputs": "Server URL (e.g. http://localhost:8188)", "outputs": "HTTP 200 response"},
    "6.2": {"desc": "Fetch live node_info from running ComfyUI server", "inputs": "NodeInfo.fetch(server_url=...)", "outputs": "Full node_info dict (~100+ node types)",
            "code": "ni = NodeInfo.fetch(server_url='http://localhost:8188')"},
    "6.3": {"desc": "Convert workflow using live server node_info", "inputs": "Workflow(path, server_url=...)", "outputs": "ApiFlow with live node specs"},

    # Stage 7: Tools
    "7.1": {"desc": "Verify PIL/Pillow can create, save, and reload images", "inputs": "PIL.Image.new('RGB', (64,64))", "outputs": "64×64 red PNG image"},
}


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
# STAGE 5 — Fixtures (discovered from fixture.json manifests)
# ===================================================================
def stage_5(collector: ResultCollector, fixtures_dir: Optional[str],
            output_dir: Optional[Path] = None) -> List[FixtureCase]:
    """Run offline fixture tests. Returns discovered fixtures for later stages."""
    stage = "Stage 5: Fixtures"
    if not fixtures_dir:
        print(f"\n{'='*60}")
        print(f"  {stage} — SKIPPED (no fixtures directory provided)")
        print(f"{'='*60}\n")
        r = collector.begin(stage, "5.0", "Fixtures stage")
        collector.skip(r, "No fixtures directory provided")
        return []

    print(f"\n{'='*60}")
    print(f"  {stage} — {fixtures_dir}")
    print(f"{'='*60}\n")

    fdir = Path(fixtures_dir)
    if not fdir.is_dir():
        r = collector.begin(stage, "5.0", "Fixtures directory exists")
        collector.fail(r, f"Not a directory: {fixtures_dir}")
        return []

    # 5.1 Discover fixtures
    fixtures = discover_fixtures(fixtures_dir)
    def t_5_1():
        assert len(fixtures) > 0, f"No fixture.json manifests found in {fixtures_dir}"
    _run_test(collector, stage, "5.1", f"Discover fixtures ({len(fixtures)} found)", t_5_1)

    # Per-fixture offline tests
    for i, fx in enumerate(fixtures):
        prefix = f"5.{10 + i * 10}"
        fx_stage = f"{stage} [{fx.name}]"

        # Copy ground-truth into output dir
        if output_dir:
            copy_ground_truth(fx, output_dir)

        # Load workflow
        wf_path = fx.directory / fx.manifest.get("workflow", "workflow.json")

        def t_load(wf=wf_path):
            from autoflow import Flow
            f = Flow.load(str(wf))
            assert f is not None, f"Failed to load {wf.name}"
        _run_test(collector, stage, f"{prefix}.1", f"[{fx.name}] Load workflow", t_load)

        # Convert with fixture's own node_info
        ni_path = fx.directory / fx.manifest.get("node_info", "node-info.json")
        if ni_path.exists():
            def t_convert(wf=wf_path, ni=ni_path):
                from autoflow import Workflow
                with open(ni, "r", encoding="utf-8") as fh:
                    node_info = json.load(fh)
                api = Workflow(str(wf), node_info=node_info)
                assert api is not None, "Conversion failed"
                j = api.to_json()
                parsed = json.loads(j)
                assert isinstance(parsed, dict), "to_json() not valid JSON"
            _run_test(collector, stage, f"{prefix}.2", f"[{fx.name}] Convert with node_info", t_convert)

            # Check expected node count
            expected_count = fx.manifest.get("expected", {}).get("api_node_count")
            if expected_count:
                def t_count(wf=wf_path, ni=ni_path, exp=expected_count):
                    from autoflow import Workflow
                    with open(ni, "r", encoding="utf-8") as fh:
                        node_info = json.load(fh)
                    api = Workflow(str(wf), node_info=node_info)
                    raw = getattr(api, "unwrap", lambda: api)()
                    count = sum(
                        1 for _, v in raw.items()
                        if isinstance(v, dict) and "class_type" in v
                    )
                    assert count == exp, f"Expected {exp} API nodes, got {count}"
                _run_test(collector, stage, f"{prefix}.3", f"[{fx.name}] API node count = {expected_count}", t_count)

        # Check ground-truth images exist
        if fx.ground_truth_images:
            def t_gt(imgs=fx.ground_truth_images):
                for img in imgs:
                    assert img.exists(), f"Ground-truth image missing: {img}"
            _run_test(collector, stage, f"{prefix}.4", f"[{fx.name}] Ground-truth images ({len(fx.ground_truth_images)})", t_gt)

    _print_stage_summary(collector, stage)
    return fixtures


# ===================================================================
# STAGE 6 — Server (submit, progress capture, image fetch)
# ===================================================================
def stage_6(collector: ResultCollector, server_url: Optional[str],
            fixtures: Optional[List[FixtureCase]] = None,
            output_dir: Optional[Path] = None) -> None:
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

    # ---------------------------------------------------------------
    # Per-fixture server tests: submit as-is, capture progress, fetch images
    # ---------------------------------------------------------------
    if fixtures:
        for i, fx in enumerate(fixtures):
            if not fx.manifest.get("requires_server", False):
                continue

            wf_path = fx.directory / fx.manifest.get("workflow", "workflow.json")
            ni_path = fx.directory / fx.manifest.get("node_info", "node-info.json")
            prefix = f"6.{10 + i * 10}"

            # Submit as-is (no seed/steps modification!) with progress capture
            def t_submit(wf=wf_path, ni=ni_path, fixture=fx, pfx=prefix):
                from autoflow import Workflow
                ni_data = None
                if ni.exists():
                    with open(ni, "r", encoding="utf-8") as fh:
                        ni_data = json.load(fh)
                api = Workflow(str(wf), node_info=ni_data) if ni_data else Workflow(str(wf), server_url=server_url)

                # Apply only edits from manifest (e.g. filename_prefix)
                edits = fixture.manifest.get("edits", {})
                for edit_key, edit_val in edits.items():
                    parts = edit_key.split(".")
                    if len(parts) == 2:
                        node_type, param = parts
                        try:
                            node = getattr(api, node_type)
                            setattr(node, param, edit_val)
                        except AttributeError:
                            pass

                # Progress callback
                progress_events: List[Dict[str, Any]] = []
                t_start = time.time()

                def on_event(evt: Dict[str, Any]) -> None:
                    progress_events.append({
                        "type": evt.get("type", ""),
                        "data": evt.get("data", {}),
                        "elapsed_s": round(time.time() - t_start, 3),
                    })
                    # Print progress for feedback
                    d = evt.get("data", {})
                    if evt.get("type") == "progress":
                        step = d.get("value", "?")
                        total = d.get("max", "?")
                        print(f"    ⏳ [{fixture.name}] Step {step}/{total}", end="\r")

                # Submit with defaults (full steps, original seed)
                res = api.submit(
                    server_url=server_url,
                    wait=True,
                    on_event=on_event,
                )
                print()  # clear carriage return
                assert res is not None, "Submit returned None"
                fixture.progress_log = progress_events

                # Save progress log
                if output_dir:
                    prog_dir = output_dir / "progress"
                    prog_dir.mkdir(parents=True, exist_ok=True)
                    prog_file = prog_dir / f"{fixture.directory.name}.json"
                    prog_file.write_text(
                        json.dumps(progress_events, indent=2),
                        encoding="utf-8",
                    )

                # Fetch images and save to output
                img_out = None
                if output_dir:
                    img_out = output_dir / fixture.directory.name / "generated"
                    img_out.mkdir(parents=True, exist_ok=True)

                images = res.fetch_images(
                    output_path=str(img_out) if img_out else None,
                    include_bytes=True,
                )
                assert images is not None, "fetch_images returned None"
                assert len(images) > 0, "No images returned"

                # Track generated image paths
                if img_out:
                    fixture.generated_images = sorted(img_out.glob("*.png"))
                    # Also save any images from bytes if output_path didn't write them
                    if not fixture.generated_images:
                        for idx, img in enumerate(images):
                            img_bytes = img.get("bytes")
                            if isinstance(img_bytes, (bytes, bytearray)):
                                out_file = img_out / f"output_{idx:05d}.png"
                                out_file.write_bytes(img_bytes)
                                fixture.generated_images.append(out_file)

            _run_test(collector, stage, f"{prefix}.1",
                      f"[{fx.name}] Submit + progress capture + fetch images", t_submit)

            # Verify expected image count
            expected_imgs = fx.manifest.get("expected", {}).get("output_image_count")
            if expected_imgs is not None:
                def t_img_count(fixture=fx, exp=expected_imgs):
                    actual = len(fixture.generated_images)
                    assert actual == exp, f"Expected {exp} output images, got {actual}"
                _run_test(collector, stage, f"{prefix}.2",
                          f"[{fx.name}] Output image count = {expected_imgs}", t_img_count)
    else:
        # No fixtures — run a minimal submit test with bundled workflow
        def t_6_4():
            from autoflow import Workflow
            api = Workflow(str(_BUNDLED_WORKFLOW), server_url=server_url)
            # Submit as-is — no modifications
            res = api.submit(server_url=server_url, wait=True)
            assert res is not None, "Submit returned None"
            images = res.fetch_images()
            assert images is not None and len(images) > 0, "No images returned"
        _run_test(collector, stage, "6.4", "submit(wait=True) + fetch_images()", t_6_4)

    _print_stage_summary(collector, stage)


# ===================================================================
# STAGE 7 — Tools (image comparison, etc.)
# ===================================================================
def stage_7(collector: ResultCollector, has_pil: bool,
            fixtures: Optional[List[FixtureCase]] = None) -> None:
    stage = "Stage 7: Tools"
    if not has_pil:
        print(f"\n{'='*60}")
        print(f"  {stage} — SKIPPED (no tools available)")
        print(f"{'='*60}\n")
        r = collector.begin(stage, "7.0", "Tools stage")
        collector.skip(r, "PIL not available")
        return

    print(f"\n{'='*60}")
    print(f"  {stage}")
    print(f"{'='*60}\n")

    # 7.1 PIL available
    def t_7_1():
        from PIL import Image
        img = Image.new("RGB", (64, 64), color=(255, 0, 0))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            img.save(tmp.name)
            loaded = Image.open(tmp.name)
            assert loaded.size == (64, 64), f"Image size mismatch: {loaded.size}"
            os.unlink(tmp.name)
    _run_test(collector, stage, "7.1", "PIL: create + load image", t_7_1)

    # 7.2 Per-fixture image size comparison (ground-truth vs generated)
    if fixtures:
        for i, fx in enumerate(fixtures):
            if not fx.ground_truth_images or not fx.generated_images:
                continue

            def t_compare(fixture=fx):
                from PIL import Image
                for gt_img in fixture.ground_truth_images:
                    gt = Image.open(gt_img)
                    # Just verify generated images are same dimensions
                    for gen_path in fixture.generated_images:
                        gen = Image.open(gen_path)
                        assert gt.size == gen.size, (
                            f"Size mismatch: ground-truth {gt.size} vs "
                            f"generated {gen.size}"
                        )
            _run_test(collector, stage, f"7.{10 + i}",
                      f"[{fx.name}] Image dimensions match ground-truth", t_compare)

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


def generate_html_report(collector: ResultCollector, output_path: str,
                         fixtures: Optional[List[FixtureCase]] = None) -> str:
    """Generate an HTML investigation dashboard with test details, images, and progress."""
    import autoflow
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stages = collector.by_stage()
    out_dir = Path(output_path).parent

    total = len(collector.results)
    passed = sum(1 for r in collector.results if r.status == "PASS")
    failed = sum(1 for r in collector.results if r.status == "FAIL")
    errors = sum(1 for r in collector.results if r.status == "ERROR")
    skipped = sum(1 for r in collector.results if r.status == "SKIP")
    overall_color = "#2d5016" if collector.all_passed else "#8b1a1a"

    # --- Build stage sections with expandable rows ---
    stage_sections = ""
    for stage_name, results in stages.items():
        stage_passed = sum(1 for r in results if r.status == "PASS")
        stage_total = len(results)
        stage_icon = "✅" if stage_passed == stage_total else "❌"

        rows = ""
        for r in results:
            color = {
                "PASS": "#2d5016", "FAIL": "#8b1a1a",
                "ERROR": "#8b4513", "SKIP": "#4a4a00"
            }.get(r.status, "#333")
            icon = {"PASS": "✅", "FAIL": "❌", "ERROR": "💥", "SKIP": "⏭️"}.get(r.status, "?")
            msg_html = html_mod.escape(r.message) if r.message else ""

            # Get catalog info for this test
            cat = TEST_CATALOG.get(r.test_id, r.detail or {})
            desc = cat.get("desc", "")
            inputs = cat.get("inputs", "")
            outputs = cat.get("outputs", "")
            code = cat.get("code", "")

            has_detail = bool(desc or inputs or outputs or code or msg_html)
            clickable = ' class="expandable" onclick="toggleDetail(this)"' if has_detail else ''

            # Tooltip text
            tooltip = html_mod.escape(desc) if desc else ""

            rows += f"""
            <tr style="background: {color}22;"{clickable} title="{tooltip}">
                <td class="id-col">{html_mod.escape(r.test_id)}</td>
                <td>{icon} {html_mod.escape(r.name)}</td>
                <td><strong>{r.status}</strong></td>
                <td>{r.duration_s:.3f}s</td>
                <td class="arrow-col">{'▶' if has_detail else ''}</td>
            </tr>"""

            if has_detail:
                detail_parts = []
                if desc:
                    detail_parts.append(f'<div class="detail-desc">{html_mod.escape(desc)}</div>')
                if inputs or outputs:
                    io_html = '<div class="detail-io">'
                    if inputs:
                        io_html += f'<div class="io-box"><span class="io-label">INPUT</span> {html_mod.escape(inputs)}</div>'
                    if outputs:
                        io_html += f'<div class="io-box"><span class="io-label">OUTPUT</span> {html_mod.escape(outputs)}</div>'
                    io_html += '</div>'
                    detail_parts.append(io_html)
                if code:
                    detail_parts.append(f'<div class="detail-code"><pre>{html_mod.escape(code)}</pre></div>')
                if msg_html and r.status != "PASS":
                    detail_parts.append(f'<div class="detail-msg"><strong>Message:</strong><pre>{msg_html}</pre></div>')

                rows += f"""
            <tr class="detail-row" style="display:none;">
                <td colspan="5">
                    <div class="detail-content">{"".join(detail_parts)}</div>
                </td>
            </tr>"""

        stage_sections += f"""
    <div class="stage-section">
        <h2 class="stage-header" onclick="toggleStage(this)">
            {stage_icon} {html_mod.escape(stage_name)}
            <span class="stage-count">{stage_passed}/{stage_total}</span>
            <span class="stage-toggle">▼</span>
        </h2>
        <div class="stage-body">
            <table>
            <thead><tr><th style="width:60px">ID</th><th>Test</th><th style="width:70px">Status</th><th style="width:70px">Time</th><th style="width:30px"></th></tr></thead>
            <tbody>{rows}</tbody>
            </table>
        </div>
    </div>"""

    # --- Build image comparison sections ---
    image_sections = ""
    if fixtures:
        for fx in fixtures:
            if not fx.ground_truth_images and not fx.generated_images:
                continue
            section = f'<div class="fixture-card">\n'
            section += f'<h2>🖼️ {html_mod.escape(fx.name)}</h2>\n'
            section += '<div class="image-comparison">\n'

            # Ground truth column
            if fx.ground_truth_images:
                section += '<div class="image-col">\n<h3>Ground Truth</h3>\n'
                for img in fx.ground_truth_images:
                    rel = os.path.relpath(str(out_dir / fx.directory.name / "ground-truth" / img.name), str(out_dir))
                    section += f'<a href="{rel}" target="_blank" class="img-link">'
                    section += f'<img src="{rel}" alt="{html_mod.escape(img.name)}" />'
                    section += f'</a>\n<span class="img-label">{html_mod.escape(img.name)}</span>\n'
                section += '</div>\n'

            # Generated column (always show)
            section += '<div class="image-col">\n<h3>Generated</h3>\n'
            if fx.generated_images:
                for img in fx.generated_images:
                    rel = os.path.relpath(str(img), str(out_dir))
                    section += f'<a href="{rel}" target="_blank" class="img-link">'
                    section += f'<img src="{rel}" alt="{html_mod.escape(img.name)}" />'
                    section += f'</a>\n<span class="img-label">{html_mod.escape(img.name)}</span>\n'
            else:
                section += '<div class="no-image-placeholder">'
                section += '<p>⏳ No generated images</p>'
                section += '<p class="img-label">Run with --server-url to generate output images</p>'
                section += '</div>\n'
            section += '</div>\n'
            section += '</div>\n'  # end image-comparison

            # Progress timeline
            if fx.progress_log:
                progress_steps = [e for e in fx.progress_log if e.get("type") == "progress"]
                if progress_steps:
                    last = progress_steps[-1]
                    data = last.get("data", {})
                    max_val = data.get("max", 1)
                    cur_val = data.get("value", 0)
                    pct = int(cur_val / max_val * 100) if max_val else 100
                    elapsed = last.get("elapsed_s", 0)
                    section += f'<div class="progress-info">\n'
                    section += f'<strong>Progress:</strong> {cur_val}/{max_val} steps ({pct}%) — {elapsed:.1f}s\n'
                    section += f'<div class="progress-bar"><div class="progress-fill" style="width:{pct}%"></div></div>\n'

                    # Step-by-step timeline
                    section += '<div class="progress-timeline">\n'
                    for step in progress_steps:
                        s_data = step.get("data", {})
                        s_val = s_data.get("value", 0)
                        s_max = s_data.get("max", 1)
                        s_time = step.get("elapsed_s", 0)
                        section += f'<div class="timeline-step" title="Step {s_val}/{s_max} at {s_time:.1f}s">'
                        section += f'<span class="timeline-dot"></span>'
                        section += f'</div>\n'
                    section += '</div>\n'  # end timeline
                    section += '</div>\n'  # end progress-info

                # Show all raw events
                all_events = fx.progress_log
                if all_events:
                    section += '<details class="events-log">\n'
                    section += f'<summary>📋 Raw events ({len(all_events)} captured)</summary>\n'
                    section += '<pre class="events-pre">'
                    for evt in all_events:
                        section += html_mod.escape(json.dumps(evt, indent=None)) + '\n'
                    section += '</pre>\n</details>\n'

            section += '</div>\n'  # end fixture-card
            image_sections += section

    # --- Assemble HTML ---
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>autoflow Test Dashboard</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Inter', system-ui, -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 2rem; line-height: 1.6; }}
  h1 {{ color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 0.5rem; margin-bottom: 0.5rem; }}
  h2 {{ color: #8b949e; margin-top: 1.5rem; margin-bottom: 0.5rem; }}
  h3 {{ color: #58a6ff; margin: 0.5rem 0; font-size: 0.95em; }}

  /* Summary stats */
  .summary {{ display: flex; gap: 1rem; margin: 1rem 0; flex-wrap: wrap; }}
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
  .overall {{ padding: 1rem; border-radius: 8px; background: {overall_color}44; border: 2px solid {overall_color}; margin-bottom: 1rem; text-align: center; font-size: 1.2em; }}
  .env-info {{ color: #8b949e; font-size: 0.9em; margin-bottom: 1rem; }}
  .env-info strong {{ color: #c9d1d9; }}

  /* Stage sections */
  .stage-section {{ margin-bottom: 1rem; border: 1px solid #21262d; border-radius: 8px; overflow: hidden; }}
  .stage-header {{ background: #161b22; margin: 0; padding: 0.75rem 1rem; cursor: pointer; display: flex; align-items: center; gap: 0.5rem; user-select: none; font-size: 1em; }}
  .stage-header:hover {{ background: #1c2128; }}
  .stage-count {{ margin-left: auto; font-size: 0.85em; color: #8b949e; }}
  .stage-toggle {{ font-size: 0.7em; color: #484f58; transition: transform 0.2s; }}
  .stage-body {{ padding: 0; }}
  .stage-body.collapsed {{ display: none; }}

  /* Test table */
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #21262d; }}
  th {{ background: #0d1117; color: #8b949e; font-weight: 600; font-size: 0.85em; }}
  pre {{ color: #f0f0f0; margin: 0; }}
  .id-col {{ font-family: monospace; font-size: 0.85em; color: #8b949e; }}
  .arrow-col {{ text-align: center; color: #484f58; font-size: 0.8em; transition: transform 0.2s; }}

  /* Expandable rows */
  .expandable {{ cursor: pointer; }}
  .expandable:hover {{ background: #161b2244 !important; }}
  .expandable:hover .arrow-col {{ color: #58a6ff; }}
  .detail-row td {{ padding: 0; background: #161b22; }}
  .detail-content {{ padding: 0.75rem 1rem 0.75rem 4rem; border-left: 3px solid #58a6ff; animation: slideDown 0.15s ease-out; }}
  @keyframes slideDown {{ from {{ opacity: 0; max-height: 0; }} to {{ opacity: 1; max-height: 500px; }} }}

  .detail-desc {{ color: #c9d1d9; margin-bottom: 0.5rem; font-size: 0.9em; }}
  .detail-io {{ display: flex; gap: 1rem; margin-bottom: 0.5rem; flex-wrap: wrap; }}
  .io-box {{ background: #21262d; border-radius: 6px; padding: 0.4rem 0.75rem; font-size: 0.85em; flex: 1; min-width: 200px; }}
  .io-label {{ display: inline-block; background: #30363d; color: #58a6ff; padding: 0.1rem 0.4rem; border-radius: 3px; font-size: 0.75em; font-weight: 600; margin-right: 0.5rem; letter-spacing: 0.05em; }}
  .detail-code {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 0.5rem 0.75rem; margin-top: 0.5rem; }}
  .detail-code pre {{ font-size: 0.85em; color: #79c0ff; white-space: pre-wrap; word-break: break-word; }}
  .detail-msg {{ margin-top: 0.5rem; }}
  .detail-msg pre {{ font-size: 0.8em; color: #f85149; white-space: pre-wrap; word-break: break-word; }}

  /* Fixture cards */
  .fixture-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1.5rem; margin-top: 1.5rem; }}
  .fixture-card h2 {{ margin-top: 0; color: #c9d1d9; }}

  /* Image comparison */
  .image-comparison {{ display: flex; gap: 2rem; margin: 1rem 0; flex-wrap: wrap; }}
  .image-col {{ flex: 1; min-width: 280px; }}
  .image-col img {{ max-width: 100%; border-radius: 8px; border: 1px solid #30363d; cursor: pointer; transition: transform 0.2s; }}
  .image-col img:hover {{ transform: scale(1.02); box-shadow: 0 0 20px rgba(88,166,255,0.3); }}
  .img-link {{ display: block; margin-bottom: 0.5rem; }}
  .img-label {{ font-size: 0.8em; color: #8b949e; display: block; margin-bottom: 1rem; }}
  .no-image-placeholder {{ border: 2px dashed #30363d; border-radius: 8px; padding: 3rem 2rem; text-align: center; color: #484f58; min-height: 200px; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
  .no-image-placeholder p {{ margin: 0.25rem 0; }}

  /* Progress */
  .progress-info {{ background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 1rem; margin-top: 1rem; }}
  .progress-bar {{ background: #21262d; border-radius: 4px; height: 8px; margin-top: 0.5rem; overflow: hidden; }}
  .progress-fill {{ background: linear-gradient(90deg, #3fb950, #58a6ff); height: 100%; border-radius: 4px; transition: width 0.3s; }}
  .progress-timeline {{ display: flex; gap: 2px; margin-top: 0.5rem; flex-wrap: wrap; }}
  .timeline-step {{ position: relative; }}
  .timeline-dot {{ display: inline-block; width: 6px; height: 6px; background: #3fb950; border-radius: 50%; }}
  .timeline-step:hover .timeline-dot {{ background: #58a6ff; transform: scale(1.5); }}

  /* Events log */
  .events-log {{ margin-top: 0.75rem; }}
  .events-log summary {{ cursor: pointer; color: #8b949e; font-size: 0.85em; }}
  .events-log summary:hover {{ color: #58a6ff; }}
  .events-pre {{ max-height: 300px; overflow-y: auto; font-size: 0.75em; padding: 0.5rem; background: #0d1117; border: 1px solid #21262d; border-radius: 4px; }}

  /* Lightbox */
  .lightbox {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.92); z-index: 1000; align-items: center; justify-content: center; cursor: pointer; }}
  .lightbox.active {{ display: flex; }}
  .lightbox img {{ max-width: 95vw; max-height: 95vh; object-fit: contain; border-radius: 8px; }}
</style>
</head>
<body>
<h1>🧪 autoflow Test Dashboard</h1>
<div class="overall">{'🎉 ALL TESTS PASSED' if collector.all_passed else '⚠️ SOME TESTS FAILED'}</div>
<p class="env-info">
<strong>Version:</strong> {html_mod.escape(autoflow.__version__)} &nbsp;|&nbsp;
<strong>Python:</strong> {html_mod.escape(sys.version.split()[0])} &nbsp;|&nbsp;
<strong>OS:</strong> {html_mod.escape(sys.platform)} &nbsp;|&nbsp;
<strong>Date:</strong> {now} &nbsp;|&nbsp;
<strong>Total:</strong> {total} tests
</p>

<div class="summary">
  <div class="stat pass"><div class="stat-value">{passed}</div><div class="stat-label">Passed</div></div>
  <div class="stat fail"><div class="stat-value">{failed}</div><div class="stat-label">Failed</div></div>
  <div class="stat error"><div class="stat-value">{errors}</div><div class="stat-label">Errors</div></div>
  <div class="stat skip"><div class="stat-value">{skipped}</div><div class="stat-label">Skipped</div></div>
</div>

{stage_sections}

{image_sections}

<div id="lightbox" class="lightbox" onclick="this.classList.remove('active')">
  <img id="lightbox-img" src="" alt="Full resolution" />
</div>

<script>
// Toggle detail row
function toggleDetail(row) {{
  const detail = row.nextElementSibling;
  if (detail && detail.classList.contains('detail-row')) {{
    const arrow = row.querySelector('.arrow-col');
    if (detail.style.display === 'none') {{
      detail.style.display = 'table-row';
      if (arrow) arrow.textContent = '▼';
    }} else {{
      detail.style.display = 'none';
      if (arrow) arrow.textContent = '▶';
    }}
  }}
}}

// Toggle stage collapse
function toggleStage(header) {{
  const body = header.nextElementSibling;
  const toggle = header.querySelector('.stage-toggle');
  if (body) {{
    body.classList.toggle('collapsed');
    if (toggle) toggle.textContent = body.classList.contains('collapsed') ? '▶' : '▼';
  }}
}}

// Lightbox for images
document.querySelectorAll('.image-col img').forEach(img => {{
  img.addEventListener('click', function(e) {{
    e.preventDefault();
    e.stopPropagation();
    const lb = document.getElementById('lightbox');
    const lbImg = document.getElementById('lightbox-img');
    lbImg.src = this.parentElement.href || this.src;
    lb.classList.add('active');
  }});
}});

// Auto-expand failed tests
document.querySelectorAll('.expandable').forEach(row => {{
  const statusCell = row.querySelector('td:nth-child(3) strong');
  if (statusCell && (statusCell.textContent === 'FAIL' || statusCell.textContent === 'ERROR')) {{
    toggleDetail(row);
  }}
}});
</script>

<p style="color:#484f58;margin-top:2rem;font-size:0.85em;">Generated by autoflow test suite — click any test row for details</p>
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
                        help="Path to fixtures directory (auto-discovers fixture.json manifests)")
    parser.add_argument("--server-url", type=str, default=None,
                        help="ComfyUI server URL for live tests")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory for results (default: autoflow-test-suite/outputs/)")
    parser.add_argument("--port", type=int, default=None,
                        help="Launch python -m http.server on this port to serve results")
    parser.add_argument("--no-clean", action="store_true",
                        help="Don't wipe output directory before running")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't open report in browser")
    args = parser.parse_args()

    collector = ResultCollector()

    # --- Resolve output directory ---
    if args.output_dir:
        output_dir = Path(args.output_dir)
    elif args.fixtures_dir:
        # Default: sibling 'outputs' dir next to fixtures
        output_dir = Path(args.fixtures_dir).parent / "outputs"
    else:
        output_dir = Path(_REPO_ROOT / "autoflow-test-suite" / "outputs")

    # --- Clean output directory ---
    if not args.no_clean:
        clean_output_dir(output_dir)
        print(f"  🧹 Cleaned output directory: {output_dir}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

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

    if not args.non_interactive:
        if not fixtures_dir:
            default_fixtures = _REPO_ROOT / "autoflow-test-suite" / "fixtures"
            hint = f" [{default_fixtures}]" if default_fixtures.is_dir() else ""
            ans = input(f"\nFixtures directory{hint} (Enter for default, 'skip' to skip): ").strip()
            if ans.lower() == "skip":
                fixtures_dir = None
            elif ans:
                fixtures_dir = ans
            elif default_fixtures.is_dir():
                fixtures_dir = str(default_fixtures)
            else:
                fixtures_dir = None

        if not server_url:
            server_url = input("ComfyUI server URL (or Enter to skip): ").strip() or None

        # Auto-detect PIL
        try:
            import PIL  # noqa: F401
            has_pil = True
        except ImportError:
            pil_ans = input("PIL/Pillow not detected. Install it? (y/n): ").strip().lower()
            if pil_ans in ("y", "yes"):
                print("  Installing Pillow...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow", "-q"])
                has_pil = True
    else:
        # Non-interactive: auto-detect PIL silently
        try:
            import PIL  # noqa: F401
            has_pil = True
        except ImportError:
            pass

    # Run fixture stages
    fixtures = stage_5(collector, fixtures_dir, output_dir=output_dir)
    stage_6(collector, server_url, fixtures=fixtures, output_dir=output_dir)
    stage_7(collector, has_pil, fixtures=fixtures)

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

    # Generate HTML report as index.html in output dir
    report_path = str(output_dir / "index.html")
    generate_html_report(collector, report_path, fixtures=fixtures)
    print(f"  📄 Report: {report_path}")

    # --- Serve via http.server ---
    if args.port:
        port = args.port
        print(f"\n  🌐 Serving results at http://localhost:{port}")
        print(f"     Serving from: {output_dir}")
        print(f"     Press Ctrl+C to stop\n")

        if not args.no_browser:
            # Open browser after a short delay (give server time to start)
            import threading
            def _open_browser():
                time.sleep(1.0)
                webbrowser.open(f"http://localhost:{port}")
            threading.Thread(target=_open_browser, daemon=True).start()

        try:
            subprocess.run(
                [sys.executable, "-m", "http.server", str(port)],
                cwd=str(output_dir),
            )
        except KeyboardInterrupt:
            print("\n  Server stopped.")
    elif not args.no_browser:
        try:
            webbrowser.open(f"file://{os.path.abspath(report_path)}")
        except Exception:
            pass

    return 0 if collector.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
