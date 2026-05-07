# MCP Server (`comfyui-autograph[mcp]`)

`comfyui-autograph` ships an optional **Model Context Protocol** server so that any
MCP-capable IDE — Claude Desktop, Claude Code, Cursor, VS Code (Copilot, Continue,
Cline), Zed, and others — can drive ComfyUI through natural-language tool calls.

The MCP server lives inside the `autograph` package as a subpackage
(`autograph.mcp`), but it is **opt-in**: importing `autograph` does not import it,
and installing `comfyui-autograph` without the `[mcp]` extra still pulls in zero
runtime dependencies. Activate the extra only when you want to run the server.

---

## Install

The `mcp` Python SDK requires **Python 3.10+**. The core `comfyui-autograph`
library still works on Python 3.7+; only the `[mcp]` extra has the higher floor.

Pick whichever invocation suits you:

```bash
# Zero-install via uv (no global pollution):
uvx --from "comfyui-autograph[mcp]" comfyui-autograph-mcp

# Pip install:
pip install "comfyui-autograph[mcp]"
comfyui-autograph-mcp                     # console-script entry point
python -m autograph.mcp                   # equivalent
```

If `mcp` isn't installed, importing `autograph.mcp` raises a friendly
`ImportError` pointing back here.

---

## Configure your IDE

The repo ships ready-to-merge JSON snippets in [`examples/mcp/`](../examples/mcp/).

### Claude Desktop

Merge into `claude_desktop_config.json`
(`~/.config/Claude/` on Linux, `~/Library/Application Support/Claude/` on macOS,
`%APPDATA%\Claude\` on Windows):

```json
{
  "mcpServers": {
    "comfyui-autograph": {
      "command": "uvx",
      "args": ["--from", "comfyui-autograph[mcp]", "comfyui-autograph-mcp"],
      "env": { "AUTOGRAPH_COMFYUI_SERVER_URL": "http://127.0.0.1:8188" }
    }
  }
}
```

### Claude Code

Drop in your project root as `.mcp.json` (same JSON shape as Claude Desktop above).

### Cursor

`.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global). Same shape.
Cursor warns if you go over its ~40-tool ceiling across all servers; the
autograph MCP exposes only 15 tools so it stays well under.

### VS Code (Copilot)

`.vscode/mcp.json`:

```json
{
  "servers": {
    "comfyui-autograph": {
      "command": "uvx",
      "args": ["--from", "comfyui-autograph[mcp]", "comfyui-autograph-mcp"],
      "env": { "AUTOGRAPH_COMFYUI_SERVER_URL": "http://127.0.0.1:8188" }
    }
  }
}
```

### Continue

Merge into `~/.continue/config.json` under `experimental.mcpServers`:

```json
{
  "experimental": {
    "mcpServers": {
      "comfyui-autograph": {
        "command": "uvx",
        "args": ["--from", "comfyui-autograph[mcp]", "comfyui-autograph-mcp"]
      }
    }
  }
}
```

### Zed

Merge into `~/.config/zed/settings.json`:

```json
{
  "context_servers": {
    "comfyui-autograph": {
      "command": {
        "path": "uvx",
        "args": ["--from", "comfyui-autograph[mcp]", "comfyui-autograph-mcp"],
        "env": { "AUTOGRAPH_COMFYUI_SERVER_URL": "http://127.0.0.1:8188" }
      }
    }
  }
}
```

### Pip-installed alternative (any IDE)

If you'd rather install once with pip and skip `uvx`:

```json
{ "command": "comfyui-autograph-mcp", "args": [] }
```

---

## Tools

| Tool | Parameters | Returns |
| --- | --- | --- |
| `comfyui_status` | `server_url?` | `{server_url, reachable, system_stats?, queue?}` |
| `list_node_types` | `query?, category?, limit=50, server_url?` | `{count, node_types: [{class_type, display_name, category, output_node}]}` |
| `describe_node_type` | `class_type, server_url?` | `{class_type, definition}` |
| `list_models` | `folder?, server_url?` | `{folder, data}` |
| `inspect_workflow` | `workflow` | `{node_count, nodes: [...]}` |
| `convert_workflow` | `workflow` | `{ok, errors, warnings, api_workflow, ...}` |
| `validate_workflow` | `workflow` | `{ok, errors, warnings, ...}` |
| `set_workflow_values` | `workflow, updates: [{node_id?, class_type?, title?, inputs}]` | `{applied, workflow}` |
| `run_workflow` | `workflow, wait=True, fetch_outputs=True, save_to?, inline_images=True, max_inline?, server_url?` | JSON summary + inline image content |
| `queue_workflow` | `workflow, server_url?` | `{prompt_id, server_url}` |
| `get_history` | `prompt_id?, limit=10, server_url?` | `{history}` |
| `interrupt` | `server_url?` | `{ok}` |
| `upload_file` | `local_path, accept?, subfolder?, overwrite=False, server_url?` | `{uploaded: [{name, path, kind, mime_type, ...}]}` |
| `fetch_outputs` | `prompt_id, save_to?, kinds?, inline_images=True, max_inline?, server_url?` | JSON summary + inline image content |
| `list_outputs` | `prompt_id, server_url?` | `{outputs: [{node_id, kind, filename, resource_uri, ...}]}` |

