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
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

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

_AUDIO_UPLOAD_EXTENSIONS = {
    ".aac",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
}

_VIDEO_UPLOAD_EXTENSIONS = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
}

_TEXT_UPLOAD_EXTENSIONS = {
    ".csv",
    ".json",
    ".md",
    ".srt",
    ".txt",
    ".vtt",
    ".yaml",
    ".yml",
}

_ARCHIVE_UPLOAD_EXTENSIONS = {
    ".7z",
    ".gz",
    ".rar",
    ".tar",
    ".tgz",
    ".zip",
}

_MODEL_UPLOAD_EXTENSIONS = {
    ".bin",
    ".ckpt",
    ".fbx",
    ".glb",
    ".gltf",
    ".gguf",
    ".obj",
    ".onnx",
    ".pt",
    ".pth",
    ".safetensors",
    ".stl",
}

_ACCEPT_EXTENSION_SETS = {
    "image": _IMAGE_UPLOAD_EXTENSIONS,
    "audio": _AUDIO_UPLOAD_EXTENSIONS,
    "video": _VIDEO_UPLOAD_EXTENSIONS,
    "text": _TEXT_UPLOAD_EXTENSIONS,
    "archive": _ARCHIVE_UPLOAD_EXTENSIONS,
    "model": _MODEL_UPLOAD_EXTENSIONS,
}


class FileUploadResult(dict):
    """Response from ComfyUI's upload endpoint for an input asset."""

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
    def mime_type(self) -> str:
        value = self.get("mime_type")
        return value if isinstance(value, str) else "application/octet-stream"

    @property
    def kind(self) -> str:
        value = self.get("kind")
        return value if isinstance(value, str) else "unknown"

    @property
    def path(self) -> Optional[str]:
        value = self.get("path")
        if isinstance(value, str) and value:
            return value
        if not self.name:
            return None
        return f"{self.subfolder.strip('/')}/{self.name}" if self.subfolder else self.name


class FileUploadResults(list):
    """List of FileUploadResult objects."""

    def paths(self) -> List[str]:
        return [p for p in (getattr(item, "path", None) for item in self) if isinstance(p, str)]


class ImageUploadResult(FileUploadResult):
    """Backward-compatible image upload result."""


class ImageUploadResults(FileUploadResults):
    """Backward-compatible list of ImageUploadResult objects."""


def comfy_url(server_url: str, path: str) -> str:
    return f"{server_url.rstrip('/')}/{path.lstrip('/')}"


def _join_upload_subfolder(base: Optional[str], rel_parent: Path) -> str:
    parts = []
    if isinstance(base, str) and base.strip():
        parts.extend([p for p in base.replace("\\", "/").split("/") if p])
    if str(rel_parent) not in ("", "."):
        parts.extend(rel_parent.as_posix().split("/"))
    return "/".join(parts)


def _guess_mime_type(file_path: Path) -> str:
    return mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"


def _guess_file_kind(file_path: Path, mime_type: Optional[str] = None) -> str:
    suffix = file_path.suffix.lower()
    for kind, extensions in _ACCEPT_EXTENSION_SETS.items():
        if suffix in extensions:
            return kind
    mime = mime_type or _guess_mime_type(file_path)
    if "/" in mime:
        prefix = mime.split("/", 1)[0]
        if prefix in ("image", "audio", "video", "text"):
            return prefix
    return "unknown"


def _normalize_accept(accept: Optional[Union[str, Iterable[str]]]) -> Tuple[str, ...]:
    if accept is None:
        return ()
    if isinstance(accept, str):
        raw_items = accept.replace(",", " ").split()
    else:
        raw_items = [str(item) for item in accept]
    return tuple(item.strip().lower() for item in raw_items if item and item.strip())


def _matches_accept(file_path: Path, accept: Optional[Union[str, Iterable[str]]]) -> bool:
    items = _normalize_accept(accept)
    if not items:
        return True
    suffix = file_path.suffix.lower()
    mime_type = _guess_mime_type(file_path)
    kind = _guess_file_kind(file_path, mime_type)
    for item in items:
        if item in ("*", "*/*", "any", "file"):
            return True
        if item in _ACCEPT_EXTENSION_SETS and kind == item:
            return True
        if item.endswith("/*") and mime_type.startswith(item[:-1]):
            return True
        if item.startswith(".") and suffix == item:
            return True
        if "/" in item and mime_type == item:
            return True
    return False


