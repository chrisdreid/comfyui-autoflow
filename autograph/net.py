"""autograph.net

Stdlib-only HTTP helpers for talking to a ComfyUI server.

This module intentionally keeps network interactions explicit and opt-in.
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from .defaults import DEFAULT_HTTP_TIMEOUT_S


_IMAGE_UPLOAD_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
}


class ImageUploadResult(dict):
    """Response from ComfyUI's /upload/image endpoint."""

    @property
    def name(self) -> Optional[str]:
        value = self.get("name")
        return value if isinstance(value, str) else None

    @property
    def subfolder(self) -> str:
        value = self.get("subfolder")
        return value if isinstance(value, str) else ""

    @property
    def type(self) -> str:
        value = self.get("type")
        return value if isinstance(value, str) else "input"

    @property
    def path(self) -> Optional[str]:
        value = self.get("path")
        if isinstance(value, str) and value:
            return value
        if not self.name:
            return None
        return f"{self.subfolder.strip('/')}/{self.name}" if self.subfolder else self.name


class ImageUploadResults(list):
    """List of ImageUploadResult objects."""

    def paths(self) -> List[str]:
        return [p for p in (getattr(item, "path", None) for item in self) if isinstance(p, str)]


def comfy_url(server_url: str, path: str) -> str:
    return f"{server_url.rstrip('/')}/{path.lstrip('/')}"


def _join_upload_subfolder(base: Optional[str], rel_parent: Path) -> str:
    parts = []
    if isinstance(base, str) and base.strip():
        parts.extend([p for p in base.replace("\\", "/").split("/") if p])
    if str(rel_parent) not in ("", "."):
        parts.extend(rel_parent.as_posix().split("/"))
    return "/".join(parts)


def _iter_image_upload_files(path: Path, *, recursive: bool) -> Iterable[Path]:
    it = path.rglob("*") if recursive else path.iterdir()
    for p in sorted(it):
        if p.is_file() and p.suffix.lower() in _IMAGE_UPLOAD_EXTENSIONS:
            yield p


def _multipart_form_data(fields: Dict[str, str], file_field: str, file_path: Path) -> tuple:
    boundary = f"----autograph-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    chunks: List[bytes] = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(file_path.read_bytes())
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), boundary


def _upload_single_image(
    file_path: Path,
    *,
    server_url: str,
    subfolder: Optional[str],
    image_type: str,
    overwrite: bool,
    timeout: int,
) -> ImageUploadResult:
    fields = {
        "type": str(image_type or "input"),
        "overwrite": "true" if overwrite else "false",
    }
    if subfolder:
        fields["subfolder"] = subfolder
    body, boundary = _multipart_form_data(fields, "image", file_path)
    req = urllib.request.Request(
        comfy_url(server_url, "/upload/image"),
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = ""
        raise urllib.error.HTTPError(
            e.url,
            e.code,
            f"{e.msg}{': ' + err_body if err_body else ''}",
            e.hdrs,
            e.fp,
        )

    parsed: Any
    parsed = json.loads(raw) if raw else {}
    if not isinstance(parsed, dict):
        parsed = {"raw": parsed}
    parsed.setdefault("name", file_path.name)
    parsed.setdefault("subfolder", subfolder or "")
    parsed.setdefault("type", image_type or "input")
    if "path" not in parsed:
        name = parsed.get("name")
        sf = parsed.get("subfolder")
        if isinstance(name, str):
            parsed["path"] = f"{str(sf).strip('/')}/{name}" if isinstance(sf, str) and sf else name
    return ImageUploadResult(parsed)


def upload_image(
    path: Union[str, Path],
    server_url: Optional[str] = None,
    *,
    subfolder: Optional[str] = None,
    image_type: str = "input",
    overwrite: bool = False,
    recursive: bool = True,
    timeout: int = DEFAULT_HTTP_TIMEOUT_S,
) -> Union[ImageUploadResult, ImageUploadResults]:
    """
    Upload one image file, or every image in a directory, to ComfyUI's input store.

    Directories preserve relative subdirectories by appending them to `subfolder`.
    The returned `path` value is the string expected by LoadImage's `image` input.
    """
    base = resolve_comfy_server_url(server_url)
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Image upload path not found: {path}")
    if p.is_file():
        return _upload_single_image(
            p,
            server_url=base,
            subfolder=subfolder,
            image_type=image_type,
            overwrite=overwrite,
            timeout=timeout,
        )
    if not p.is_dir():
        raise ValueError(f"Image upload path is neither a file nor directory: {path}")

    uploads = ImageUploadResults()
    for item in _iter_image_upload_files(p, recursive=recursive):
        rel_parent = item.relative_to(p).parent
        item_subfolder = _join_upload_subfolder(subfolder, rel_parent)
        uploads.append(
            _upload_single_image(
                item,
                server_url=base,
                subfolder=item_subfolder or None,
                image_type=image_type,
                overwrite=overwrite,
                timeout=timeout,
            )
        )
    return uploads


def http_json(
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = DEFAULT_HTTP_TIMEOUT_S,
    method: str = "POST",
) -> Dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            if not body:
                return {}
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return parsed
            return {"raw": parsed}
    except urllib.error.HTTPError as e:
        # Best-effort capture response body for easier debugging (e.g. /prompt 400 errors).
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = ""
        raise urllib.error.HTTPError(
            e.url,
            e.code,
            f"{e.msg}{': ' + err_body if err_body else ''}",
            e.hdrs,
            e.fp,
        )


def resolve_comfy_server_url(server_url: Optional[str]) -> str:
    """
    Resolve ComfyUI server URL for submit operations.

    We intentionally do NOT default to localhost here; submit() should only run when the
    user explicitly provides a URL or sets AUTOGRAPH_COMFYUI_SERVER_URL.
    """
    if server_url:
        return server_url
    env = os.environ.get("AUTOGRAPH_COMFYUI_SERVER_URL")
    if env:
        return env
    raise ValueError("Missing server URL. Pass server_url= or set AUTOGRAPH_COMFYUI_SERVER_URL.")