`workflow` arguments accept a workflow file path, a JSON string, or a workflow
dict — the MCP picks the right one automatically.

The `accept` argument on `upload_file` accepts:
* a kind: `"image"`, `"audio"`, `"video"`, `"text"`, `"archive"`, `"model"`
* a MIME pattern: `"image/*"`
* an exact MIME type: `"image/png"`
* an extension: `".safetensors"`
* or a list of any of the above

---

## Resources

* `comfyui://node-info` — full node_info catalog (JSON)
* `comfyui://history/{prompt_id}` — single job's history (JSON)
* `comfyui://outputs/{prompt_id}/{filename}` — output file bytes

---

## Prompts

* `text_to_image(prompt, negative?, model?, steps?, seed?)` — guided
  text-to-image conversation that walks the LLM through inspect → set values →
  validate → run.
* `diagnose_workflow()` — walks the LLM through validation errors and proposes
  fixes the user can apply with `set_workflow_values`.

---

## Configuration (env vars)

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTOGRAPH_COMFYUI_SERVER_URL` | `http://127.0.0.1:8188` | ComfyUI server URL |
| `AUTOGRAPH_TIMEOUT_S` | `30` | HTTP timeout (seconds) |
| `AUTOGRAPH_OUTPUT_PATH` | `./` | Where to save fetched files |
| `AUTOGRAPH_MCP_MAX_INLINE_IMAGE_BYTES` | `2000000` | Per-image inline cap (bytes) |
| `AUTOGRAPH_MCP_MAX_INLINE_IMAGES` | `4` | Max images returned inline per call |

The first three are the same env vars autograph itself reads. The MCP cap vars
are new; both can also be overridden per-call via `inline_images=False` or
`max_inline=N` on `run_workflow` / `fetch_outputs`.

Unlike autograph's strict `resolve_comfy_server_url` — which raises if the URL
is neither passed nor in the environment — the MCP server falls back to
`http://127.0.0.1:8188` so a default local ComfyUI just works.

---

## Image return policy

Generated images are returned to the client as **inline base64**
`ImageContent` blocks so the LLM can actually see them, but with two safety
caps (configurable per call or via env vars):

* **Per-image bytes cap** — images larger than `max_inline_image_bytes` are
  saved to disk and returned as a file path + `comfyui://` resource URI
  instead.
* **Per-call count cap** — once `max_inline_images` images have been inlined,
  remaining ones fall back to file paths/URIs.

The smallest images are inlined first, so if you produce a single large + many
small outputs, the small ones still preview inline while the large one becomes
a link.

Pass `inline_images=False` to skip inlining entirely (great when a workflow
spits out hundreds of grid frames).

---

## Troubleshooting

**`ImportError: The MCP server requires the 'mcp' package.`**
Install the extra: `pip install 'comfyui-autograph[mcp]'`. Note Python 3.10+ is
required.

**`comfyui_status` returns `reachable: false`.**
Either ComfyUI is not running, or `AUTOGRAPH_COMFYUI_SERVER_URL` points at the
wrong host/port. Test directly: `curl http://127.0.0.1:8188/system_stats`.

**`run_workflow` returns no `content_blocks`.**
The job may not have produced any registered outputs (no SaveImage / equivalent
node). Try `list_outputs(prompt_id=...)` against the returned `prompt_id`.

**Cursor warns about a tool ceiling.**
Cursor caps total MCP tools across all configured servers around 40. The
autograph MCP only exposes 15, so the warning is about another server in your
config — disable any you don't need.

**Image previews never show inline.**
Either the client doesn't render `ImageContent` (rare among MCP clients), or
the images exceed the cap. Lower `max_inline` to 1 and re-run; check the
returned summary's `inlined: true/false` field.

---

## Verify it works

```bash
# 1. Core stays clean (no mcp installed)
pip install -e .
python -c "import autograph; print(autograph.__version__)"

# 2. With the extra
pip install -e ".[mcp]"
comfyui-autograph-mcp --help
python -m autograph.mcp --help

# 3. Inspect tools interactively
npx @modelcontextprotocol/inspector \
  uvx --from "comfyui-autograph[mcp]" comfyui-autograph-mcp
```