def _iter_upload_files(
    path: Path,
    *,
    recursive: bool,
    accept: Optional[Union[str, Iterable[str]]],
) -> Iterable[Path]:
    it = path.rglob("*") if recursive else path.iterdir()
    for p in sorted(it):
        if p.is_file() and _matches_accept(p, accept):
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


def _upload_single_file(
    file_path: Path,
    *,
    server_url: str,
    subfolder: Optional[str],
    file_type: str,
    overwrite: bool,
    timeout: int,
    endpoint_path: str,
    file_field: str,
) -> FileUploadResult:
    fields = {
        "type": str(file_type or "input"),
        "overwrite": "true" if overwrite else "false",
    }
    if subfolder:
        fields["subfolder"] = subfolder
    body, boundary = _multipart_form_data(fields, file_field, file_path)
    req = urllib.request.Request(
        comfy_url(server_url, endpoint_path),
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
    mime_type = _guess_mime_type(file_path)
    parsed.setdefault("name", file_path.name)
    parsed.setdefault("subfolder", subfolder or "")
    parsed.setdefault("type", file_type or "input")
    parsed.setdefault("mime_type", mime_type)
    parsed.setdefault("kind", _guess_file_kind(file_path, mime_type))
    if "path" not in parsed:
        name = parsed.get("name")
        sf = parsed.get("subfolder")
        if isinstance(name, str):
            parsed["path"] = f"{str(sf).strip('/')}/{name}" if isinstance(sf, str) and sf else name
    return FileUploadResult(parsed)


def upload_file(
    path: Union[str, Path],
    server_url: Optional[str] = None,
    *,
    subfolder: Optional[str] = None,
    file_type: str = "input",
    overwrite: bool = False,
    recursive: bool = True,
    timeout: int = DEFAULT_HTTP_TIMEOUT_S,
    accept: Optional[Union[str, Iterable[str]]] = None,
    endpoint_path: str = "/upload/image",
    file_field: str = "image",
) -> Union[FileUploadResult, FileUploadResults]:
    """
    Upload one file, or matching files in a directory, to ComfyUI's input store.

    Directories preserve relative subdirectories by appending them to `subfolder`.
    `accept` may be a friendly kind (image/audio/video/text/archive/model), a MIME
    pattern like image/*, an exact MIME type, an extension, or an iterable of those.
    The returned `path` value is the string expected by ComfyUI file inputs.
    """
    base = resolve_comfy_server_url(server_url)
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"File upload path not found: {path}")
    if p.is_file():
        if not _matches_accept(p, accept):
            raise ValueError(f"File does not match accepted upload template {accept!r}: {path}")
        return _upload_single_file(
            p,
            server_url=base,
            subfolder=subfolder,
            file_type=file_type,
            overwrite=overwrite,
            timeout=timeout,
            endpoint_path=endpoint_path,
            file_field=file_field,
        )
    if not p.is_dir():
        raise ValueError(f"File upload path is neither a file nor directory: {path}")

    uploads = FileUploadResults()
    for item in _iter_upload_files(p, recursive=recursive, accept=accept):
        rel_parent = item.relative_to(p).parent
        item_subfolder = _join_upload_subfolder(subfolder, rel_parent)
        uploads.append(
            _upload_single_file(
                item,
                server_url=base,
                subfolder=item_subfolder or None,
                file_type=file_type,
                overwrite=overwrite,
                timeout=timeout,
                endpoint_path=endpoint_path,
                file_field=file_field,
            )
        )
    return uploads


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

    This is a compatibility wrapper around upload_file(..., accept="image").
    """
    uploaded = upload_file(
        path,
        server_url=server_url,
        subfolder=subfolder,
        file_type=image_type,
        overwrite=overwrite,
        recursive=recursive,
        timeout=timeout,
        accept="image",
    )
    if isinstance(uploaded, FileUploadResult):
        return ImageUploadResult(uploaded)
    return ImageUploadResults(ImageUploadResult(item) for item in uploaded)


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



