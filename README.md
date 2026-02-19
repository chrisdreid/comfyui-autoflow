<!-- Keep version below in sync with autoflow/version.py -->
```text
ComfyUI 
 █████╗ ██╗   ██╗████████╗ ██████╗ ███████╗██╗      ██████╗ ██╗    ██╗
██╔══██╗██║   ██║╚══██╔══╝██╔═══██╗██╔════╝██║     ██╔═══██╗██║    ██║
███████║██║   ██║   ██║   ██║   ██║█████╗  ██║     ██║   ██║██║ █╗ ██║
██╔══██║██║   ██║   ██║   ██║   ██║██╔══╝  ██║     ██║   ██║██║███╗██║
██║  ██║╚██████╔╝   ██║   ╚██████╔╝██║     ███████╗╚██████╔╝╚███╔███╔╝
╚═╝  ╚═╝ ╚═════╝    ╚═╝    ╚═════╝ ╚═╝     ╚══════╝ ╚═════╝  ╚══╝╚══╝ 
                                                       version: 1.2.0
```

```mermaid
flowchart LR
  workflowJson["workflow.json"] --> autoflow["autoflow"]
   --> apiFlow[workflow-api.json]
```
---
# Imagine...
### What if you could `load, edit, and submit` ComfyUI workflows without ever exporting an API workflow from the GUI?

### What if you could `batch-convert and patch workflows offline`  No running ComfyUI instance required?

### What if you could attach studio `metadata` to your workflow and have it carry through the entire production lifecycle?

### What if you could `render` comfyui node workflows with all of the above features, `without ever launching the comfyui server`?

- # Let me introduce `comfyui-autoflow`

---
# autoflow

Skip the GUI. `autoflow` handles the backend so you can automate/pipeline your ComfyUI renderables with full control through the entire conversion and submission process.
`autoflow` is a small and efficient, pure **Python package** (stdlib-only +extendable) for ComfyUI automation that gives you access to renderable conversion with or without ComfyUI.

## Features


| Feature | Description |
|---------|-------------|
| **Submit Workflow.json** | Directly edit and submit `workflow.json` files without the need for GUI Api exports   |
| **Convert** | `workflow.json` → `ApiFlow` (renderable API payload) |
| **Offline/Online** | Convert without ComfyUI server running or fetch live from ComfyUI |
| **Subgraphs** | Flattens `definitions.subgraphs` (including nested subgraphs) into a normal API payload |
| **Edit** | Modify nodes, inputs, seeds before submission |
| **Find + address** | `flow.nodes.find(...)` / `api.find(...)` plus `.path()` / `.address()` for stable node addresses |
| **Submit** | Send to ComfyUI, wait for completion, fetch output images |
| **Progress** | Hook into ComfyUI render events for real-time progress control |
| **Serverless ComfyUI Execution** | `.execute` to process ComfyUI native nodes without running the ComfyUI HTTP server |
| **Map** | Patch values across nodes for pipelines (seeds, paths, prompts) |
| **Extract** | Load workflows from ComfyUI PNG outputs (embedded metadata) |
| **Stdlib-only** | No dependencies by default; optional Pillow, ImageMagick, ffmpeg |

## Requirements

- Python 3.9+ (dict insertion order preserved)
- ComfyUI server (optional, for API mode)
- No additional Python packages required

## Tested ComfyUI Versions:
- ComfyUI `0.8.2`
- ComfyUI_frontend `v1.35.9`

---
## The Two `ComfyUI Formats` you should know about

ComfyUI uses two JSON formats:

| Format | File | Description |
|--------|------|-------------|
| **Workspace** | `workflow.json` | The UI-editable graph with node positions, colors, widgets. What you save from ComfyUI. |
| **API Payload** | `workflow-api.json` | The renderable blueprint—just nodes + inputs, ready for `POST /prompt`. This is what `ApiFlow` represents. |

**autoflow converts Workspace → API Payload** (or loads an existing API Payload directly).

```mermaid
flowchart LR
  workspace["workflow.json (workspace)"] --> convert["autoflow"]
  convert --> payload["workflow-api.json (API payload / ApiFlow)"]
  payload --> submit["POST /prompt"]
  submit --> comfy["ComfyUI renders"]
```

## Installation

```bash
pip install comfyui-autoflow
```

