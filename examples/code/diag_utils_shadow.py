#!/usr/bin/env python3
"""Diagnostic: find what shadows ComfyUI's utils package.

Run from ComfyUI root with PYTHONPATH including both autoflow and ComfyUI:
    python diag_utils_shadow.py
"""
import sys
import os

print("=== sys.path ===")
for i, p in enumerate(sys.path):
    marker = ""
    u = os.path.join(p, "utils")
    uf = os.path.join(p, "utils.py")
    if os.path.isdir(u):
        has_init = os.path.exists(os.path.join(u, "__init__.py"))
        marker = f"  <-- has utils/ (pkg={has_init})"
    if os.path.isfile(uf):
        marker = f"  <-- has utils.py (FILE, will shadow!)"
    print(f"  [{i}] {p}{marker}")

print("\n=== Before ComfyUI imports ===")
print(f"  'utils' in sys.modules: {'utils' in sys.modules}")

try:
    import comfy.samplers
    import comfy.sd
    from nodes import NODE_CLASS_MAPPINGS
except ImportError as e:
    print(f"  ComfyUI import failed: {e}")
    sys.exit(1)

print(f"\n=== After ComfyUI imports ===")
print(f"  'utils' in sys.modules: {'utils' in sys.modules}")
print(f"  NODE_CLASS_MAPPINGS count: {len(NODE_CLASS_MAPPINGS)}")

if 'utils' in sys.modules:
    m = sys.modules['utils']
    print(f"  sys.modules['utils'] = {m}")
    print(f"    __file__: {getattr(m, '__file__', 'N/A')}")
    print(f"    __path__: {getattr(m, '__path__', 'N/A')}")
    print(f"    is_package: {hasattr(m, '__path__')}")

print("\n=== Direct import test ===")
# Remove cached entry to test fresh
if 'utils' in sys.modules:
    cached = sys.modules.pop('utils')
    print(f"  Removed cached: {cached}")
if 'utils.install_util' in sys.modules:
    sys.modules.pop('utils.install_util')

try:
    import utils
    print(f"  import utils OK: {utils.__file__}")
    print(f"    is_package: {hasattr(utils, '__path__')}")
    from utils import install_util
    print(f"  utils.install_util OK")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== Check if comfy.utils poisoned sys.modules ===")
import comfy.utils
print(f"  comfy.utils.__file__: {comfy.utils.__file__}")
# Some packages do 'sys.modules[__name__] = ...' tricks
print(f"  sys.modules.get('utils'): {sys.modules.get('utils')}")
print(f"  sys.modules.get('comfy.utils'): {sys.modules.get('comfy.utils')}")
