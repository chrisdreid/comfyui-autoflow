# comfyui-autograph MCP Server — IDE Setup

This folder ships drop-in configuration snippets for every major MCP-capable
editor. The MCP server itself lives inside the `autograph` package — it is an
**optional extra** that does not affect the zero-dependency core.

## Install

The MCP server requires Python **3.10+** (the official `mcp` SDK requirement);
the core `comfyui-autograph` library still works on Python 3.7+.

Pick whichever invocation suits you — every IDE config below uses one of them:

```bash
# Zero-install via uv (recommended; no global install needed)
uvx --from "comfyui-autograph[mcp]" comfyui-autograph-mcp

# Or pip-installed:
pip install "comfyui-autograph[mcp]"
comfyui-autograph-mcp                     # console script
python -m autograph.mcp                   # equivalent
```

## Configuration

The server reads autograph's existing environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTOGRAPH_COMFYUI_SERVER_URL` | `http://127.0.0.1:8188` | ComfyUI server URL |
| `AUTOGRAPH_TIMEOUT_S` | `30` | HTTP timeout (seconds) |
| `AUTOGRAPH_OUTPUT_PATH` | `./` | Where to save fetched files |
| `AUTOGRAPH_MCP_MAX_INLINE_IMAGE_BYTES` | `2000000` | Per-image inline cap (bytes) |
| `AUTOGRAPH_MCP_MAX_INLINE_IMAGES` | `4` | Max images returned inline per call |

If `AUTOGRAPH_COMFYUI_SERVER_URL` is unset the MCP falls back to
`http://127.0.0.1:8188`, so a default local ComfyUI just works.

## IDE snippets

| File | Where to put it |
| --- | --- |
| [`claude-desktop.json`](./claude-desktop.json) | Merge into `claude_desktop_config.json` (`~/.config/Claude/` on Linux, `~/Library/Application Support/Claude/` on macOS, `%APPDATA%\Claude\` on Windows) |
| [`claude-code.mcp.json`](./claude-code.mcp.json) | Drop in your project root as `.mcp.json` |
| [`cursor.mcp.json`](./cursor.mcp.json) | `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global) |
| [`vscode.mcp.json`](./vscode.mcp.json) | `.vscode/mcp.json` for Copilot's MCP support |
| [`zed.settings.json`](./zed.settings.json) | Merge into `~/.config/zed/settings.json` |
| [`continue.config.json`](./continue.config.json) | Merge into `~/.continue/config.json` |

Every snippet uses the canonical `uvx` command. If you prefer a pip install,
swap the `command`/`args` for `"command": "comfyui-autograph-mcp", "args": []`.

## Available tools (15)

| Tool | What it does |
| --- | --- |
| `comfyui_status` | Server reachable + queue depth + system stats |
| `list_node_types` | Search the node catalog |
| `describe_node_type` | Full input/output/widget spec for one class_type |
| `list_models` | Checkpoints / loras / vae / etc. |
| `inspect_workflow` | Summarize a workflow's nodes (file path, JSON, or dict) |
| `convert_workflow` | Workspace → API format with structured errors |
| `validate_workflow` | Pre-flight error/warning report |
| `set_workflow_values` | Bulk-edit widgets by node_id / class_type / title |
| `run_workflow` | Submit, wait, fetch outputs, return inline images |
| `queue_workflow` | Fire-and-forget, returns prompt_id |
| `get_history` | Recent runs (or one by prompt_id) |
| `interrupt` | Cancel current job |
| `upload_file` | Upload to ComfyUI input dir (image/audio/video/text/archive/model) |
| `fetch_outputs` | Retrieve outputs for a past prompt_id |
| `list_outputs` | Enumerate output files without downloading |

Plus the resources `comfyui://node-info`, `comfyui://history/{prompt_id}`,
`comfyui://outputs/{prompt_id}/{filename}` and the prompts `text_to_image` and
`diagnose_workflow`.

## Verify it works

After configuring your IDE and restarting it, ask:

> *Use the autograph MCP to check whether ComfyUI is running.*

Expected: the assistant calls `comfyui_status` and reports the queue depth.

For interactive debugging without an IDE:

```bash
npx @modelcontextprotocol/inspector \
  uvx --from "comfyui-autograph[mcp]" comfyui-autograph-mcp
```

The Inspector opens a local web UI where you can call every tool by hand.