Then use with `python -m autoflow ...` or `import autoflow` from Python.
- Optional: set `AUTOFLOW_COMFYUI_SERVER_URL` once (then `server_url` / `--server-url` become optional):
  - Linux/macOS: `export AUTOFLOW_COMFYUI_SERVER_URL="http://localhost:8188"`
  - Windows PowerShell: `$env:AUTOFLOW_COMFYUI_SERVER_URL = "http://localhost:8188"`
  - Windows CMD: `set AUTOFLOW_COMFYUI_SERVER_URL=http://localhost:8188`
  - Python: `import os; os.environ["AUTOFLOW_COMFYUI_SERVER_URL"] = "http://localhost:8188"`
- Optional: set `AUTOFLOW_OBJECT_INFO_SOURCE=modules|fetch|server|/path/to/object_info.json` to auto-resolve `object_info`.
---
# `autoflow` - Quick Start

### Get `object_info.json` (optional, one-time)

Save `object_info.json` so you can convert offline. You can also convert against a running ComfyUI instance, but for efficiency we recommend pulling a new object_info.json file per instance (reproducible, no server needed).

```mermaid
flowchart LR
  comfy["ComfyUI server"] --> obj["/object_info"]
  obj --> file["object_info.json"]
```

```python
# api
from autoflow import ObjectInfo

ObjectInfo.fetch(server_url="http://localhost:8188", output_path="object_info.json")
```

```bash
# cli
python -m autoflow --download-object-info-path object_info.json --server-url http://localhost:8188
```

- Direct modules (no server): `ObjectInfo.from_comfyui_modules()` builds `object_info` from local ComfyUI nodes.
- Env source (optional): set `AUTOFLOW_OBJECT_INFO_SOURCE=modules|fetch|server|/path/to/object_info.json`.

- More: [`docs/object-info-and-env.md`](docs/object-info-and-env.md)
## Convert live (using running ComfyUI)

Convert `workflow.json` by fetching `/object_info` from your running ComfyUI server.

```mermaid
flowchart LR
  env["AUTOFLOW_COMFYUI_SERVER_URL"] --> wf["Workflow(...)"]
  wf --> apiFlow["ApiFlow"]
  comfy["ComfyUI server"] --> obj["/object_info"]
  obj --> wf
```
If environment variable `AUTOFLOW_COMFYUI_SERVER_URL` is set, `server_url` becomes optional.

If `AUTOFLOW_OBJECT_INFO_SOURCE` is set, `Workflow(...)` will auto-resolve `object_info` when none is provided.

```python
# api
from autoflow import Workflow

api = Workflow("workflow.json")  # uses AUTOFLOW_COMFYUI_SERVER_URL
api.save("workflow-api.json")
```

```bash
# cli
python -m autoflow --input-path workflow.json --output-path workflow-api.json
```

- More: [`docs/convert.md`](docs/convert.md), [`docs/object-info-and-env.md`](docs/object-info-and-env.md)


## Convert `workflow` to `workflow-api` (offline)

Convert using your saved `object_info.json` (no server needed).

```mermaid
flowchart LR
  workflowJson["workflow.json"] --> wf["Workflow(...)"]
  objectInfo["object_info.json"] --> wf
  wf --> apiFlow["ApiFlow"]
  apiFlow --> saveApi["save(workflow-api.json)"]
```

```python
# api
from autoflow import Workflow

api = Workflow("workflow.json", object_info="object_info.json")
api.save("workflow-api.json")
```

```bash
# cli
# Offline mode (saved object_info)
python -m autoflow --input-path workflow.json --output-path workflow-api.json --object-info-path object_info.json

# Short form (flags)
python -m autoflow -i workflow.json -o workflow-api.json -f object_info.json
```

- More: [`docs/convert.md`](docs/convert.md)

## Load from PNG (extract embedded workflow)

ComfyUI embeds workflow metadata in PNG outputs. Extract it directly—no external dependencies needed.

```python
# api
from autoflow import Flow, ApiFlow

# From PNG file
api_flow = ApiFlow.load("ComfyUI_00001_.png")  # extracts API payload
flow = Flow.load("ComfyUI_00001_.png")          # extracts workspace

# From bytes (e.g., HTTP upload, database blob)
with open("output.png", "rb") as f:
    api_flow = ApiFlow.load(f.read())
```

All `.load()` methods accept: `dict`, `bytes`, `str` (JSON or path), `Path`

## Submit + images (optional)
 Submit your `ApiFlow` directly to ComfyUI and get images back
