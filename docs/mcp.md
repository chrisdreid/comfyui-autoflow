# MCP Server (`comfyui-autograph[mcp]`)

`comfyui-autograph` ships an optional **Model Context Protocol** server so any
MCP-capable IDE — Claude Desktop, Claude Code, Cursor, VS Code (Copilot,
Continue, Cline), Zed, and others — can drive ComfyUI through natural-language
tool calls.

It is a **workhorse for back-end workflow editing**: load a workflow file,
inspect the node graph, edit widgets, add and connect new nodes, graft in
fragments the LLM finds online, validate, and submit — all without opening the
GUI. Generated images come back inline so the LLM can actually see them.

The MCP server lives inside the `autograph` package as a subpackage
(`autograph.mcp`), but it is **opt-in**: importing `autograph` does not import
it, and installing `comfyui-autograph` without the `[mcp]` extra still pulls in
zero runtime dependencies.

---

## Install

The `mcp` Python SDK requires **Python 3.10+**. The core `comfyui-autograph`
library still works on Python 3.7+; only the `[mcp]` extra has the higher floor.

```bash
# Zero-install via uv (no global pollution):
uvx --from "comfyui-autograph[mcp]" comfyui-autograph-mcp

# Or pip install:
pip install "comfyui-autograph[mcp]"
comfyui-autograph-mcp                     # console-script entry point
python -m autograph.mcp                   # equivalent
```

If `mcp` isn't installed, importing `autograph.mcp` raises a friendly
`ImportError` pointing back here.

---

## Configure your IDE

Drop-in JSON snippets ship in [`examples/mcp/`](../examples/mcp/) for Claude
Desktop, Claude Code, Cursor, VS Code (Copilot), Continue, and Zed. Every one
uses the canonical command:

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

If `AUTOGRAPH_COMFYUI_SERVER_URL` is unset the MCP falls back to
`http://127.0.0.1:8188`, so a default local ComfyUI just works.

---

## How it works: stateful sessions

The MCP keeps an in-memory store of **live workflow sessions**, each keyed by
a stable `workflow_id`. The typical flow:

1. **Open** — `load_workflow(source=...)` (or `create_workflow()` /
   `load_local_workflow(name=...)`) returns a `workflow_id`.
2. **Inspect/edit** — every editing tool (`add_node`, `connect_nodes`,
   `set_workflow_values`, `merge_workflow`, …) takes that `workflow_id` and
   mutates the live workflow.
3. **Auto-checkpoint** — every mutation auto-writes a snapshot to
   `~/.comfyui-autograph/sessions/<workflow_id>.json`. If your IDE restarts
   mid-edit the workflow is still on disk.
4. **Run** — `run_workflow(workflow_id=...)` submits to ComfyUI, waits, and
   returns inline images plus structured errors when things go wrong.
5. **Save / close** — `save_workflow(workflow_id, path=...)` writes a clean
   copy. `close_session(workflow_id, delete_checkpoint=True)` cleans up.

Read-only tools (`inspect_workflow`, `validate_workflow`, `convert_workflow`)
also accept an inline `workflow` argument (file path, JSON string, or dict)
when you don't want to start a session.

---

## Tools

### Server / introspection

| Tool | What it does |
| --- | --- |
| `comfyui_status` | Reachable? Queue depth + system stats. |
| `list_node_types(query?, category?, limit=50)` | Search the node catalog (substring on class_type / display_name). |
| `describe_node_type(class_type)` | Full input / output / widget spec for one class. |
| `list_models(folder?)` | Checkpoints / loras / vae / etc. via ComfyUI's `/models`. |

### Inspection / editing

| Tool | What it does |
| --- | --- |
| `inspect_workflow(workflow? | workflow_id?)` | Compact node summary with wired vs free inputs. |
| `convert_workflow(workflow? | workflow_id?)` | Workspace → API format with structured errors. |
| `validate_workflow(workflow? | workflow_id?)` | Pre-flight error / warning report. |
| `set_workflow_values(updates, workflow? | workflow_id?)` | Bulk widget edits by `node_id`, `class_type`, or `title`. |

### Builder API (session-only)

