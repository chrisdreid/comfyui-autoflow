# Feasibility: ApiFlow → Flow Reverse Conversion

## The Two Formats

| | Flow (workspace) | ApiFlow (API payload) |
|---|---|---|
| **Node identity** | `node.id` (int), `node.type` | `node_id` (str), `class_type` |
| **Inputs** | `widgets_values` (positional array) + `inputs[]` with links | `inputs: {name: value_or_ref}` (named dict) |
| **Connections** | Explicit link table: `[link_id, src_node, src_slot, dst_node, dst_slot, type]` | Inline refs: `["node_id", slot_index]` |
| **Outputs** | `outputs[]` with slot types, names, link lists | Not present |
| **Layout** | `pos`, `size`, `order`, `color`, `bgcolor` | Not present |
| **Groups** | Named bounding-box groups | Not present |
| **Metadata** | `extra` (frontend version, zoom, etc.), `properties`, `flags`, `mode` | `_meta` (optional title only) |

## What's Lost (Forward: Flow → ApiFlow)

- **Positions, sizes, colors** — the entire visual layout
- **Output slot metadata** — type names, slot indices, link arrays
- **Link table** — the ordered `links[]` array with link IDs and slot types
- **Widget ordering** — `widgets_values` is positional; ApiFlow names them
- **UI-only nodes** — e.g. `MarkdownNote` nodes are stripped
- **Groups** — named visual groupings
- **Properties** — `cnr_id`, `ver`, `ue_properties`, etc.
- **Extra metadata** — frontend version, zoom/pan state

## Can We Go Back? (ApiFlow → Flow)

### What IS Recoverable

| Data | How |
|---|---|
| Node IDs | Preserved 1:1 (`str` → `int`) |
| `class_type` → `type` | Direct mapping |
| Named inputs → `widgets_values` | Reverse-map via `node_info` (widget name → positional index) |
| Input connections | Inline `["node_id", slot_index]` refs → rebuild link table entries |
| Execution order | Toposort from `dag.py` already exists |
| Rough positions | Toposort + column/row auto-layout (see below) |

### What's LOST Forever (without the original Flow)

| Data | Impact |
|---|---|
| Exact positions/sizes | Must synthesize with auto-layout |
| Colors / bgcolor | Default only |
| Groups | Cannot recreate |
| UI-only nodes | Gone (MarkdownNote, etc.) |
| Properties (`cnr_id`, `ver`, etc.) | Gone |
| Output slot type names | Need `node_info` to reconstruct |
| Widget ordering for non-standard widgets | Risky without `node_info` |
| Extra metadata (zoom, frontend version) | Defaults only |

### Auto-Layout Strategy (toposort-based)

The DAG module already has `_toposort_nodes()` using Kahn's algorithm. A simple layout:

```
1. toposort nodes → ordered list
2. Assign "depth" = longest-path from sources
3. Column = depth × spacing_x
4. Row = index-within-column × spacing_y
5. Size = fixed default (e.g. 300×150)
```

This produces a left-to-right flow that's readable if not pretty. ComfyUI will re-layout on open anyway if the user wants.

## The More Interesting Use Case: Sync ApiFlow Edits Back to Flow

> "Sometimes it feels easier to set values in dot notation in ApiFlow than in Flow"

This is the stronger use case. Instead of full reverse conversion, **sync edited ApiFlow values back into the original Flow**. This keeps all layout/groups/colors intact.

### How It Would Work

```python
flow = Flow("workflow.json", node_info="node_info.json")
api = flow.convert(node_info="node_info.json")

# Edit with ApiFlow's nice dot-notation
api.ksampler[0].seed = 42
api.ksampler[0].cfg = 7.5
api.saveimage[0].filename_prefix = "batch_001"

# Sync changes back into the original Flow
flow.apply_api_edits(api)       # ← new method
flow.save("workflow_modified.json")
```

### Implementation Approach for `apply_api_edits`

```
For each API node (node_id, {class_type, inputs}):
  1. Find matching Flow node by id
  2. For each input name/value in the API node:
     a. If input is a widget (not a connection ref):
        - Use node_info to find the widget's positional index in widgets_values
        - Update flow_node["widgets_values"][index] = new_value
     b. If input is a connection ref ["other_id", slot]:
        - Skip (connections are structural, not typically edited)
```

This is **very feasible** because:
- `node_info` already provides the widget name → index mapping
- `_flow_widget_map()` in `models.py` (line 112) already does exactly this reverse lookup
- Node IDs are preserved 1:1 between Flow and ApiFlow

## Feasibility Summary

| Feature | Difficulty | Value | Recommendation |
|---|---|---|---|
| **Full ApiFlow → Flow** (cold, no original) | Medium-Hard | Low-Medium | Possible but synthesized layout is ugly |
| **Sync ApiFlow edits → Flow** (with original) | Easy-Medium | **High** | Best bang for buck — keeps layout intact |
| **Auto-layout via toposort** | Easy | Medium | Useful for the cold case; DAG infra exists |

> **Tip:** The sync-back approach (`flow.apply_api_edits(api)`) covers 100% of the value-editing use case with minimal effort — no data is lost since the original Flow provides all layout/groups/metadata. Full reverse conversion (cold, no original Flow) is possible but the layout will always look machine-generated.