```mermaid
flowchart LR
  apiFlow["ApiFlow"] ==> submit["submit(wait=True)"]
  submit ==> comfy["ComfyUI server"]
  comfy --> |job handle|apiFlow
  apiFlow ---> |job handle| images["fetch_images().save(...)"]
```

```python
# api
from autoflow import Workflow

api = Workflow("workflow.json", object_info="object_info.json")
api.saveimage.inputs.filename_prefix='autoflow'
res = api.submit(server_url="http://localhost:8188", wait=True)
images = res.fetch_images()
images.save("outputs/frame.###.png")
```

You can also set an output default with env `AUTOFLOW_OUTPUT_PATH` and then just provide a `filename=` template:

```python
# api
images.save(filename="frame.{src_frame}.png")  # or "frame.###.png" for zero-indexed numbering
```

```bash
# cli
# Prints prompt_id first, then (if saving) the written file paths. Progress logs go to stderr.
python -m autoflow --submit --input-path workflow.json --server-url http://localhost:8188 \
  --save-images outputs --filepattern "frame.###.png" --index-offset 1001
```

- More: [`docs/submit-and-images.md`](docs/submit-and-images.md), [`docs/progress-events.md`](docs/progress-events.md)

## Submit with progress

Stream real-time progress from ComfyUI's WebSocket during rendering.

```mermaid
flowchart LR
  apiFlow["ApiFlow"] --> submit["submit(wait=True, on_event=ProgressPrinter())"]
  submit --> ws["/ws (WebSocket)"]
  ws --> printer["ProgressPrinter"]
```

```python
# api
from autoflow import Workflow, ProgressPrinter

api = Workflow("workflow.json", object_info="object_info.json")
res = api.submit(
    server_url="http://localhost:8188",
    wait=True,
    on_event=ProgressPrinter(),
)
images = res.fetch_images()
images.save("outputs/")
```

Use `chain_callbacks` to combine the built-in printer with your own handler:

```python
# api
from autoflow import Workflow, ProgressPrinter, chain_callbacks

def my_handler(event):
    if event.get("type") == "progress":
        pct = event["data"]["value"] / event["data"]["max"] * 100
        print(f"  {pct:.0f}%")

api = Workflow("workflow.json", object_info="object_info.json")
api.submit(
    server_url="http://localhost:8188",
    wait=True,
    on_event=chain_callbacks(ProgressPrinter(), my_handler),
)
```

- More: [`docs/progress-events.md`](docs/progress-events.md)

## Edit nodes before submission

Access nodes by `class_type`, modify inputs, then submit. Changes happen in-place on the `ApiFlow`.

```python
# api
from autoflow import Workflow

api = Workflow("workflow.json", object_info="object_info.json")

# --- Attribute-style access (by class_type) ---
api.ksampler[0].seed = 12345
api.ksampler[0].cfg = 7.5

# Change the output filename in SaveImage
api.saveimage[0].filename_prefix = "my_render"

# --- find() for more control ---
for ks in api.find(class_type="KSampler"):
    ks.seed = 99999
    ks.steps = 30

# --- Path-style access ---
api["ksampler/seed"] = 42             # first KSampler's seed
api["saveimage/filename_prefix"] = "batch_001"

# Submit the modified workflow
res = api.submit(server_url="http://localhost:8188", wait=True)
images = res.fetch_images()
images.save("outputs/")
```

- More: [`docs/mapping.md`](docs/mapping.md), [`docs/map-strings-and-paths.md`](docs/map-strings-and-paths.md)

## Serverless execute (no ComfyUI HTTP server)

If you're running inside a ComfyUI environment (repo + venv), you can run workflows serverlessly:

- Details: [`docs/execute.md`](docs/execute.md)

## Optional Functionality

- **Polymorphic loading** (dict, bytes, JSON string, file path, PNG):
  - all `.load()` methods auto-detect input type: [`docs/load-vs-convert.md`](docs/load-vs-convert.md)
  - extract workflows from ComfyUI PNG outputs (no dependencies)
