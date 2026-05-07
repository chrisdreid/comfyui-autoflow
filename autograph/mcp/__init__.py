"""Optional MCP (Model Context Protocol) server for comfyui-autograph.

The core ``autograph`` package is intentionally zero-dependency. This sub-package
is opt-in: install with ``pip install comfyui-autograph[mcp]`` (which pulls in the
``mcp`` Python SDK) and run with ``comfyui-autograph-mcp`` or ``python -m autograph.mcp``.

Importing ``autograph`` does NOT import this package, so the zero-dependency
promise of the core library is preserved.
"""

try:
    from mcp.server.fastmcp import FastMCP  # noqa: F401
except ImportError as exc:
    raise ImportError(
        "The MCP server requires the 'mcp' package.\n"
        "Install with:  pip install 'comfyui-autograph[mcp]'\n"
        "or:            uvx --from 'comfyui-autograph[mcp]' comfyui-autograph-mcp\n"
        "Note: the [mcp] extra requires Python 3.10+."
    ) from exc

from .server import build_server, main  # noqa: E402,F401

__all__ = ["build_server", "main"]
