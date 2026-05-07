"""FastMCP server for comfyui-autograph.

Build the server with :func:`build_server` (useful for tests) or run it with
:func:`main` (the console-script entry point — defaults to stdio transport).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Union

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from autograph.version import __version__

from . import prompts as _prompts
from . import resources as _resources
from . import tools as _tools
from .config import McpConfig, load_config
from .session import SessionStore


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------


def _materialize_content_blocks(blocks: List[Dict[str, Any]]) -> List[Union[TextContent, ImageContent]]:
    out: List[Union[TextContent, ImageContent]] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "image":
            out.append(
                ImageContent(
                    type="image",
                    data=str(b.get("data", "")),
                    mimeType=str(b.get("mimeType", "image/png")),
                )
            )
        else:
            out.append(TextContent(type="text", text=str(b.get("text", ""))))
    return out


def _result_with_images(payload: Dict[str, Any]) -> List[Union[TextContent, ImageContent]]:
    blocks = payload.pop("content_blocks", []) or []
    summary = TextContent(type="text", text=json.dumps(payload, default=str, indent=2))
    return [summary, *_materialize_content_blocks(blocks)]


# ---------------------------------------------------------------------------
# Server construction
# ---------------------------------------------------------------------------


def build_server(
    config: Optional[McpConfig] = None,
    store: Optional[SessionStore] = None,
) -> FastMCP:
    cfg = config or load_config()
    sessions = store or SessionStore()

    mcp = FastMCP(
        "comfyui-autograph",
        instructions=(
            "ComfyUI workflow workhorse. Typical loop: `load_workflow` (or `create_workflow`) -> "
            "`inspect_workflow` -> `set_workflow_values` / `add_node` / `connect_nodes` / `merge_workflow` -> "
            "`validate_workflow` -> `run_workflow`. Workflows live in a stateful session keyed by `workflow_id` "
            "with auto-checkpoints to ~/.comfyui-autograph/sessions/. The `merge_workflow` tool grafts a "
            "fragment (e.g. JSON found online) into the active workflow with auto-stitching, returning what "
            "still needs wiring. Use `list_workflow_sources` for curated places to fetch fragments and "
            "`search_local_workflows` to browse the local library. Generated images are returned inline "
            "(base64) up to a per-call cap; large outputs fall back to file paths and `comfyui://` URIs."
        ),
    )

    # =======================================================================
    # Server / introspection (4)
    # =======================================================================

    @mcp.tool()
    def comfyui_status(server_url: Optional[str] = None) -> Dict[str, Any]:
        """Check whether a ComfyUI server is reachable and report queue depth + system stats."""
        return _tools.comfyui_status(cfg, server_url=server_url)

    @mcp.tool()
    def list_node_types(
        query: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
        server_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List ComfyUI node types. `query` matches class_type or display_name (substring, case-insensitive)."""
        return _tools.list_node_types(cfg, query=query, category=category, limit=limit, server_url=server_url)

    @mcp.tool()
    def describe_node_type(class_type: str, server_url: Optional[str] = None) -> Dict[str, Any]:
        """Return the full input/output/widget definition for a single node class_type."""
        return _tools.describe_node_type(cfg, class_type=class_type, server_url=server_url)

    @mcp.tool()
    def list_models(folder: Optional[str] = None, server_url: Optional[str] = None) -> Dict[str, Any]:
        """List models known to ComfyUI. With no folder, returns the folder index; with one (e.g. 'checkpoints', 'loras', 'vae'), returns its contents."""
        return _tools.list_models(cfg, folder=folder, server_url=server_url)

    # =======================================================================
    # Workflow inspection / editing (4) — session-aware
    # =======================================================================

    @mcp.tool()
    def inspect_workflow(
        workflow: Optional[Union[str, Dict[str, Any]]] = None,
        workflow_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Summarize a workflow's nodes, link counts, and node_info source. Pass `workflow_id` for an active session, or `workflow` (path/JSON/dict) to inspect inline."""
        return _tools.inspect_workflow(cfg, sessions, workflow=workflow, workflow_id=workflow_id)

    @mcp.tool()
    def convert_workflow(
        workflow: Optional[Union[str, Dict[str, Any]]] = None,
        workflow_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convert a workspace workflow to ComfyUI's API format and return both result and structured errors."""
        return _tools.convert_workflow(cfg, sessions, workflow=workflow, workflow_id=workflow_id)

    @mcp.tool()
    def validate_workflow(
        workflow: Optional[Union[str, Dict[str, Any]]] = None,
        workflow_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Pre-flight: run the converter and return only the structured errors and warnings."""
        return _tools.validate_workflow(cfg, sessions, workflow=workflow, workflow_id=workflow_id)

    @mcp.tool()
    def set_workflow_values(
        updates: List[Dict[str, Any]],
        workflow: Optional[Union[str, Dict[str, Any]]] = None,
        workflow_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Bulk-edit widget values on workflow nodes. Each update: `{node_id?, class_type?, title?, inputs: {name: value}}`. Operates on the active session if `workflow_id` is given."""
        return _tools.set_workflow_values(
            cfg, sessions, updates=updates, workflow=workflow, workflow_id=workflow_id
        )

    # =======================================================================
    # Builder API (8) — all session-based
    # =======================================================================

    @mcp.tool()
    def load_workflow(
        source: Union[str, Dict[str, Any]],
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load a workflow into a new session. `source` may be a file path, JSON string, or workflow dict. Returns a `workflow_id` for subsequent edits."""
        return _tools.load_workflow(cfg, sessions, source=source, label=label)

    @mcp.tool()
    def create_workflow(
        starter: Optional[str] = None,
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start a new workflow session. With `starter`, seed it from the local library (see `search_local_workflows`)."""
        return _tools.create_workflow(cfg, sessions, starter=starter, label=label)

    @mcp.tool()
    def add_node(
        workflow_id: str,
        class_type: str,
        inputs: Optional[Dict[str, Any]] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append a node to the active workflow. `inputs` are widget overrides; connection inputs are made via `connect_nodes` afterwards."""
        return _tools.add_node(
            cfg, sessions, workflow_id=workflow_id, class_type=class_type, inputs=inputs, title=title
        )

    @mcp.tool()
    def connect_nodes(
        workflow_id: str,
        from_node: str,
        to_node: str,
        to_input: str,
        from_output: Optional[Union[str, int]] = None,
    ) -> Dict[str, Any]:
        """Wire `from_node.<from_output>` into `to_node.<to_input>`. If `from_output` is omitted, autograph picks the unique matching output by type."""
        return _tools.connect_nodes(
            cfg, sessions,
            workflow_id=workflow_id,
            from_node=from_node,
            to_node=to_node,
            to_input=to_input,
            from_output=from_output,
        )

    @mcp.tool()
    def disconnect_input(workflow_id: str, node_id: str, input_name: str) -> Dict[str, Any]:
        """Drop the wire feeding a specific input slot."""
        return _tools.disconnect_input(
            cfg, sessions, workflow_id=workflow_id, node_id=node_id, input_name=input_name
        )

    @mcp.tool()
    def remove_node(workflow_id: str, node_id: str) -> Dict[str, Any]:
        """Delete a node and every link touching it."""
        return _tools.remove_node(cfg, sessions, workflow_id=workflow_id, node_id=node_id)

    @mcp.tool()
    def merge_workflow(
        workflow_id: str,
        fragment: Union[str, Dict[str, Any]],
        auto_connect: bool = True,
    ) -> Dict[str, Any]:
        """Graft a workflow fragment into the active session.

        Renumbers the fragment's node + link IDs to avoid collisions, inserts it,
        and (if `auto_connect=True`) tries to wire dangling inputs/outputs against
        the existing graph by slot type when there's a unique match. Returns the
        list of nodes added, what was auto-connected, what's still dangling with
        candidates for the LLM to pick from, and any 'interposer' suggestions for
        nodes that take and produce the same slot type (e.g. LoraLoader on MODEL).
        """
        return _tools.merge_workflow(
            cfg, sessions, workflow_id=workflow_id, fragment=fragment, auto_connect=auto_connect
        )

    @mcp.tool()
    def save_workflow(workflow_id: str, path: Optional[str] = None) -> Dict[str, Any]:
        """Persist the active workflow. With no `path`, writes to its session checkpoint location."""
        return _tools.save_workflow(cfg, sessions, workflow_id=workflow_id, path=path)

    @mcp.tool()
    def get_workflow(workflow_id: str, format: str = "workspace") -> Dict[str, Any]:
        """Return the current workflow JSON (workspace by default, or 'api' for the converted API payload)."""
        return _tools.get_workflow(cfg, sessions, workflow_id=workflow_id, format=format)

    # =======================================================================
    # Session management (2)
    # =======================================================================

    @mcp.tool()
    def list_sessions() -> Dict[str, Any]:
        """List active workflow sessions (workflow_id, label, source path, node count, checkpoint path)."""
        return _tools.list_sessions(cfg, sessions)

    @mcp.tool()
    def close_session(workflow_id: str, delete_checkpoint: bool = False) -> Dict[str, Any]:
        """Drop a session from memory. With `delete_checkpoint=True`, also deletes its on-disk snapshot."""
        return _tools.close_session(
            cfg, sessions, workflow_id=workflow_id, delete_checkpoint=delete_checkpoint
        )

    # =======================================================================
    # Library + sources (3)
    # =======================================================================

    @mcp.tool()
    def list_workflow_sources() -> Dict[str, Any]:
        """Return a curated list of online sources where workflows live (Civitai, OpenArt, ComfyUI examples on GitHub, etc.). The MCP doesn't scrape — the LLM uses its own WebFetch on these URLs."""
        return _tools.list_workflow_sources(cfg)

    @mcp.tool()
    def search_local_workflows(
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Search the local workflow library (bundled starters + ~/.comfyui-autograph/workflows + project-local + AUTOGRAPH_MCP_LIBRARY_DIRS)."""
        return _tools.search_local_workflows(cfg, query=query, tags=tags, limit=limit)

    @mcp.tool()
    def load_local_workflow(name: str, label: Optional[str] = None) -> Dict[str, Any]:
        """Load a library workflow (by name or filename) into a new session."""
        return _tools.load_local_workflow(cfg, sessions, name=name, label=label)

    # =======================================================================
    # Execution (4) — session-aware
    # =======================================================================

    @mcp.tool()
    def run_workflow(
        workflow: Optional[Union[str, Dict[str, Any]]] = None,
        workflow_id: Optional[str] = None,
        wait: bool = True,
        fetch_outputs: bool = True,
        save_to: Optional[str] = None,
        inline_images: bool = True,
        max_inline: Optional[int] = None,
        server_url: Optional[str] = None,
    ) -> List[Union[TextContent, ImageContent]]:
        """Submit a workflow to ComfyUI. Pass `workflow_id` for an active session, or `workflow` (path/JSON/dict) to submit inline. With `wait=True` (default), block until the run finishes and return outputs. Submission failures and execution errors are returned as structured `errors` arrays."""
        payload = _tools.run_workflow(
            cfg, sessions,
            workflow=workflow,
            workflow_id=workflow_id,
            wait=wait,
            fetch_outputs=fetch_outputs,
            save_to=save_to,
            inline_images=inline_images,
            max_inline=max_inline,
            server_url=server_url,
        )
        return _result_with_images(payload)

    @mcp.tool()
    def queue_workflow(
        workflow: Optional[Union[str, Dict[str, Any]]] = None,
        workflow_id: Optional[str] = None,
        server_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fire-and-forget submission. Returns the prompt_id; use `fetch_outputs` later."""
        return _tools.queue_workflow(
            cfg, sessions, workflow=workflow, workflow_id=workflow_id, server_url=server_url
        )

    @mcp.tool()
    def get_history(
        prompt_id: Optional[str] = None,
        limit: int = 10,
        server_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch ComfyUI run history. With a prompt_id, returns just that job; otherwise the most recent jobs."""
        return _tools.get_history(cfg, prompt_id=prompt_id, limit=limit, server_url=server_url)

    @mcp.tool()
    def interrupt(server_url: Optional[str] = None) -> Dict[str, Any]:
        """Cancel the currently-running ComfyUI job."""
        return _tools.interrupt(cfg, server_url=server_url)

    # =======================================================================
    # Files / outputs (3)
    # =======================================================================

    @mcp.tool()
    def upload_file(
        local_path: str,
        accept: Optional[Union[str, List[str]]] = None,
        subfolder: Optional[str] = None,
        overwrite: bool = False,
        server_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload a local file (or directory of matching files) to ComfyUI's input store.

        `accept` may be a kind ('image'/'audio'/'video'/'text'/'archive'/'model'),
        a MIME pattern ('image/*'), an exact MIME type, an extension, or a list of those.
        """
        return _tools.upload_file(
            cfg,
            local_path=local_path,
            accept=accept,
            subfolder=subfolder,
            overwrite=overwrite,
            server_url=server_url,
        )

    @mcp.tool()
    def fetch_outputs(
        prompt_id: str,
        save_to: Optional[str] = None,
        kinds: Optional[Union[str, List[str]]] = None,
        inline_images: bool = True,
        max_inline: Optional[int] = None,
        server_url: Optional[str] = None,
    ) -> List[Union[TextContent, ImageContent]]:
        """Retrieve outputs for a previous prompt_id. Same image-cap policy as run_workflow."""
        payload = _tools.fetch_outputs(
            cfg,
            prompt_id=prompt_id,
            save_to=save_to,
            kinds=kinds,
            inline_images=inline_images,
            max_inline=max_inline,
            server_url=server_url,
        )
        return _result_with_images(payload)

    @mcp.tool()
    def list_outputs(prompt_id: str, server_url: Optional[str] = None) -> Dict[str, Any]:
        """Enumerate the output files of a past job without downloading them."""
        return _tools.list_outputs(cfg, prompt_id=prompt_id, server_url=server_url)

    # =======================================================================
    # Resources
    # =======================================================================

    @mcp.resource("comfyui://node-info", mime_type="application/json")
    def _resource_node_info() -> str:
        return _resources.node_info_resource(cfg)

    @mcp.resource("comfyui://history/{prompt_id}", mime_type="application/json")
    def _resource_history(prompt_id: str) -> str:
        return json.dumps(_resources.history_resource(cfg, prompt_id), default=str, indent=2)

    @mcp.resource("comfyui://outputs/{prompt_id}/{filename}")
    def _resource_output(prompt_id: str, filename: str) -> bytes:
        return _resources.output_resource(cfg, prompt_id, filename)

    # =======================================================================
    # Prompts
    # =======================================================================

    @mcp.prompt(
        name="text_to_image",
        description="Guided text-to-image conversation: load workflow → set values → render.",
    )
    def _prompt_text_to_image(
        prompt: str,
        negative: str = "",
        model: str = "auto",
        steps: int = 20,
        seed: int = 0,
    ) -> str:
        return _prompts.text_to_image(prompt, negative=negative, model=model, steps=steps, seed=seed)

    @mcp.prompt(
        name="diagnose_workflow",
        description="Walk through validation errors on a workflow and propose fixes.",
    )
    def _prompt_diagnose_workflow() -> str:
        return _prompts.diagnose_workflow()

    @mcp.prompt(
        name="vibe_build_workflow",
        description="Vibe-build a ComfyUI workflow: load or start, search the library, graft fragments, run.",
    )
    def _prompt_vibe_build(goal: str = "describe what the user wants to render") -> str:
        return _prompts.vibe_build_workflow(goal)

    return mcp


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="comfyui-autograph-mcp",
        description="MCP server for the comfyui-autograph ComfyUI client.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"comfyui-autograph-mcp {__version__}",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio",),
        default="stdio",
        help="Transport to use (only stdio is supported today; documented for forward compatibility).",
    )
    parser.parse_args(argv)

    server = build_server()
    try:
        server.run()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
