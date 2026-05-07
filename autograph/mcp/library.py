"""Local workflow library + curated online sources catalog.

A "workflow library" is just a directory of ``*.json`` workflow files plus
optional sidecar ``*.metadata.json`` files of the shape::

    {
      "name": "txt2img-sdxl-base",
      "title": "Text-to-image (SDXL base)",
      "description": "Stock SDXL base text-to-image with Empty Latent + KSampler.",
      "tags": ["txt2img", "sdxl"],
      "models_required": ["sd_xl_base_1.0.safetensors"],
      "source": "https://github.com/comfyanonymous/ComfyUI_examples"
    }

Search order (highest priority first):

1. ``$AUTOGRAPH_MCP_LIBRARY_DIRS`` (colon-separated additional dirs)
2. ``./.autograph-workflows/`` (project-local)
3. ``~/.comfyui-autograph/workflows/`` (user-home)
4. ``<package>/examples/workflows/starters/`` (bundled with the repo)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


LIBRARY_DIR_ENV = "AUTOGRAPH_MCP_LIBRARY_DIRS"


# Curated set of public sources the LLM can ask the user about (or feed to its
# own WebFetch) when it needs an example to riff on. The MCP itself does NOT
# scrape these — it just hands back the URLs.
ONLINE_SOURCES: List[Dict[str, str]] = [
    {
        "name": "ComfyUI_examples (official)",
        "url": "https://github.com/comfyanonymous/ComfyUI_examples",
        "kind": "github",
        "notes": "Canonical reference workflows for txt2img, img2img, controlnet, area composition, and more.",
    },
    {
        "name": "comfyanonymous/ComfyUI workflows",
        "url": "https://github.com/comfyanonymous/ComfyUI/tree/master/script_examples",
        "kind": "github",
        "notes": "Script-driven workflow examples maintained alongside the main ComfyUI repo.",
    },
    {
        "name": "Civitai (workflows)",
        "url": "https://civitai.com/search?type=workflows",
        "kind": "gallery",
        "notes": "Community-shared workflow JSONs alongside checkpoints; user uploads, quality varies.",
    },
    {
        "name": "OpenArt ComfyUI gallery",
        "url": "https://openart.ai/workflows/all",
        "kind": "gallery",
        "notes": "Community ComfyUI workflows with previews and tags.",
    },
    {
        "name": "ComfyUI Manager (custom-node index)",
        "url": "https://github.com/ltdrdata/ComfyUI-Manager",
        "kind": "github",
        "notes": "Use when a workflow needs a custom node — points at install instructions.",
    },
    {
        "name": "GitHub code search: workflow.json",
        "url": "https://github.com/search?q=path%3A%2A.json+%22nodes%22+%22links%22+%22last_node_id%22&type=code",
        "kind": "search",
        "notes": "Raw GitHub code search that finds workspace-format workflow JSON files.",
    },
]


# ---------------------------------------------------------------------------
# Library entries
# ---------------------------------------------------------------------------


@dataclass
class LibraryEntry:
    name: str
    path: Path
    title: str = ""
    description: str = ""
    tags: List[str] = None             # type: ignore[assignment]
    models_required: List[str] = None  # type: ignore[assignment]
    source: Optional[str] = None
    library_root: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags or []),
            "models_required": list(self.models_required or []),
            "source": self.source,
            "library_root": str(self.library_root) if self.library_root else None,
        }


def _bundled_starters_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "examples" / "workflows" / "starters"


def library_dirs() -> List[Path]:
    """Return library directories in search-priority order. Always returns absolute paths."""
    seen: List[Path] = []

    def _add(p: Optional[Path]) -> None:
        if p is None:
            return
        try:
            resolved = p.expanduser().resolve()
        except OSError:
            return
        if resolved not in seen:
            seen.append(resolved)

    env = os.environ.get(LIBRARY_DIR_ENV)
    if env:
        for chunk in env.split(os.pathsep):
            chunk = chunk.strip()
            if chunk:
                _add(Path(chunk))

    _add(Path.cwd() / ".autograph-workflows")
    _add(Path.home() / ".comfyui-autograph" / "workflows")
    _add(_bundled_starters_dir())
    return seen


def _read_metadata(workflow_path: Path) -> Dict[str, Any]:
    side = workflow_path.with_suffix(".metadata.json")
    if not side.exists():
        # Also accept inline metadata in autograph's `extra.autograph.meta` field.
        try:
            data = json.loads(workflow_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if isinstance(data, dict):
            extra = data.get("extra")
            if isinstance(extra, dict):
                ag = extra.get("autograph") or extra.get("autoflow") or {}
                meta = ag.get("meta") if isinstance(ag, dict) else None
                if isinstance(meta, dict):
                    return meta
        return {}
    try:
        return json.loads(side.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _entry_from(path: Path, *, library_root: Path) -> LibraryEntry:
    meta = _read_metadata(path)
    name = (meta.get("name") if isinstance(meta, dict) else None) or path.stem
    title = (meta.get("title") if isinstance(meta, dict) else "") or path.stem.replace("_", " ").replace("-", " ").title()
    desc = meta.get("description", "") if isinstance(meta, dict) else ""
    tags = meta.get("tags", []) if isinstance(meta, dict) else []
    models = meta.get("models_required", []) if isinstance(meta, dict) else []
    src = meta.get("source") if isinstance(meta, dict) else None
    return LibraryEntry(
        name=str(name),
        path=path,
        title=str(title),
        description=str(desc),
        tags=[str(t) for t in (tags or [])],
        models_required=[str(m) for m in (models or [])],
        source=str(src) if src else None,
        library_root=library_root,
    )


def discover() -> List[LibraryEntry]:
    """Return all library entries across all configured directories (no deduplication)."""
    out: List[LibraryEntry] = []
    seen_paths: set = set()
    for d in library_dirs():
        if not d.exists() or not d.is_dir():
            continue
        for path in sorted(d.rglob("*.json")):
            if path.name.endswith(".metadata.json"):
                continue
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            out.append(_entry_from(resolved, library_root=d))
    return out


def search(
    query: Optional[str] = None,
    tags: Optional[Iterable[str]] = None,
    limit: int = 20,
) -> List[LibraryEntry]:
    """Filter the library by query (substring match) and tags (any-of)."""
    q = (query or "").strip().lower()
    want_tags = {t.lower() for t in tags or [] if isinstance(t, str) and t.strip()}
    out: List[LibraryEntry] = []
    for entry in discover():
        haystack = " ".join(
            filter(
                None,
                [
                    entry.name,
                    entry.title,
                    entry.description,
                    " ".join(entry.tags or []),
                    str(entry.path),
                ],
            )
        ).lower()
        if q and q not in haystack:
            continue
        if want_tags and not (want_tags & {t.lower() for t in entry.tags or []}):
            continue
        out.append(entry)
        if len(out) >= max(1, limit):
            break
    return out


def load_by_name(name: str) -> LibraryEntry:
    """Locate a workflow by name (or filename) and return its LibraryEntry."""
    target = name.strip().lower()
    matches: List[LibraryEntry] = []
    for entry in discover():
        if entry.name.lower() == target or entry.path.stem.lower() == target:
            matches.append(entry)
    if not matches:
        # Fallback to fuzzy contains.
        for entry in discover():
            if target in entry.name.lower() or target in entry.path.stem.lower():
                matches.append(entry)
    if not matches:
        raise FileNotFoundError(
            f"No workflow in the library matches {name!r}. "
            f"Use `search_local_workflows` to list what's available."
        )
    return matches[0]
