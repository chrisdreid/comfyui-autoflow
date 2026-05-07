"""Phase 10 — MCP server: optional sub-package, server build, tool registration.

Skips cleanly when the optional ``mcp`` package is not installed (the core
``comfyui-autograph`` library is intentionally zero-dependency, so ``mcp`` only
ships as part of the ``[mcp]`` extra).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness import ResultCollector, _run_test  # noqa: E402

STAGE = "Phase 10: MCP server"


def _mcp_available() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


def run(collector: ResultCollector, **kwargs) -> None:
    stage = STAGE
    print(f"\n{'='*60}")
    print(f"  {stage}")
    print(f"{'='*60}\n")

    # 10.1  Importing autograph alone must NOT pull in mcp.
    def t_10_1():
        # Use a subprocess so a previously-loaded mcp module in this test run
        # doesn't taint the check.
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
        def t_10_2_skip():
            return {
                "input": "import mcp",
                "output": "mcp not installed",
                "result": "SKIP — install with `pip install \"comfyui-autograph[mcp]\"`",
            }
        _run_test(collector, stage, "10.2", "mcp extra installed", t_10_2_skip)
        return

    # 10.2  autograph.mcp module imports cleanly when mcp IS installed.
    def t_10_2():
        import autograph.mcp as _amcp
        assert hasattr(_amcp, "build_server"), "build_server missing"
        assert hasattr(_amcp, "main"), "main missing"
        return {
            "input": "import autograph.mcp",
            "output": f"build_server={_amcp.build_server}, main={_amcp.main}",
            "result": "OK",
        }
    _run_test(collector, stage, "10.2", "autograph.mcp imports", t_10_2)

    # 10.3  Server builds and registers all 15 expected tools.
    def t_10_3():
        from autograph.mcp import build_server
        server = build_server()
        # FastMCP exposes its registered tools via list_tools(); call it sync via the
        # underlying _tool_manager to avoid spinning up an event loop here.
        manager = getattr(server, "_tool_manager", None)
        names = sorted(manager._tools.keys()) if manager and hasattr(manager, "_tools") else []
        expected = {
            "comfyui_status", "list_node_types", "describe_node_type", "list_models",
            "inspect_workflow", "convert_workflow", "validate_workflow", "set_workflow_values",
            "run_workflow", "queue_workflow", "get_history", "interrupt",
            "upload_file", "fetch_outputs", "list_outputs",
        }
        missing = expected - set(names)
        assert not missing, f"missing tools: {sorted(missing)}"
        return {
            "input": "build_server() tool registration",
            "output": f"{len(names)} tools registered",
            "result": f"OK ({len(expected)} expected; all present)",
        }
    _run_test(collector, stage, "10.3", "all 15 MCP tools registered", t_10_3)

    # 10.4  Resources and prompts registered.
    def t_10_4():
        from autograph.mcp import build_server
        server = build_server()
        rmgr = getattr(server, "_resource_manager", None)
        pmgr = getattr(server, "_prompt_manager", None)
        resources = []
        if rmgr is not None:
            resources = list(getattr(rmgr, "_templates", {}).keys()) + list(getattr(rmgr, "_resources", {}).keys())
        prompts = list(getattr(pmgr, "_prompts", {}).keys()) if pmgr is not None else []
        assert any("node-info" in r for r in resources), f"node-info resource missing: {resources}"
        assert any("history" in r for r in resources), f"history resource missing: {resources}"
        assert any("outputs" in r for r in resources), f"outputs resource missing: {resources}"
        assert "text_to_image" in prompts, f"text_to_image prompt missing: {prompts}"
        assert "diagnose_workflow" in prompts, f"diagnose_workflow prompt missing: {prompts}"
        return {
            "input": "build_server() resources + prompts",
            "output": f"resources={resources}, prompts={prompts}",
            "result": "OK",
        }
    _run_test(collector, stage, "10.4", "MCP resources and prompts registered", t_10_4)

    # 10.5  Console script entry point resolves.
    def t_10_5():
        from autograph.mcp import main as mcp_main
        from autograph.mcp.__main__ import main as dunder_main
        assert mcp_main is dunder_main, "console-script and __main__ entry points diverge"
        return {
            "input": "console-script entry resolution",
            "output": "autograph.mcp.main == autograph.mcp.__main__.main",
            "result": "OK",
        }
    _run_test(collector, stage, "10.5", "comfyui-autograph-mcp entry point", t_10_5)
