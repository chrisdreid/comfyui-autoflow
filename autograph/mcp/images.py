"""Image-return policy for MCP tool results.

Generated images are returned inline as base64 ``ImageContent`` so the LLM can
actually see them, but with a per-call cap on bytes and count to prevent
context-window blowup on large grid renders. Anything that exceeds the cap is
returned as a file path + ``comfyui://`` resource URI instead.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def guess_mime_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return _MIME_BY_EXT.get(ext, "application/octet-stream")


def _ref_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, dict):
        ref = item.get("ref")
        if isinstance(ref, dict):
            return ref
        return item
    return {}


def _payload_bytes(item: Any) -> Optional[bytes]:
    if not isinstance(item, dict):
        return None
    blob = item.get("bytes")
    if isinstance(blob, (bytes, bytearray, memoryview)):
        return bytes(blob)
    return None


def _payload_path(item: Any) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    p = item.get("path")
    if isinstance(p, str) and p:
        return p
    return None


def build_image_response(
    items: Iterable[Any],
    *,
    prompt_id: Optional[str],
    inline: bool,
    max_inline_count: int,
    max_inline_bytes: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Decide which items get inlined and which get linked.

    Returns ``(content_blocks, summary_entries)`` where ``content_blocks`` is the
    structured-content list ready for the MCP tool result (text + image entries)
    and ``summary_entries`` is a JSON-friendly per-item summary.
    """
    sized: List[Tuple[int, Dict[str, Any]]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        b = _payload_bytes(raw)
        size = len(b) if b is not None else 0
        sized.append((size, raw))

    sized.sort(key=lambda pair: pair[0])

    summary: List[Dict[str, Any]] = []
    blocks: List[Dict[str, Any]] = []
    inlined_count = 0
    inlined_bytes = 0

    for size, item in sized:
        ref = _ref_dict(item)
        filename = str(ref.get("filename") or item.get("filename") or "")
        subfolder = str(ref.get("subfolder") or item.get("subfolder") or "")
        kind = str(ref.get("kind") or item.get("kind") or "")
        type_ = str(ref.get("type") or item.get("type") or "")
        path = _payload_path(item)
        blob = _payload_bytes(item)
        mime = guess_mime_type(filename) if filename else "application/octet-stream"

        entry: Dict[str, Any] = {
            "filename": filename,
            "subfolder": subfolder,
            "kind": kind,
            "type": type_,
            "size_bytes": size,
            "saved_path": path,
            "inlined": False,
        }
        if prompt_id and filename:
            entry["resource_uri"] = f"comfyui://outputs/{prompt_id}/{filename}"

        can_inline = (
            inline
            and blob is not None
            and mime.startswith("image/")
            and inlined_count < max_inline_count
            and (inlined_bytes + size) <= max_inline_bytes
        )

        if can_inline:
            blocks.append(
                {
                    "type": "image",
                    "data": base64.b64encode(blob).decode("ascii"),
                    "mimeType": mime,
                }
            )
            entry["inlined"] = True
            inlined_count += 1
            inlined_bytes += size
        elif path:
            blocks.append({"type": "text", "text": f"saved: {path}"})
        elif "resource_uri" in entry:
            blocks.append({"type": "text", "text": f"available at: {entry['resource_uri']}"})

        summary.append(entry)

    return blocks, summary
