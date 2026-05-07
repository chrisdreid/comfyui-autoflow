"""Phase 10 — MCP server: optional sub-package, server build, tool registration,
session store, graft engine, error parser.

Skips cleanly when the optional ``mcp`` package is not installed (the core
``comfyui-autograph`` library is intentionally zero-dependency, so ``mcp`` only
ships as part of the ``[mcp]`` extra).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness import ResultCollector, _run_test  # noqa: E402

STAGE = "Phase 10: MCP server"

EXPECTED_TOOLS = {
    # Server / introspection
    "comfyui_status", "list_node_types", "describe_node_type", "list_models",
    # Inspection / editing
    "inspect_workflow", "convert_workflow", "validate_workflow", "set_workflow_values",
    # Builder
    "load_workflow", "create_workflow", "add_node", "connect_nodes",
    "disconnect_input", "remove_node", "merge_workflow", "save_workflow", "get_workflow",
    # Sessions
    "list_sessions", "close_session",
    # Library / sources
    "list_workflow_sources", "search_local_workflows", "load_local_workflow",
    # Execution
    "run_workflow", "queue_workflow", "get_history", "interrupt",
    # Files / outputs
    "upload_file", "fetch_outputs", "list_outputs",
}


def _mcp_available() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Synthetic flow fixtures
# ---------------------------------------------------------------------------


def _empty_workspace() -> dict:
    return {
        "last_node_id": 0,
        "last_link_id": 0,
        "nodes": [],
        "links": [],
        "groups": [],
        "config": {},
        "extra": {},
        "version": 0.4,
    }


def _make_loader_node(node_id: int) -> dict:
    return {
        "id": node_id,
        "type": "CheckpointLoaderSimple",
        "pos": [0, 0],
        "size": [315, 100],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": [
            {"name": "MODEL", "type": "MODEL", "slot_index": 0, "links": []},
            {"name": "CLIP",  "type": "CLIP",  "slot_index": 1, "links": []},
            {"name": "VAE",   "type": "VAE",   "slot_index": 2, "links": []},
        ],
        "properties": {"Node name for S&R": "CheckpointLoaderSimple"},
        "widgets_values": ["model.safetensors"],
    }


def _make_save_node(node_id: int) -> dict:
    return {
        "id": node_id,
        "type": "SaveImage",
        "pos": [800, 0],
        "size": [315, 100],
        "flags": {},
        "order": 1,
        "mode": 0,
        "inputs": [
            {"name": "images", "type": "IMAGE", "link": None},
        ],
        "outputs": [],
        "properties": {"Node name for S&R": "SaveImage"},
        "widgets_values": ["ComfyUI"],
    }


def _make_decode_fragment() -> dict:
    """A tiny workflow fragment: one VAEDecode node with dangling LATENT/VAE inputs and an IMAGE output."""
    fragment = _empty_workspace()
    fragment["last_node_id"] = 99
    fragment["nodes"] = [
        {
            "id": 99,
            "type": "VAEDecode",
            "pos": [400, 0],
            "size": [210, 50],
            "flags": {},
            "order": 0,
            "mode": 0,
            "inputs": [
                {"name": "samples", "type": "LATENT", "link": None},
                {"name": "vae",     "type": "VAE",    "link": None},
            ],
            "outputs": [
                {"name": "IMAGE", "type": "IMAGE", "slot_index": 0, "links": []},
            ],
            "properties": {"Node name for S&R": "VAEDecode"},
            "widgets_values": [],
        }
    ]
    return fragment


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


def run(collector: ResultCollector, **kwargs) -> None:
    stage = STAGE
    print(f"\n{'='*60}")
    print(f"  {stage}")
    print(f"{'='*60}\n")

    # 10.1  Importing autograph alone must NOT pull in mcp.
    def t_10_1():
        import subprocess
        code = (
            "import sys; "
            "import autograph; "
            "leaked = [m for m in sys.modules if m == 'mcp' or m.startswith('mcp.')]; "
            "print('LEAKED:' + ','.join(leaked))"
        )
        out = subprocess.check_output(
            [sys.executable, "-c", code], stderr=subprocess.STDOUT, text=True
        ).strip()
        leaked = out.split("LEAKED:", 1)[-1]
        assert leaked == "", f"importing autograph leaked mcp modules: {leaked}"
        return {
            "input": "import autograph (subprocess)",
            "output": "no mcp.* modules in sys.modules",
            "result": "OK",
        }
    _run_test(collector, stage, "10.1", "core import does not load mcp", t_10_1)

    if not _mcp_available():
        def t_skip():
            return {
                "input": "import mcp",
                "output": "mcp not installed",
                "result": "SKIP — install with `pip install \"comfyui-autograph[mcp]\"`",
            }
        _run_test(collector, stage, "10.2", "mcp extra installed", t_skip)
        return

    # 10.2  autograph.mcp imports cleanly when [mcp] is present.
    def t_10_2():
        import autograph.mcp as _amcp
        assert hasattr(_amcp, "build_server"), "build_server missing"
        assert hasattr(_amcp, "main"), "main missing"
        return {
            "input": "import autograph.mcp",
            "output": "build_server / main present",
            "result": "OK",
        }
    _run_test(collector, stage, "10.2", "autograph.mcp imports", t_10_2)

    # 10.3  Server builds and registers all 28 expected tools.
    def t_10_3():
        from autograph.mcp import build_server
        server = build_server()
        manager = server._tool_manager
        names = set(manager._tools.keys())
        missing = EXPECTED_TOOLS - names
        unexpected = names - EXPECTED_TOOLS
        assert not missing, f"missing tools: {sorted(missing)}"
        # Unexpected isn't fatal but we want to know if the surface drifts.
        return {
            "input": "build_server() tool registration",
            "output": f"{len(names)} tools registered (expected {len(EXPECTED_TOOLS)}); unexpected={sorted(unexpected)}",
            "result": "OK",
        }
    _run_test(collector, stage, "10.3", "all 28 MCP tools registered", t_10_3)

    # 10.4  Resources and prompts registered.
    def t_10_4():
        from autograph.mcp import build_server
        server = build_server()
        rmgr = server._resource_manager
        pmgr = server._prompt_manager
        resources = list(getattr(rmgr, "_templates", {}).keys()) + list(getattr(rmgr, "_resources", {}).keys())
        prompts = list(getattr(pmgr, "_prompts", {}).keys())
        assert any("node-info" in r for r in resources)
        assert any("history" in r for r in resources)
        assert any("outputs" in r for r in resources)
        for required_prompt in ("text_to_image", "diagnose_workflow", "vibe_build_workflow"):
            assert required_prompt in prompts, f"prompt missing: {required_prompt}"
        return {
            "input": "build_server() resources + prompts",
            "output": f"resources={len(resources)}, prompts={sorted(prompts)}",
            "result": "OK",
        }
    _run_test(collector, stage, "10.4", "MCP resources and prompts registered", t_10_4)

    # 10.5  Console-script and python -m entry points agree.
    def t_10_5():
        from autograph.mcp import main as mcp_main
        from autograph.mcp.__main__ import main as dunder_main
        assert mcp_main is dunder_main, "console-script and __main__ diverge"
        return {
            "input": "console-script entry resolution",
            "output": "autograph.mcp.main is autograph.mcp.__main__.main",
            "result": "OK",
        }
    _run_test(collector, stage, "10.5", "console-script entry point", t_10_5)

    # 10.6  Session store: load workflow, write checkpoint, list, close.
    def t_10_6():
        from autograph.mcp.session import SessionStore
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(session_dir=Path(tmp))
            wf_path = Path(tmp) / "wf.json"
            wf_path.write_text(json.dumps(_empty_workspace()), encoding="utf-8")
            session = store.load_from(wf_path, label="test")
            wid = session.id
            assert session.checkpoint_path is not None and session.checkpoint_path.exists(), "checkpoint not written on load"
            session.flow._flow["nodes"].append(_make_loader_node(1))
            store.touch(wid)
            cp = json.loads(session.checkpoint_path.read_text(encoding="utf-8"))
            assert len(cp.get("nodes", [])) == 1, "checkpoint did not capture mutation"
            listed = store.list()
            assert any(s["workflow_id"] == wid for s in listed), "session not in list()"
            close_result = store.close(wid, delete_checkpoint=True)
            assert close_result.get("ok"), f"close failed: {close_result}"
            assert not session.checkpoint_path.exists(), "checkpoint file should have been deleted"
        return {
            "input": "SessionStore lifecycle",
            "output": "load → mutate → checkpoint → list → close (with checkpoint delete)",
            "result": "OK",
        }
    _run_test(collector, stage, "10.6", "session store load/checkpoint/close", t_10_6)

    # 10.7  Graft engine: insert a fragment with renumbering and auto-stitching.
    def t_10_7():
        import autograph
        from autograph.mcp.graft import merge_into_flow

        # Active flow: a CheckpointLoaderSimple (id=1) and a SaveImage (id=2).
        active = _empty_workspace()
        active["last_node_id"] = 2
        active["nodes"] = [_make_loader_node(1), _make_save_node(2)]
        flow = autograph.Flow(active)

        report = merge_into_flow(flow, _make_decode_fragment())

        # The fragment had id=99; with last_node_id=2 it should renumber to 99+2 = 101.
        added_ids = [int(n["node_id"]) for n in report["added_nodes"]]
        assert added_ids == [101], f"expected renumbered id 101, got {added_ids}"

        # VAEDecode has dangling LATENT (no LATENT producer in active) → still dangling.
        # VAEDecode has dangling VAE (CheckpointLoaderSimple has unique VAE output) → auto-wired.
        # VAEDecode IMAGE output → SaveImage has unique free IMAGE input → auto-wired.
        wires = report["auto_connected"]
        assert any(w["slot_type"] == "VAE" for w in wires), f"VAE not auto-wired: {wires}"
        assert any(w["slot_type"] == "IMAGE" for w in wires), f"IMAGE not auto-wired: {wires}"

        still_in = report["still_dangling_inputs"]
        assert any(d["input_type"] == "LATENT" for d in still_in), \
            f"LATENT input should still be dangling (no producer in active flow): {still_in}"

        return {
            "input": "merge_into_flow(VAEDecode fragment)",
            "output": (
                f"added={added_ids}, auto-wired={[w['slot_type'] for w in wires]}, "
                f"still_dangling={[d['input_type'] for d in still_in]}"
            ),
            "result": "OK",
        }
    _run_test(collector, stage, "10.7", "graft engine renumber + auto-stitch", t_10_7)

    # 10.8  Error parser: structured /prompt 400 body.
    def t_10_8():
        from autograph.mcp.errors import parse_prompt_error_body
        body = json.dumps(
            {
                "error": {"type": "prompt_outputs_failed", "message": "Validation failed"},
                "node_errors": {
                    "5": {
                        "class_type": "KSampler",
                        "errors": [
                            {"type": "value-not-in-list", "message": "seed not in range", "details": {}}
                        ],
                    }
                },
            }
        )
        errors = parse_prompt_error_body(body, default_status=400)
        assert len(errors) >= 2, f"expected top-level + node error, got {errors}"
        node_err = next((e for e in errors if e.get("node_id") == "5"), None)
        assert node_err is not None and node_err.get("class_type") == "KSampler", \
            f"missing structured KSampler error: {errors}"
        return {
            "input": "parse_prompt_error_body(<400 body>)",
            "output": f"{len(errors)} structured errors, including node 5/KSampler",
            "result": "OK",
        }
    _run_test(collector, stage, "10.8", "error parser handles /prompt 400", t_10_8)

    # 10.9  Workflow library + sources catalog.
    def t_10_9():
        from autograph.mcp import library as lib
        sources = lib.ONLINE_SOURCES
        assert isinstance(sources, list) and any("github.com/comfyanonymous" in s.get("url", "") for s in sources), \
            "expected the official ComfyUI examples GitHub URL in ONLINE_SOURCES"
        entries = lib.discover()
        names = [e.name for e in entries]
        assert any(n == "txt2img-basic" for n in names), f"bundled txt2img-basic missing from library: {names}"
        return {
            "input": "library.discover() + ONLINE_SOURCES",
            "output": f"{len(entries)} library entries; {len(sources)} curated sources",
            "result": "OK",
        }
    _run_test(collector, stage, "10.9", "library discovery + sources catalog", t_10_9)
