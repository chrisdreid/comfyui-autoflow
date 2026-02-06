"""
Test fixture helpers.

These unit tests are intended to run in a few common developer layouts:

- This repo as a standalone checkout (fixtures may live in a local ignored dir)
- This repo checked out next to a ComfyUI repo that contains `../data/*.json`

We intentionally resolve fixture paths dynamically so tests do not require copying JSON
fixtures into the repo root.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[2]


def fixture_dir() -> Path:
    """
    Return the directory containing JSON fixtures for offline tests.

    Resolution order:
    - env AUTOFLOW_TESTDATA_DIR
    - repo-root / _testdata   (local, should be gitignored)
    - ../data                 (common layout when this repo lives next to ComfyUI)
    """
    env = os.environ.get("AUTOFLOW_TESTDATA_DIR")
    if isinstance(env, str) and env.strip():
        p = Path(env).expanduser().resolve()
        if p.is_dir():
            return p

    local = (REPO_ROOT / "_testdata").resolve()
    if local.is_dir():
        return local

    sibling = (REPO_ROOT.parent / "data").resolve()
    if sibling.is_dir():
        return sibling

    # Last resort: search upward a little for a `data/` folder.
    cur: Optional[Path] = REPO_ROOT
    for _ in range(3):
        if cur is None:
            break
        cand = (cur.parent / "data").resolve()
        if cand.is_dir():
            return cand
        cur = cur.parent if cur.parent != cur else None

    raise unittest.SkipTest(
        "Offline test fixtures not found. Set AUTOFLOW_TESTDATA_DIR, or create ./_testdata/, "
        "or place this repo next to a sibling ../data/ directory."
    )


def fixture_path(name: str) -> Path:
    """
    Return absolute path to a fixture file in fixture_dir().
    """
    base = fixture_dir()
    p = (base / name).resolve()
    if not p.is_file():
        raise unittest.SkipTest(f"Offline test fixture missing: {p}")
    return p


