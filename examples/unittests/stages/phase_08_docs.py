"""Phase 8 — Docs: execute fenced code blocks from documentation and verify they run.

This phase wraps the existing docs-test.py script, capturing per-block output
for dashboard rendering.  Enabled via --docs flag.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness import (  # noqa: E402
    ResultCollector, _run_test, _print_stage_summary, SkipTest,
)

STAGE = "Phase 8: Docs"

_DOCS_TEST_SCRIPT = _REPO_ROOT / "examples" / "docs-test.py"


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

    # Run the docs-test script as a subprocess and capture output
    def t_8_1():
        try:
            result = subprocess.run(
                [sys.executable, str(_DOCS_TEST_SCRIPT)],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(_REPO_ROOT),
            )
            stdout_lines = result.stdout.strip().split("\n") if result.stdout else []
            stderr_lines = result.stderr.strip().split("\n") if result.stderr else []

            if result.returncode != 0:
                err_tail = "\n".join(stderr_lines[-10:])
                raise AssertionError(
                    f"docs-test.py exited {result.returncode}:\n{err_tail}"
                )

            # Count passed / failed from stdout
            passed = sum(1 for l in stdout_lines if "✓" in l or "PASS" in l.upper())
            failed = sum(1 for l in stdout_lines if "✗" in l or "FAIL" in l.upper())

            return {
                "input": "docs-test.py",
                "output": f"{passed} passed, {failed} failed, {len(stdout_lines)} lines",
                "result": "✓ all blocks executed" if failed == 0 else f"⚠ {failed} failures",
            }
        except subprocess.TimeoutExpired:
            raise AssertionError("docs-test.py timed out (120s)")
    _run_test(collector, stage, "8.1", "Execute docs-test.py", t_8_1)

    _print_stage_summary(collector, stage)
