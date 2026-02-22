#!/usr/bin/env python3
"""
autoflow — Modular Test Suite
==============================

Slim orchestrator that auto-discovers ``stages/stage_*.py`` modules and
runs them in order.  Every stage exports ``run(collector, **kwargs)``
and uses the shared ``harness`` infrastructure.

Usage::

    # Auto stages only (CI-safe, no prompts)
    python examples/unittests/main.py --non-interactive

    # Full interactive
    python examples/unittests/main.py

    # With CLI overrides (skip prompts)
    python examples/unittests/main.py --fixtures-dir /path/to/testdata --server-url http://localhost:8188

    # Run a specific stage
    python examples/unittests/main.py --stage 16

    # List all stages
    python examples/unittests/main.py --list
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Ensure repo root is on sys.path
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Ensure the unittests directory is also on sys.path so ``import harness``
# works from stage modules.
_UNITTEST_DIR = Path(__file__).resolve().parent
if str(_UNITTEST_DIR) not in sys.path:
    sys.path.insert(0, str(_UNITTEST_DIR))

from harness import (  # noqa: E402
    ResultCollector,
    _print_stage_summary,
    generate_html_report,
    clean_output_dir,
    discover_fixtures,
    copy_ground_truth,
    _BUNDLED_WORKFLOW,
)


# ---------------------------------------------------------------------------
# Stage discovery
# ---------------------------------------------------------------------------
_STAGES_DIR = _UNITTEST_DIR / "stages"


def _discover_stages() -> List[Tuple[int, str, Any]]:
    """Return sorted list of (stage_num, module_name, module) for every stage_*.py."""
    stages: List[Tuple[int, str, Any]] = []
    for path in sorted(_STAGES_DIR.glob("stage_*.py")):
        stem = path.stem  # e.g. stage_08_flow_core
        parts = stem.split("_", 2)  # ["stage", "08", "flow_core"]
        if len(parts) < 2:
            continue
        try:
            num = int(parts[1])
        except ValueError:
            continue
        mod_name = f"stages.{stem}"
        mod = importlib.import_module(mod_name)
        stages.append((num, mod_name, mod))
    return stages


# ---------------------------------------------------------------------------
# Prompted stages: fixtures, server, PIL
# ---------------------------------------------------------------------------
def _resolve_prompted_kwargs(args) -> Dict[str, Any]:
    """Resolve interactive prompts for fixtures_dir, server_url, has_pil."""
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
            ans = input("ComfyUI server URL [http://localhost:8188] (Enter for localhost, 'skip' to skip): ").strip()
            if ans.lower() == "skip":
                server_url = None
            elif ans:
                server_url = ans
            else:
                server_url = "http://localhost:8188"

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
        try:
            import PIL  # noqa: F401
            has_pil = True
        except ImportError:
            pass

    return {
        "fixtures_dir": fixtures_dir,
        "server_url": server_url,
        "has_pil": has_pil,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="autoflow — Modular Test Suite")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Skip all prompted stages (CI mode)")
    parser.add_argument("--fixtures-dir", type=str, default=None,
                        help="Path to fixtures directory")
    parser.add_argument("--server-url", type=str, default=None,
                        help="ComfyUI server URL for live tests")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory for results")
    parser.add_argument("--port", type=int, default=None,
                        help="Serve results on this HTTP port")
    parser.add_argument("--no-clean", action="store_true",
                        help="Don't wipe output directory before running")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't open report in browser")
    parser.add_argument("--stage", type=int, nargs="*", default=None,
                        help="Run only specific stage number(s)")
    parser.add_argument("--list", action="store_true",
                        help="List all discovered stages and exit")
    args = parser.parse_args()

    # --- Discover stages ---
    all_stages = _discover_stages()

    if args.list:
        print(f"\n{'='*60}")
        print("  Discovered Stage Modules")
        print(f"{'='*60}\n")
        for num, mod_name, mod in all_stages:
            stage_label = getattr(mod, "STAGE", mod_name)
            print(f"  {num:3d}  {stage_label}")
        print()
        return 0

    # --- Resolve output directory ---
    if args.output_dir:
        output_dir = Path(args.output_dir)
    elif args.fixtures_dir:
        output_dir = Path(args.fixtures_dir).parent / "outputs"
    else:
        output_dir = _REPO_ROOT / "autoflow-test-suite" / "outputs"

    if not args.no_clean:
        clean_output_dir(output_dir)
        print(f"  🧹 Cleaned output directory: {output_dir}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    # --- Resolve prompted args ---
    prompted = _resolve_prompted_kwargs(args)

    # Build kwargs passed to every stage
    stage_kwargs: Dict[str, Any] = {
        "output_dir": output_dir,
        **prompted,
    }

    # --- Filter stages ---
    if args.stage is not None:
        stage_set = set(args.stage)
        run_stages = [(n, m, mod) for n, m, mod in all_stages if n in stage_set]
        if not run_stages:
            print(f"  ⚠️  No stages matched: {args.stage}")
            return 1
    else:
        run_stages = all_stages

    # --- Run stages ---
    collector = ResultCollector()

    print(f"\n{'='*60}")
    print("  autoflow — Modular Test Suite")
    print(f"{'='*60}")
    print(f"  Running {len(run_stages)} stage(s)...\n")

    t0 = time.monotonic()
    for num, mod_name, mod in run_stages:
        try:
            ret = mod.run(collector, **stage_kwargs)
            # Stage 5 returns discovered fixtures — pass them to later stages
            if isinstance(ret, list) and ret:
                stage_kwargs["fixtures"] = ret
        except Exception as exc:
            # If a stage itself blows up, record a single ERROR for it.
            from harness import _run_test
            stage_label = getattr(mod, "STAGE", mod_name)
            _run_test(collector, stage_label, f"{num}.0",
                      f"Stage {num} module load/run",
                      lambda: (_ for _ in ()).throw(exc))
    elapsed = time.monotonic() - t0

    # --- Final summary ---
    print(f"\n{'='*60}")
    print("  FINAL RESULTS")
    print(f"{'='*60}")

    total = len(collector.results)
    passed = sum(1 for r in collector.results if r.status == "PASS")
    failed = sum(1 for r in collector.results if r.status == "FAIL")
    errors = sum(1 for r in collector.results if r.status == "ERROR")
    skipped = sum(1 for r in collector.results if r.status == "SKIP")

    print(f"\n  Total: {total} | ✅ {passed} passed | ❌ {failed} failed | 💥 {errors} errors | ⏭️  {skipped} skipped")
    print(f"  ⏱️  Elapsed: {elapsed:.1f}s")

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

    # --- HTML report ---
    # Prefer fixtures from stage runs (they have generated_images/progress_log),
    # fall back to fresh discovery for ground-truth-only display.
    fixtures = stage_kwargs.get("fixtures") or discover_fixtures(prompted.get("fixtures_dir", "") or "")
    report_path = str(output_dir / "index.html")
    run_config = {
        "server_url": prompted.get("server_url"),
        "fixtures_dir": prompted.get("fixtures_dir"),
        "has_pil": prompted.get("has_pil"),
        "output_dir": str(output_dir),
    }
    generate_html_report(collector, report_path, fixtures=fixtures or None,
                         run_config=run_config)
    print(f"  📄 Report: {report_path}")

    # --- Optional HTTP server ---
    if args.port:
        port = args.port
        print(f"\n  🌐 Serving results at http://localhost:{port}")
        print(f"     Serving from: {output_dir}")
        print(f"     Press Ctrl+C to stop\n")

        if not args.no_browser:
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
