"""Tool implementations for the autograph MCP server.

Every function here is a thin wrapper over the public ``autograph`` API. There is
no business logic in this module — its job is to translate MCP-friendly arg shapes
into autograph calls and translate autograph results into JSON-friendly dicts.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

import autograph
from autograph.net import comfy_url, http_json, upload_file as _upload_file
from autograph.results import SubmissionResult

from .config import McpConfig
from .images import build_image_response, guess_mime_type


WorkflowInput = Union[str, Dict[str, Any]]


# ---------------------------------------------------------------------------
# Workflow input coercion
# ---------------------------------------------------------------------------


def _looks_like_json(s: str) -> bool:
    if not isinstance(s, str):
        return False
    stripped = s.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def _coerce_workflow(workflow: WorkflowInput) -> Union[Dict[str, Any], Path]:
    """Accept a path string, JSON string, or dict and return a value autograph.Flow accepts."""
    if isinstance(workflow, dict):
        return workflow
    if isinstance(workflow, str):
        if _looks_like_json(workflow):
            return json.loads(workflow)
        p = Path(workflow).expanduser()
        if p.exists() and p.is_file():
            return p
        # Treat any other string as JSON (will raise a clearer error than file-not-found).
        return json.loads(workflow)
    raise TypeError(
        f"workflow must be a JSON string, file path, or dict — got {type(workflow).__name__}"
    )


def _flow(workflow: WorkflowInput, *, server_url: Optional[str] = None) -> "autograph.Flow":
    src = _coerce_workflow(workflow)
    if server_url:
        return autograph.Flow(src, server_url=server_url)
    return autograph.Flow(src)


def _node_summary(node: Any) -> Dict[str, Any]:
    """Compact, LLM-friendly view of a NodeRef."""
    raw = node.unwrap() if hasattr(node, "unwrap") else dict(node)
    summary: Dict[str, Any] = {
        "id": getattr(node, "addr", None) or str(raw.get("id", "")),
        "class_type": getattr(node, "type", None) or raw.get("class_type") or raw.get("type", ""),
        "title": getattr(node, "title", "") or "",
    }
    inputs = raw.get("inputs")
    if isinstance(inputs, dict):
        widgets: Dict[str, Any] = {}
        connections: Dict[str, Any] = {}
        for k, v in inputs.items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], (str, int)):
                connections[k] = {"from_node_id": str(v[0]), "from_output": v[1]}
            else:
                widgets[k] = v
        if widgets:
            summary["inputs"] = widgets
        if connections:
            summary["connections"] = connections
    else:
        wv = raw.get("widgets_values")
        if isinstance(wv, list):
            summary["widgets_values"] = wv
    return summary


# ---------------------------------------------------------------------------
# Server / introspection
# ---------------------------------------------------------------------------


def comfyui_status(config: McpConfig, server_url: Optional[str] = None) -> Dict[str, Any]:
    base = config.resolve_server_url(server_url)
    out: Dict[str, Any] = {
        "server_url": base,
        "reachable": False,
    }
    try:
        stats = http_json(comfy_url(base, "/system_stats"), payload=None, timeout=config.timeout_s, method="GET")
        out["reachable"] = True
        out["system_stats"] = stats
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    try:
        queue = http_json(comfy_url(base, "/queue"), payload=None, timeout=config.timeout_s, method="GET")
        running = queue.get("queue_running") if isinstance(queue, dict) else None
        pending = queue.get("queue_pending") if isinstance(queue, dict) else None
        out["queue"] = {
            "running": len(running) if isinstance(running, list) else 0,
            "pending": len(pending) if isinstance(pending, list) else 0,
        }
    except Exception:
        pass
    return out


def list_node_types(
    config: McpConfig,
    query: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50,
    server_url: Optional[str] = None,
) -> Dict[str, Any]:
    base = config.resolve_server_url(server_url)
    ni = autograph.NodeInfo.fetch(server_url=base, timeout=config.timeout_s)
    matches = ni.find(q=query) if query else [
        # No query: build a minimal entry per node.
        type("V", (), {"_AUTOGRAPH_addr": k, "_d": v})()
        for k, v in ni.items()
        if isinstance(k, str) and isinstance(v, dict)
    ]

    out: List[Dict[str, Any]] = []
    for view in matches:
        addr = getattr(view, "_AUTOGRAPH_addr", None)
        if isinstance(view, dict):
            data = view
        else:
            data = getattr(view, "_d", None) or ni.get(addr) or {}
        cat = data.get("category") if isinstance(data, dict) else None
        if category and isinstance(cat, str) and category.lower() not in cat.lower():
            continue
        out.append(
            {
                "class_type": addr,
                "display_name": data.get("display_name") if isinstance(data, dict) else None,
                "category": cat,
                "output_node": bool(data.get("output_node")) if isinstance(data, dict) else False,
            }
        )
        if len(out) >= max(1, limit):
            break
    return {"server_url": base, "count": len(out), "node_types": out}


def describe_node_type(
    config: McpConfig,
    class_type: str,
    server_url: Optional[str] = None,
) -> Dict[str, Any]:
    base = config.resolve_server_url(server_url)
    ni = autograph.NodeInfo.fetch(server_url=base, timeout=config.timeout_s)
    if class_type in ni:
        data = ni[class_type]
        return {
            "class_type": class_type,
            "definition": dict(data) if isinstance(data, dict) else data,
        }
    # Case-insensitive fallback.
    target = class_type.lower()
    for k, v in ni.items():
        if isinstance(k, str) and k.lower() == target and isinstance(v, dict):
            return {"class_type": k, "definition": dict(v)}
    raise KeyError(f"Unknown class_type: {class_type!r}")


def list_models(
    config: McpConfig,
    folder: Optional[str] = None,
    server_url: Optional[str] = None,
) -> Dict[str, Any]:
    base = config.resolve_server_url(server_url)
    path = "/models" if not folder else f"/models/{folder}"
    data = http_json(comfy_url(base, path), payload=None, timeout=config.timeout_s, method="GET")
    return {"server_url": base, "folder": folder, "data": data}


# ---------------------------------------------------------------------------
# Workflow inspection / editing
# ---------------------------------------------------------------------------


def inspect_workflow(config: McpConfig, workflow: WorkflowInput) -> Dict[str, Any]:
    flow = _flow(workflow, server_url=config.resolve_server_url())
    nodes_view = flow.nodes
    nodes: List[Dict[str, Any]] = []
    try:
        for n in nodes_view:
            nodes.append(_node_summary(n))
    except Exception:
        # Fall back to raw iteration over the underlying dict structure.
        raw = flow.unwrap() if hasattr(flow, "unwrap") else dict(flow)
        for n in raw.get("nodes", []) or []:
            if isinstance(n, dict):
                nodes.append(
                    {
                        "id": str(n.get("id", "")),
                        "class_type": n.get("type") or n.get("class_type", ""),
                        "title": n.get("title") or "",
                        "widgets_values": n.get("widgets_values"),
                    }
                )
    return {
        "node_count": len(nodes),
        "nodes": nodes,
        "node_info_source": getattr(flow, "source", None),
    }


def convert_workflow(config: McpConfig, workflow: WorkflowInput) -> Dict[str, Any]:
    flow = _flow(workflow, server_url=config.resolve_server_url())
    result = flow.convert_with_errors()
    api_data = None
    if getattr(result, "data", None) is not None:
        try:
            api_data = result.data.unwrap() if hasattr(result.data, "unwrap") else dict(result.data)
        except Exception:
            api_data = result.data
    return {
        "ok": bool(getattr(result, "ok", False)),
        "errors": [_err(e) for e in getattr(result, "errors", []) or []],
        "warnings": [_err(w) for w in getattr(result, "warnings", []) or []],
        "processed_nodes": getattr(result, "processed_nodes", 0),
        "skipped_nodes": getattr(result, "skipped_nodes", 0),
        "total_nodes": getattr(result, "total_nodes", 0),
        "api_workflow": api_data,
    }


def validate_workflow(config: McpConfig, workflow: WorkflowInput) -> Dict[str, Any]:
    flow = _flow(workflow, server_url=config.resolve_server_url())
    result = flow.convert_with_errors()
    return {
        "ok": bool(getattr(result, "ok", False)),
        "errors": [_err(e) for e in getattr(result, "errors", []) or []],
        "warnings": [_err(w) for w in getattr(result, "warnings", []) or []],
        "processed_nodes": getattr(result, "processed_nodes", 0),
        "total_nodes": getattr(result, "total_nodes", 0),
    }


def _err(e: Any) -> Dict[str, Any]:
    return {
        "category": _enum_value(getattr(e, "category", None)),
        "severity": _enum_value(getattr(e, "severity", None)),
        "message": getattr(e, "message", str(e)),
        "node_id": getattr(e, "node_id", None),
        "details": getattr(e, "details", None),
    }


def _enum_value(v: Any) -> Optional[str]:
    if v is None:
        return None
    return getattr(v, "value", str(v))


def set_workflow_values(
    config: McpConfig,
    workflow: WorkflowInput,
    updates: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Apply a list of widget patches to a workflow and return the updated JSON.

    Each ``update`` is a dict matching one or more nodes plus the inputs to set::

        {"node_id": "5", "inputs": {"seed": 42, "steps": 30}}
        {"class_type": "KSampler", "inputs": {"cfg": 7.5}}
        {"title": "Positive Prompt", "inputs": {"text": "a cat"}}

    If multiple match keys are given on a single update they are AND-ed.
    """
    flow = _flow(workflow, server_url=config.resolve_server_url())
    applied: List[Dict[str, Any]] = []
    if not isinstance(updates, list):
        raise TypeError("updates must be a list of {node_id?, class_type?, title?, inputs} dicts")

    for patch in updates:
        if not isinstance(patch, dict):
            continue
        inputs = patch.get("inputs")
        if not isinstance(inputs, dict) or not inputs:
            continue
        node_id = patch.get("node_id")
        class_type = patch.get("class_type")
        title = patch.get("title")

        targets = list(_resolve_targets(flow, node_id=node_id, class_type=class_type, title=title))
        for t in targets:
            for k, v in inputs.items():
                try:
                    setattr(t, k, v)
                    applied.append(
                        {
                            "node_id": getattr(t, "addr", None),
                            "class_type": getattr(t, "type", None),
                            "input": k,
                            "value": v,
                            "ok": True,
                        }
                    )
                except Exception as exc:
                    applied.append(
                        {
                            "node_id": getattr(t, "addr", None),
                            "class_type": getattr(t, "type", None),
                            "input": k,
                            "value": v,
                            "ok": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

    return {
        "applied": applied,
        "workflow": flow.unwrap() if hasattr(flow, "unwrap") else dict(flow),
    }


def _resolve_targets(
    flow: "autograph.Flow",
    *,
    node_id: Optional[Any] = None,
    class_type: Optional[str] = None,
    title: Optional[str] = None,
) -> Iterable[Any]:
    """Yield NodeRef-like targets matching the given criteria."""
    if node_id is not None:
        try:
            return [_by_id(flow, node_id)]
        except Exception:
            return []
    matches = []
    try:
        all_nodes = list(flow.nodes)
    except Exception:
        all_nodes = []
    for n in all_nodes:
        if class_type and (getattr(n, "type", "") or "").lower() != class_type.lower():
            continue
        if title and (getattr(n, "title", "") or "") != title:
            continue
        matches.append(n)
    return matches


def _by_id(flow: "autograph.Flow", node_id: Any) -> Any:
    target = str(node_id)
    for n in flow.nodes:
        if str(getattr(n, "addr", "")) == target:
            return n
    raise KeyError(f"No node with id {node_id!r}")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def run_workflow(
    config: McpConfig,
    workflow: WorkflowInput,
    wait: bool = True,
    fetch_outputs: bool = True,
    save_to: Optional[str] = None,
    inline_images: bool = True,
    max_inline: Optional[int] = None,
    server_url: Optional[str] = None,
) -> Dict[str, Any]:
    base = config.resolve_server_url(server_url)
    flow = _flow(workflow, server_url=base)
    submission = flow.submit(
        server_url=base,
        wait=wait,
        fetch_outputs=False,        # we fetch ourselves so we control include_bytes
        timeout=config.timeout_s,
    )
    return _materialize_submission(
        config,
        submission,
        save_to=save_to,
        inline_images=inline_images,
        max_inline=max_inline,
        do_fetch=fetch_outputs,
    )


def queue_workflow(
    config: McpConfig,
    workflow: WorkflowInput,
    server_url: Optional[str] = None,
) -> Dict[str, Any]:
    base = config.resolve_server_url(server_url)
    flow = _flow(workflow, server_url=base)
    submission = flow.submit(server_url=base, wait=False, fetch_outputs=False, timeout=config.timeout_s)
    return {
        "prompt_id": submission.prompt_id,
        "server_url": submission.server_url,
    }


def get_history(
    config: McpConfig,
    prompt_id: Optional[str] = None,
    limit: int = 10,
    server_url: Optional[str] = None,
) -> Dict[str, Any]:
    base = config.resolve_server_url(server_url)
    if prompt_id:
        url = comfy_url(base, f"/history/{prompt_id}")
        return {"server_url": base, "prompt_id": prompt_id, "history": http_json(url, payload=None, timeout=config.timeout_s, method="GET")}
    url = comfy_url(base, f"/history?max_items={max(1, int(limit))}")
    return {"server_url": base, "limit": limit, "history": http_json(url, payload=None, timeout=config.timeout_s, method="GET")}


def interrupt(config: McpConfig, server_url: Optional[str] = None) -> Dict[str, Any]:
    base = config.resolve_server_url(server_url)
    try:
        http_json(comfy_url(base, "/interrupt"), payload={}, timeout=config.timeout_s, method="POST")
        return {"server_url": base, "ok": True}
    except urllib.error.HTTPError as exc:
        return {"server_url": base, "ok": False, "error": f"HTTP {exc.code}: {exc.reason}"}


# ---------------------------------------------------------------------------
# Files / outputs
# ---------------------------------------------------------------------------


def upload_file(
    config: McpConfig,
    local_path: str,
    accept: Optional[Union[str, List[str]]] = None,
    subfolder: Optional[str] = None,
    overwrite: bool = False,
    server_url: Optional[str] = None,
) -> Dict[str, Any]:
    base = config.resolve_server_url(server_url)
    result = _upload_file(
        local_path,
        server_url=base,
        subfolder=subfolder,
        overwrite=overwrite,
        accept=accept,
        timeout=config.timeout_s,
    )
    if isinstance(result, list):
        items = [dict(it) for it in result]
        return {"server_url": base, "uploaded": items}
    return {"server_url": base, "uploaded": [dict(result)]}


def fetch_outputs(
    config: McpConfig,
    prompt_id: str,
    save_to: Optional[str] = None,
    kinds: Optional[Union[str, List[str]]] = None,
    inline_images: bool = True,
    max_inline: Optional[int] = None,
    server_url: Optional[str] = None,
) -> Dict[str, Any]:
    base = config.resolve_server_url(server_url)
    submission = SubmissionResult.from_prompt_id(prompt_id, server_url=base)
    return _materialize_submission(
        config,
        submission,
        save_to=save_to,
        inline_images=inline_images,
        max_inline=max_inline,
        do_fetch=True,
        output_types=kinds,
    )


def list_outputs(
    config: McpConfig,
    prompt_id: str,
    server_url: Optional[str] = None,
) -> Dict[str, Any]:
    base = config.resolve_server_url(server_url)
    url = comfy_url(base, f"/history/{prompt_id}")
    history = http_json(url, payload=None, timeout=config.timeout_s, method="GET")
    entry = history.get(prompt_id) if isinstance(history, dict) else None
    outputs: List[Dict[str, Any]] = []
    if isinstance(entry, dict):
        node_outputs = entry.get("outputs")
        if isinstance(node_outputs, dict):
            for node_id, node_out in node_outputs.items():
                if not isinstance(node_out, dict):
                    continue
                for kind, items in node_out.items():
                    if not isinstance(items, list):
                        continue
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        outputs.append(
                            {
                                "node_id": str(node_id),
                                "kind": kind,
                                "filename": it.get("filename"),
                                "subfolder": it.get("subfolder", ""),
                                "type": it.get("type", ""),
                                "resource_uri": (
                                    f"comfyui://outputs/{prompt_id}/{it.get('filename')}"
                                    if it.get("filename")
                                    else None
                                ),
                            }
                        )
    return {"server_url": base, "prompt_id": prompt_id, "outputs": outputs}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _materialize_submission(
    config: McpConfig,
    submission: SubmissionResult,
    *,
    save_to: Optional[str],
    inline_images: bool,
    max_inline: Optional[int],
    do_fetch: bool,
    output_types: Optional[Union[str, List[str]]] = None,
) -> Dict[str, Any]:
    base = submission.server_url
    out: Dict[str, Any] = {
        "prompt_id": submission.prompt_id,
        "server_url": base,
    }
    if not do_fetch:
        return out

    output_path = save_to or config.output_path
    files = submission.fetch_files(
        output_types=output_types,
        timeout=config.timeout_s,
        wait=True,
        output_path=output_path,
        include_bytes=bool(inline_images),
    )

    cap_count = max_inline if isinstance(max_inline, int) else config.max_inline_images
    blocks, summary = build_image_response(
        files,
        prompt_id=submission.prompt_id,
        inline=bool(inline_images),
        max_inline_count=cap_count,
        max_inline_bytes=config.max_inline_image_bytes,
    )

    out["outputs"] = summary
    out["save_path"] = output_path
    out["content_blocks"] = blocks
    return out
