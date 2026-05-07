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
    """Pull image content blocks out of a tool payload and front-load a JSON summary."""
    blocks = payload.pop("content_blocks", []) or []
    summary = TextContent(type="text", text=json.dumps(payload, default=str, indent=2))
    return [summary, *_materialize_content_blocks(blocks)]


def build_server(config: Optional[McpConfig] = None) -> FastMCP:
    """Construct (but do not run) the FastMCP server. Used by tests too."""
    cfg = config or load_config()
    mcp = FastMCP(
        "comfyui-autograph",
        instructions=(
            "ComfyUI driver via the autograph client. Use `comfyui_status` first to confirm "
            "the server is reachable, `inspect_workflow` to read a workflow, "
            "`set_workflow_values` to edit it, and `run_workflow` to render. "
            "Generated images are returned inline (base64) up to a per-call cap; large or "
            "numerous outputs are returned as file paths and `comfyui://` resource URIs."
        ),
    )

    # ---------- server / introspection ----------

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

    # ---------- workflow inspection / editing ----------

    @mcp.tool()
    def inspect_workflow(workflow: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Summarize a workflow. `workflow` may be a file path, JSON string, or workflow dict."""
        return _tools.inspect_workflow(cfg, workflow)

    @mcp.tool()
    def convert_workflow(workflow: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Convert a workspace workflow to ComfyUI's API format and return both result and structured errors."""
        return _tools.convert_workflow(cfg, workflow)

    @mcp.tool()
    def validate_workflow(workflow: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Pre-flight: run the converter and return only the structured errors and warnings."""
        return _tools.validate_workflow(cfg, workflow)

    @mcp.tool()
    def set_workflow_values(
        workflow: Union[str, Dict[str, Any]],
        updates: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Bulk-edit widget values on workflow nodes. Each update: `{node_id?, class_type?, title?, inputs: {name: value}}`."""
        return _tools.set_workflow_values(cfg, workflow, updates)

    # ---------- execution ----------

    @mcp.tool()
    def run_workflow(
        workflow: Union[str, Dict[str, Any]],
        wait: bool = True,
        fetch_outputs: bool = True,
        save_to: Optional[str] = None,
        inline_images: bool = True,
        max_inline: Optional[int] = None,
        server_url: Optional[str] = None,
    ) -> List[Union[TextContent, ImageContent]]:
        """Submit a workflow to ComfyUI. With wait=True (default), block until the run finishes and return outputs.

        Generated images are returned inline (base64) up to the configured caps; anything larger
        is returned as a file path plus a `comfyui://outputs/...` resource URI.
        """
        payload = _tools.run_workflow(
            cfg,
            workflow,
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
        workflow: Union[str, Dict[str, Any]],
        server_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fire-and-forget submission. Returns the prompt_id; use `fetch_outputs` later to retrieve results."""
        return _tools.queue_workflow(cfg, workflow, server_url=server_url)

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

    # ---------- files / outputs ----------

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

    # ---------- resources ----------

    @mcp.resource("comfyui://node-info", mime_type="application/json")
    def _resource_node_info() -> str:
        return _resources.node_info_resource(cfg)

    @mcp.resource("comfyui://history/{prompt_id}", mime_type="application/json")
    def _resource_history(prompt_id: str) -> str:
        return json.dumps(_resources.history_resource(cfg, prompt_id), default=str, indent=2)

    @mcp.resource("comfyui://outputs/{prompt_id}/{filename}")
    def _resource_output(prompt_id: str, filename: str) -> bytes:
        return _resources.output_resource(cfg, prompt_id, filename)

    # ---------- prompts ----------

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

    return mcp


def main(argv: Optional[List[str]] = None) -> None:
    """Console-script entry point. Parses minimal CLI flags then runs the FastMCP server."""
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
    # FastMCP.run() with no transport defaults to stdio.
    try:
        server.run()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
