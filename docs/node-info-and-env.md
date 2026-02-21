# NodeInfo + env vars

`NodeInfo` is the schema ComfyUI returns from `GET /object_info`. autoflow uses it to translate a workspace workflow into an API payload.

autoflow normalizes `node_info` inputs through a shared resolver, so you can pass:
- a dict-like `NodeInfo` (including flowtree `NodeInfo`)
- a file path
- a URL
- `"modules"` / `"from_comfyui_modules"` for direct module loading

Server URLs are normalized the same way: empty strings are treated as missing, and
`AUTOFLOW_COMFYUI_SERVER_URL` is used when server_url is omitted in conversion paths.

If `AUTOFLOW_NODE_INFO_SOURCE` is set, `NodeInfo()`, `Flow`, `ApiFlow`, `Workflow`, and
conversion helpers will auto-resolve node_info when none is provided.

If it is **not** set, `NodeInfo()` returns an **empty** node_info (no error), and you can
load/fetch later.

```mermaid
flowchart LR
  workflowJson["workflow.json"] --> convertFn["Workflow(...)"]
  objectInfo["/object_info or node_info.json"] --> convertFn
  convertFn --> apiFlow["ApiFlow"]
```

## Recommended: set server URL once

Set `AUTOFLOW_COMFYUI_SERVER_URL` once and `server_url` / `--server-url` become optional everywhere.

```mermaid
flowchart LR
  env["AUTOFLOW_COMFYUI_SERVER_URL"] --> convert["Workflow(...)"]
  convert --> apiFlow["ApiFlow"]
```

```bash
# cli
# Linux/macOS
export AUTOFLOW_COMFYUI_SERVER_URL="http://localhost:8188"

# Windows PowerShell
$env:AUTOFLOW_COMFYUI_SERVER_URL = "http://localhost:8188"

# Windows CMD
set AUTOFLOW_COMFYUI_SERVER_URL=http://localhost:8188
```

```python
# api
import os
os.environ["AUTOFLOW_COMFYUI_SERVER_URL"] = "http://localhost:8188"
```

## Fetch and save node_info.json

Save `node_info.json` for offline/reproducible conversion (no server needed later).

```mermaid
flowchart LR
  comfy["ComfyUI server"] --> objectInfo["/object_info"]
  objectInfo --> file["node_info.json"]
```

```python
# api
from autoflow import NodeInfo

# Fetch from server and save
oi = NodeInfo.fetch(server_url="http://localhost:8188", output_path="node_info.json")

# Or fetch then save separately
oi = NodeInfo.fetch()
oi.save("node_info.json")
```

```bash
# cli
python -m autoflow --download-node-info-path node_info.json --server-url http://localhost:8188
```

## Load from file

```python
# api
from autoflow import NodeInfo

oi = NodeInfo.load("node_info.json")
```

## Load from ComfyUI modules (direct)

If you're running inside a ComfyUI environment (repo + venv), you can build an
`NodeInfo` from local node modules without starting the server.

**Environment note**: this requires ComfyUI’s Python modules to be importable (same venv/conda env you run ComfyUI with, and ComfyUI repo root on `PYTHONPATH` or as your working directory).

Related:
- Serverless execution (no ComfyUI HTTP server): [`execute.md`](execute.md)

```python
# api
from autoflow import NodeInfo

oi = NodeInfo.from_comfyui_modules()
# or (equivalent explicit source)
oi = NodeInfo("modules")
oi = NodeInfo(source="modules")
```

## NodeInfo API

| Method | Description |
|--------|-------------|
| `NodeInfo.fetch(server_url=, timeout=, output_path=)` | Fetch from ComfyUI server |
| `NodeInfo().fetch(server_url=, timeout=)` | Fetch and **mutate in-place** (returns `self`) |
| `NodeInfo.load(path_or_json_str)` | Load from file or JSON string |
| `.save(path)` | Write to disk |
| `.to_json()` | Serialize to JSON string |

## Optional env vars (defaults)

These env vars override library defaults (precedence is always args → env → default):

| Env var | Type | Meaning |
|--------|------|---------|
| `AUTOFLOW_TIMEOUT_S` | int | Default HTTP timeout seconds |
| `AUTOFLOW_POLL_INTERVAL_S` | float | Poll interval for wait/poll loops |
| `AUTOFLOW_WAIT_TIMEOUT_S` | int | Default wait timeout seconds |
| `AUTOFLOW_SUBMIT_CLIENT_ID` | str | Default `client_id` for submit |
| `AUTOFLOW_SUBGRAPH_MAX_DEPTH` | int | Default max depth for subgraph flattening |
| `AUTOFLOW_FIND_MAX_DEPTH` | int | Default max depth for `flow.find(...)` / `flow.nodes.find(...)` recursion |
| `AUTOFLOW_NODE_INFO_SOURCE` | str | Source for `node_info`: `fetch`, `modules`, `server`, or a file path |

### AUTOFLOW_NODE_INFO_SOURCE

Supported values:
- `fetch`: Use `server_url` / `AUTOFLOW_COMFYUI_SERVER_URL` if set; otherwise fall back to modules.
- `modules`: Use local ComfyUI modules (`NodeInfo.from_comfyui_modules()`).
- `server`: Require `server_url` / `AUTOFLOW_COMFYUI_SERVER_URL`; error if missing.
- any other value is treated as a file path to `node_info.json`.

Notes:
- Resolution is in-process only (no disk cache). `fetch` mode refreshes each call.

## Deprecated / experimental: model layer switch

autoflow currently supports an **internal** model implementation switch via an env var.

- This is **experimental** and may be removed before release.
- Only use it for local exploration/testing (don’t depend on it in production code).

**Env var**: `AUTOFLOW_MODEL_LAYER`

- `AUTOFLOW_MODEL_LAYER=flowtree` (default): wrapper-based, terminal-first navigation layer
- `AUTOFLOW_MODEL_LAYER=models`: legacy-parity dict-subclass layer

Set it **before importing** `autoflow`:

```bash
# Linux/macOS
export AUTOFLOW_MODEL_LAYER=models

# Windows PowerShell
$env:AUTOFLOW_MODEL_LAYER = "models"

# Windows CMD
set AUTOFLOW_MODEL_LAYER=models
```