| Tool | What it does |
| --- | --- |
| `load_workflow(source, label?)` | Open a path / JSON / dict into a new session. |
| `create_workflow(starter?, label?)` | New empty session, optionally seeded from the local library. |
| `add_node(workflow_id, class_type, inputs?, title?)` | Append a node; `inputs` are widget overrides. |
| `connect_nodes(workflow_id, from_node, to_node, to_input, from_output?)` | Wire two nodes; auto-resolves output by type if omitted. |
| `disconnect_input(workflow_id, node_id, input_name)` | Drop the wire feeding one input. |
| `remove_node(workflow_id, node_id)` | Delete a node and every link touching it. |
| `merge_workflow(workflow_id, fragment, auto_connect=True)` | Graft a fragment with renumbering + auto-stitch. |
| `save_workflow(workflow_id, path?)` | Write to disk (or to the session checkpoint if `path` is omitted). |
| `get_workflow(workflow_id, format="workspace"|"api")` | Dump the current JSON. |

### Session management

| Tool | What it does |
| --- | --- |
| `list_sessions()` | All live workflow ids with metadata. |
| `close_session(workflow_id, delete_checkpoint=False)` | Drop from memory; optionally delete the snapshot. |

### Library + sources

| Tool | What it does |
| --- | --- |
| `list_workflow_sources()` | Curated URL list (Civitai, OpenArt, ComfyUI examples on GitHub, …). The MCP doesn't scrape — your assistant uses its own WebFetch on these. |
| `search_local_workflows(query?, tags?, limit=20)` | Search the local library (bundled starters + `~/.comfyui-autograph/workflows` + project-local + `AUTOGRAPH_MCP_LIBRARY_DIRS`). |
| `load_local_workflow(name, label?)` | Open a library workflow into a new session. |

### Execution

| Tool | What it does |
| --- | --- |
| `run_workflow(workflow? | workflow_id?, wait=True, fetch_outputs=True, save_to?, inline_images=True, max_inline?)` | Submit, optionally wait, return inline images. Submission and execution failures come back as structured `errors` arrays. |
| `queue_workflow(...)` | Fire-and-forget; returns `prompt_id`. |
| `get_history(prompt_id?, limit=10)` | Recent runs (or one by id). |
| `interrupt()` | Cancel current job. |

### Files / outputs

| Tool | What it does |
| --- | --- |
| `upload_file(local_path, accept?, subfolder?, overwrite=False)` | Push files into ComfyUI's input store. `accept` accepts kinds (`image`/`audio`/`video`/`text`/`archive`/`model`), MIME patterns, exact MIME types, or extensions. |
| `fetch_outputs(prompt_id, save_to?, kinds?, inline_images=True, max_inline?)` | Retrieve outputs of a past job. |
| `list_outputs(prompt_id)` | Enumerate outputs without downloading. |

---

## The `merge_workflow` graft engine

This is the heart of "vibe-add a feature." When the LLM finds a workflow JSON
online (or in the library) that does what the user wants, it hands the JSON to
`merge_workflow` and gets back a structured report.

What the engine does:

1. **Renumber** — every node id and link id in the fragment shifts by the active
   workflow's `last_node_id` / `last_link_id` so nothing collides.
2. **Insert** — nodes and links splice into the active graph; positions get
   offset (default `+450, 0`) so the fragment lands to the right.
3. **Detect dangling slots** — fragment inputs with no incoming link, fragment
   outputs with no outgoing link.
4. **Auto-stitch by type** — for each dangling fragment input, look for a
   producer of that type in the existing graph (excluding the fragment).
   Wire it if there's exactly one match. Same for dangling outputs that find
   a unique free input.
5. **Suggest interposers** — when a fragment node both takes and produces the
   same slot type (e.g. `LoraLoader` on `MODEL`), the engine flags it as an
   "interposer" and emits a hint explaining how to slot it into an existing
   path (disconnect → connect → connect).

Return shape:

```json
{
  "added_nodes":              [{ "node_id": "42", "class_type": "VAEDecode", "title": "" }],
  "node_id_map":              { "1": "42" },
  "auto_connected":           [{ "from": {...}, "to": {...}, "slot_type": "VAE", "reason": "unique-source-by-type" }],
  "still_dangling_inputs":    [{ "node_id": "42", "input_name": "samples", "input_type": "LATENT", "candidates": [...] }],
  "still_dangling_outputs":   [],
  "interposer_suggestions":   []
}
```

The LLM then calls `connect_nodes` for each entry in `still_dangling_*` until
`validate_workflow` is clean.

---

## The local workflow library

The MCP searches these directories in priority order:

1. Anything in `$AUTOGRAPH_MCP_LIBRARY_DIRS` (colon-separated dirs).
2. `./.autograph-workflows/` (project-local).
3. `~/.comfyui-autograph/workflows/` (user-home).
4. The bundled `examples/workflows/starters/` directory.

