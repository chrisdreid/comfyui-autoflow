#!/usr/bin/env python3
"""
Autoflow pre-publish test runner.

Usage (from repo root):
    python examples/unittests/run_tests.py              # Run all tests
    python examples/unittests/run_tests.py --quick      # Self-contained tests only (no fixtures needed)
    python examples/unittests/run_tests.py --verbose    # Show individual test names
    python examples/unittests/run_tests.py --list       # Just list what would run

This script discovers and runs all unittest files under examples/unittests/.
Tests that require fixture files will SKIP gracefully if fixtures are absent.
"""

import argparse
import subprocess
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parents[1]

# Tests that need no fixture files at all
SELF_CONTAINED = [
    "test_dag.py",
    "test_dir_and_widget_introspection.py",
    "test_map_helpers.py",
    "test_model_layer_env_switch.py",
    "test_save_formatting.py",
    "test_submit_terminal_event.py",
    "test_ws_events.py",
]

# Not a unittest.TestCase — excluded from discovery
EXCLUDED = [
    "test_error_handling.py",
]

ALL_TESTS = sorted([
    p.name for p in TEST_DIR.glob("test_*.py")
    if p.name not in EXCLUDED
])

FIXTURE_TESTS = sorted(set(ALL_TESTS) - set(SELF_CONTAINED))


def list_tests(subset):
    print(f"\n{'='*60}")
    print(f"  {len(subset)} test files would run:")
    print(f"{'='*60}\n")
    for name in subset:
        tag = "🟢" if name in SELF_CONTAINED else "🟡"
        print(f"  {tag}  {name}")
    print(f"\n  🟢 = self-contained    🟡 = needs fixtures\n")


def run_tests(subset, verbose=False):
    print(f"\n{'='*60}")
    print(f"  autoflow test runner — {len(subset)} files")
    print(f"{'='*60}\n")

    failed = []
    passed = []
    skipped_files = []

    for name in subset:
        module = f"examples.unittests.{name[:-3]}"
        cmd = [sys.executable, "-m", "unittest", module]
        if verbose:
            cmd.append("-v")

        tag = "🟢" if name in SELF_CONTAINED else "🟡"
        print(f"  {tag}  {name} ... ", end="", flush=True)

        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )

        stderr = result.stderr.strip()

        # Check if all tests were skipped
        if "skipped=" in stderr and "FAILED" not in stderr and result.returncode == 0:
            print("SKIPPED (fixtures missing)")
            skipped_files.append(name)
        elif result.returncode == 0:
            # Extract counts from stderr
            # e.g. "Ran 3 tests in 0.004s\n\nOK"
            lines = stderr.splitlines()
            ran_line = [l for l in lines if l.startswith("Ran ")]
            count = ran_line[0] if ran_line else "?"
            print(f"OK  ({count})")
            passed.append(name)
        else:
            print("FAILED")
            failed.append((name, stderr))

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS: {len(passed)} passed, {len(skipped_files)} skipped, {len(failed)} failed")
    print(f"{'='*60}\n")

    if skipped_files:
        print("  Skipped (fixtures missing):")
        for n in skipped_files:
            print(f"    - {n}")
        print()

    if failed:
        print("  FAILURES:")
        for name, err in failed:
            print(f"\n  ❌ {name}:")
            # Show last 15 lines of stderr
            for line in err.splitlines()[-15:]:
                print(f"     {line}")
        print()
        return 1

    if not failed:
        print("  ✅ All tests passed!\n")
        return 0

    return 1


def main():
    parser = argparse.ArgumentParser(description="autoflow test runner")
    parser.add_argument("--quick", action="store_true",
                        help="Run only self-contained tests (no fixtures needed)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show individual test names")
    parser.add_argument("--list", action="store_true",
                        help="List test files without running")
    args = parser.parse_args()

    subset = SELF_CONTAINED if args.quick else ALL_TESTS

    if args.list:
        list_tests(subset)
        return 0

    return run_tests(subset, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
