"""Phase 8 — Docs: execute fenced code blocks from documentation and verify they run.

Instead of launching docs-test.py as a single subprocess (which provides no
progress feedback and can hang silently), this phase imports the docs-test
registry directly and runs each example block as its own individual test.
This gives:
  - per-block progress in the terminal and HTML dashboard
  - per-block timing
  - immediate identification of which block hangs or fails

Enabled via --docs flag.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness import (  # noqa: E402
    ResultCollector, _run_test, _print_stage_summary, SkipTest,
)

STAGE = "Phase 8: Docs"

_DOCS_TEST_SCRIPT = _REPO_ROOT / "examples" / "code" / "docs-test.py"


def _import_docs_test():
    """Import docs-test.py as a module without running main()."""
    spec = importlib.util.spec_from_file_location("_docs_test", str(_DOCS_TEST_SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    # Must register before exec so @dataclass can resolve the module
    sys.modules["_docs_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_with_timeout(fn, timeout_s=30):
    """Run fn() in a daemon thread with a timeout.

    Returns (result, error, timed_out).
    """
    result_box: list = [None]
    error_box: list = [None]

    def worker():
        try:
            result_box[0] = fn()
        except Exception as e:
            error_box[0] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=timeout_s)

    if t.is_alive():
        return None, None, True  # timed out
    return result_box[0], error_box[0], False


def run(collector: ResultCollector, **kwargs) -> None:
    stage = STAGE
    print(f"\n{'='*60}")
    print(f"  {stage}")
    print(f"{'='*60}\n")

    run_docs = kwargs.get("docs", False)

    if not run_docs:
        def t_8_skip():
            raise SkipTest("Docs tests disabled (use --docs to enable)")
        _run_test(collector, stage, "8.0", "Docs tests (skipped: --docs not set)", t_8_skip)
        _print_stage_summary(collector, stage)
        return

    if not _DOCS_TEST_SCRIPT.is_file():
        def t_8_miss():
            raise SkipTest(f"docs-test.py not found at {_DOCS_TEST_SCRIPT}")
        _run_test(collector, stage, "8.0", "docs-test.py missing", t_8_miss)
        _print_stage_summary(collector, stage)
        return

    # --- Import docs-test module ---
    try:
        docs_mod = _import_docs_test()
    except Exception as e:
        def t_8_import_fail(e=e):
            raise AssertionError(f"Failed to import docs-test.py: {e}")
        _run_test(collector, stage, "8.0", "Import docs-test.py", t_8_import_fail)
        _print_stage_summary(collector, stage)
        return

    # --- Register doc blocks ---
    docs_mod._register_doc_blocks(
        docs_dir=docs_mod.DOCS_DIR,
        include_langs=["python", "bash", "json", "text", ""],
    )

    if not docs_mod.EXAMPLES:
        def t_8_no_blocks():
            raise SkipTest("No doc blocks found")
        _run_test(collector, stage, "8.0", "No doc blocks registered", t_8_no_blocks)
        _print_stage_summary(collector, stage)
        return

    # --- Resolve fixture paths ---
    fixtures_dir = kwargs.get("fixtures_dir")
    workflow_path: Optional[Path] = None
    node_info_path: Optional[Path] = None
    image_path: Optional[Path] = None

    if fixtures_dir:
        logo_basic = Path(fixtures_dir) / "logo-basic"
        wf = logo_basic / "workflow.json"
        ni = logo_basic / "node-info.json"
        gt = logo_basic / "ground-truth"
        if wf.is_file():
            workflow_path = wf
        if ni.is_file():
            node_info_path = ni
        if gt.is_dir():
            pngs = sorted(gt.glob("*.png"))
            if pngs:
                image_path = pngs[0]

    # Fallbacks for workflow
    if not workflow_path:
        for candidate in [
            _REPO_ROOT / "default.json",
            _REPO_ROOT / "examples" / "workflows" / "workflow.json",
        ]:
            if candidate.is_file():
                workflow_path = candidate
                break

    if not workflow_path:
        def t_8_no_wf():
            raise SkipTest("No workflow.json found — need fixtures/logo-basic/workflow.json or repo root default.json")
        _run_test(collector, stage, "8.0", "Docs setup", t_8_no_wf)
        _print_stage_summary(collector, stage)
        return

    # Fallback for node_info
    if not node_info_path:
        ni_default = _REPO_ROOT / "node_info.json"
        if ni_default.is_file():
            node_info_path = ni_default

    out_dir = Path(kwargs.get("output_dir", _REPO_ROOT / "autoflow-test-suite" / "outputs")) / "_docs_sandbox"

    # Setup report
    wf_str = str(workflow_path.relative_to(_REPO_ROOT)) if workflow_path and str(workflow_path).startswith(str(_REPO_ROOT)) else str(workflow_path)
    ni_str = str(node_info_path.relative_to(_REPO_ROOT)) if node_info_path and str(node_info_path).startswith(str(_REPO_ROOT)) else str(node_info_path)
    img_str = str(image_path.relative_to(_REPO_ROOT)) if image_path and str(image_path).startswith(str(_REPO_ROOT)) else str(image_path)

    def t_8_0():
        return {
            "input": f"{len(docs_mod.EXAMPLES)} doc blocks registered",
            "output": f"workflow={wf_str}, node_info={ni_str}, image={img_str}",
            "result": "✓ ready",
        }
    _run_test(collector, stage, "8.0", "Docs setup", t_8_0)

    # --- Build shared kwargs for each block ---
    server_url = kwargs.get("server_url")
    shared_kwargs: Dict[str, Any] = dict(
        exec_python=True,
        run_cli=False,
        allow_network=bool(server_url),
        server_url=server_url,
        prompt_env=False,
        strict_network=False,
        workflow=workflow_path,
        node_info=node_info_path,
        image=image_path,
        out=out_dir,
        verbose=False,
    )

    # --- Run each doc block as its own test ---
    sorted_labels = sorted(docs_mod.EXAMPLES.keys())
    for idx, label in enumerate(sorted_labels, start=1):
        ex = docs_mod.EXAMPLES[label]
        test_id = f"8.{idx}"

        # Per-block timeout
        per_block_timeout = 15
        if ex.needs_network:
            per_block_timeout = 30

        def make_test_fn(ex=ex, label=label, timeout=per_block_timeout):
            def test_fn():
                result, error, timed_out = _run_with_timeout(
                    lambda: docs_mod._call_with_supported_kwargs(ex.fn, shared_kwargs),
                    timeout_s=timeout,
                )

                if timed_out:
                    raise AssertionError(f"Timed out after {timeout}s")
                if error:
                    raise error

                status = "exec" if ex.can_exec_python else "compile"
                return {
                    "input": f"{ex.doc_file}#{ex.block_index}:{ex.lang}",
                    "output": status,
                    "result": f"✓ {ex.lang} ok",
                }
            return test_fn

        desc = label
        if ex.needs_network:
            desc += " [net]"

        _run_test(collector, stage, test_id, desc, make_test_fn())

    _print_stage_summary(collector, stage)
