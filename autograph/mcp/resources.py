"""MCP resource handlers for browsing ComfyUI state without burning tool calls."""

from __future__ import annotations

from typing import Any, Dict

from autograph.net import comfy_url, http_json
import autograph

from .config import McpConfig


def node_info_resource(config: McpConfig) -> str:
    """Return the full node_info catalog as a JSON string."""
    base = config.resolve_server_url()
    ni = autograph.NodeInfo.fetch(server_url=base, timeout=config.timeout_s)
    return ni.to_json()


def history_resource(config: McpConfig, prompt_id: str) -> Dict[str, Any]:
    """Return the full history JSON for a single job."""
    base = config.resolve_server_url()
    return http_json(
        comfy_url(base, f"/history/{prompt_id}"),
        payload=None,
        timeout=config.timeout_s,
        method="GET",
    )


def output_resource(config: McpConfig, prompt_id: str, filename: str) -> bytes:
    """Fetch an output file's bytes via /view, looking up its subfolder/type from history."""
    base = config.resolve_server_url()
    history = http_json(
        comfy_url(base, f"/history/{prompt_id}"),
        payload=None,
        timeout=config.timeout_s,
        method="GET",
    )
    entry = history.get(prompt_id) if isinstance(history, dict) else None
    subfolder = ""
    type_ = "output"
    if isinstance(entry, dict):
        outputs = entry.get("outputs")
        if isinstance(outputs, dict):
            for _node, node_out in outputs.items():
                if not isinstance(node_out, dict):
                    continue
                for items in node_out.values():
                    if not isinstance(items, list):
                        continue
                    for it in items:
                        if isinstance(it, dict) and it.get("filename") == filename:
                            subfolder = str(it.get("subfolder", "") or "")
                            type_ = str(it.get("type", "") or "output")
                            break
    import urllib.parse
    qs = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": type_})
    url = comfy_url(base, f"/view?{qs}")
    import urllib.request
    with urllib.request.urlopen(url, timeout=config.timeout_s) as resp:
        return resp.read()