A library entry is a `*.json` workflow plus an optional `*.metadata.json`
sidecar:

```json
{
  "name": "txt2img-basic",
  "title": "Text-to-image (basic)",
  "description": "...",
  "tags": ["txt2img", "basic"],
  "models_required": [],
  "source": "https://github.com/comfyanonymous/ComfyUI_examples"
}
```

Drop your own workflows into `~/.comfyui-autograph/workflows/` — they'll be
discoverable on the next call to `search_local_workflows`.

---

## Resources

* `comfyui://node-info` — full node_info catalog (JSON)
* `comfyui://history/{prompt_id}` — single job's history (JSON)
* `comfyui://outputs/{prompt_id}/{filename}` — output file bytes

## Prompts

* `text_to_image(prompt, negative?, model?, steps?, seed?)` — guided
  text-to-image conversation that walks the LLM through inspect → set values →
  validate → run.
* `diagnose_workflow()` — walk through validation errors and propose fixes.
* `vibe_build_workflow(goal)` — end-to-end build template: load or start →
  search the library → graft fragments → run.

---

## Configuration (env vars)

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTOGRAPH_COMFYUI_SERVER_URL` | `http://127.0.0.1:8188` | ComfyUI server URL |
| `AUTOGRAPH_TIMEOUT_S` | `30` | HTTP timeout (seconds) |
| `AUTOGRAPH_OUTPUT_PATH` | `./` | Where to save fetched files |
| `AUTOGRAPH_MCP_MAX_INLINE_IMAGE_BYTES` | `2000000` | Per-image inline cap (bytes) |
| `AUTOGRAPH_MCP_MAX_INLINE_IMAGES` | `4` | Max images returned inline per call |
| `AUTOGRAPH_MCP_SESSION_DIR` | `~/.comfyui-autograph/sessions` | Where session checkpoints land |
| `AUTOGRAPH_MCP_LIBRARY_DIRS` | _(unset)_ | Colon-separated extra workflow library dirs |

---

## Image return policy

Generated images come back as inline base64 `ImageContent` so the LLM can see
them, with two safety caps (configurable per call or via env vars):

* **Per-image bytes cap** — anything bigger is saved to disk and returned as a
  file path + `comfyui://` resource URI.
* **Per-call count cap** — once `max_inline_images` images have been inlined,
  the rest fall back to file paths/URIs.

Smallest images are inlined first. Pass `inline_images=False` to skip inlining
entirely (useful for grid renders).

---

## Error feedback

`run_workflow` and `queue_workflow` parse two kinds of failure into actionable
JSON:

* **Submission failures** (HTTP 400 from `/prompt`) — the body's `error` and
  `node_errors` are flattened into a list of
  `{node_id, class_type, error_type, message, details?}`.
* **Execution failures** (status messages on the history entry) — likewise
  flattened so the LLM can name the offending node and propose a fix.

The successful case returns `ok: true`; failures return `ok: false` with the
`errors` array populated.

---

## A vibe-build walkthrough

User: *"Take `flow.json`, add a LoRA stage, and render with seed 42."*

LLM (rough sequence of tool calls):

1. `comfyui_status` — verify server.
2. `load_workflow(source="flow.json")` → gets `wf_xxxx`.
3. `inspect_workflow(workflow_id="wf_xxxx")` — sees the existing graph.
4. `list_models(folder="loras")` — confirms what LoRAs are installed.
5. `list_node_types(query="lora")` → finds `LoraLoader`.
6. `describe_node_type("LoraLoader")` — confirms `MODEL`, `CLIP` in/out and
   `lora_name`, `strength_model`, `strength_clip` widgets.
7. `add_node(workflow_id="wf_xxxx", class_type="LoraLoader", inputs={...})`.
8. The LoraLoader is an interposer (MODEL in / MODEL out). The LLM uses
   `disconnect_input` on the existing KSampler's `model` input, then two
   `connect_nodes` calls to thread the LoRA between the checkpoint loader and
   the sampler.
9. `set_workflow_values(workflow_id="wf_xxxx", updates=[{"class_type":"KSampler","inputs":{"seed":42}}])`.
10. `validate_workflow(workflow_id="wf_xxxx")` — clean.
11. `run_workflow(workflow_id="wf_xxxx", wait=True, fetch_outputs=True)` — image lands inline.
12. `save_workflow(workflow_id="wf_xxxx", path="flow.lora.json")`.

If step 11 returns `ok: false`, the LLM uses the structured `errors` to fix
and retry without the user having to dig through ComfyUI's logs.

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