- **OOP node access**:
  - `api.ksampler[0].seed = 42` — attribute-style access by class_type
  - `api.find(class_type="KSampler")[0].seed = 42` — search + then edit (returns NodeProxy objects)
  - `api.ksampler[0]._meta` / `.meta` — access node metadata
  - `api["ksampler/seed"]` — path-style access
  - `api["18:17:3/seed"] = 42` — edit nodes inside flattened subgraph exports (ComfyUI-style path IDs)
  - `flow.nodes.ksampler[0].type` — explicit via `.nodes` for workspace flows
  - `flow.nodes.find(title="NewSubgraphName")[0].path()` — find renamed subgraph instances; prints a stable path like `18:17:3`
  - `flow.extra.ds.scale` — drill into nested dicts with `DictView`
  - `node.properties.models.url` — single-item list-of-dicts drill via `ListView` (otherwise index first)
- **Mapping** (seeds/paths/prompts):
  - typed callback mapping: [`docs/mapping.md`](docs/mapping.md)
  - declarative string/path mapping: [`docs/map-strings-and-paths.md`](docs/map-strings-and-paths.md)
  - cache-busting repeat runs: [`docs/force-recompute.md`](docs/force-recompute.md)
- **Filename pattern saving**:
  - `ImagesResult.save("outputs/frame.###.png")`: [`docs/submit-and-images.md`](docs/submit-and-images.md)
- **Service patterns**:
  - FastAPI integration: [`docs/fastapi.md`](docs/fastapi.md)
  - structured errors: [`docs/error-handling.md`](docs/error-handling.md)
- **When things break**:
  - troubleshooting: [`docs/troubleshooting.md`](docs/troubleshooting.md)
  - deeper options: [`docs/advanced.md`](docs/advanced.md)

## CLI Reference

| Argument | Short | Description |
|----------|-------|-------------|
| `--input-path` | `-i` | Input workflow JSON file path |
| `--output-path` | `-o` | Output API format JSON file path |
| `--server-url` | | ComfyUI server URL (or set `AUTOFLOW_COMFYUI_SERVER_URL`) |
| `--object-info-path` | `-f` | Path to saved `object_info.json` file |
| `--download-object-info-path` | | Download `/object_info` and save to file |
| `--submit` | | Submit converted API payload to ComfyUI |
| `--no-wait` | | Submit without waiting for completion (prints `prompt_id` and exits) |
| `--no-progress` | | Disable progress output during `--submit` when waiting |
| `--save-images` | | Directory to save fetched images (requires waiting) |
| `--filepattern` | | Filename pattern used when saving images (default: `frame.###.png`) |
| `--index-offset` | | Index offset for `#` patterns (default: 0) |
| `--save-files` | | Directory to save fetched registered files (requires waiting) |
| `--output-types` | | Comma-separated registered output types when saving files (e.g. `images,files`) |

**Note**: The CLI supports submission and saving registered outputs via `--submit` (see [`docs/submit-and-images.md`](docs/submit-and-images.md) and [`docs/progress-events.md`](docs/progress-events.md)).

## Contributing

This script is designed to be production-ready and maintainable. Key design principles:

- **Minimal Dependencies**: Uses only Python standard library
- **Cross-Platform Compatibility**: Works on Linux, Windows, and macOS
- **Robust Error Handling**: Graceful degradation and detailed error reporting
- **Exact Replication**: Matches ComfyUI's internal conversion exactly

### Running tests (offline)

#### Unit tests

```bash
# Run the full unittest suite (offline)
python -m unittest discover -s examples/unittests -v
```

What to expect:
- **Output**: test names + `... ok`, then a final `OK`
- **Exit code**: `0` on success, non-zero on failure

#### Docs examples test harness (`docs-test.py`)

This runs the fenced code examples from `docs/*.md` in a sandbox.

```bash
# Offline run: compiles python blocks, optionally executes safe ones, and runs safe CLI blocks
python examples/code/docs-test.py --mode offline --exec-python --run-cli

# List available labeled examples
python examples/code/docs-test.py --list

# Run only a subset (labels come from --list)
python examples/code/docs-test.py --mode offline --only "docs/convert.md#1:python" --exec-python
```

What to expect:
- **Output**: `START ...` / `END ... (ok)` banners per doc block
- **Skips**: network-looking snippets print `SKIP` unless you run in online mode
- **Exit code**: `0` if all selected examples pass; `1` if any fail

Diagram: see [`docs/contributing-tests.md`](docs/contributing-tests.md)

## License

[`MIT License`](LICENSE)

## Related

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) - The main ComfyUI project
- [ComfyUI API Documentation](https://github.com/comfyanonymous/ComfyUI/wiki/API) - API format specification

