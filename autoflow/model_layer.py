"""autoflow.model_layer

Internal model-layer selector.

Controlled by env var:
  AUTOFLOW_MODEL_LAYER=models|flowtree

Default is "flowtree" (experimental wrapper layer).

NOTE: This is an internal experiment switch; do not document in public docs.
"""

from __future__ import annotations

import os
from typing import Any, Tuple, Type


def model_layer_name() -> str:
    v = os.environ.get("AUTOFLOW_MODEL_LAYER", "flowtree")
    v = (v or "flowtree").strip().lower()
    if v in ("model", "models", "legacy"):
        return "models"
    if v in ("flowtree", "tree", "nav"):
        return "flowtree"
    # Fail fast so users don't think they're in a mode they aren't.
    raise ValueError("AUTOFLOW_MODEL_LAYER must be 'models' or 'flowtree'")


def get_models():
    name = model_layer_name()
    if name == "flowtree":
        from .flowtree import ApiFlow, Flow, ObjectInfo, Workflow  # noqa: F401

        return Flow, ApiFlow, ObjectInfo, Workflow

    from .models import ApiFlow, Flow, ObjectInfo, Workflow  # noqa: F401

    return Flow, ApiFlow, ObjectInfo, Workflow


Flow, ApiFlow, ObjectInfo, Workflow = get_models()

__all__ = ["model_layer_name", "get_models", "Flow", "ApiFlow", "ObjectInfo", "Workflow"]


