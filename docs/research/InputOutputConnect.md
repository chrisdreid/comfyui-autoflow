# Research: Viewing & Changing Inputs/Outputs via Dot Notation

## Current State

### ApiFlow (API payload)

Each node's `inputs` dict contains both **widget values** and **connection refs**:

```python
api = Workflow("workflow.json", node_info="node_info.json")

# Widget value — plain scalar
api.ksampler[0].seed          # → 696969
api.ksampler[0].cfg           # → 6.9

# Connection ref — opaque [node_id, slot_index] tuple
api.ksampler[0].model         # → ["4", 0]
api.ksampler[0].positive      # → ["6", 0]
api.ksampler[0].latent_image  # → ["5", 0]
```

Setting a widget value works:
```python
api.ksampler[0].seed = 42     # ✅ writes to inputs["seed"]
```

Setting a connection ref also "works" syntactically, but there's no ergonomic API:
```python
api.ksampler[0].model = ["7", 0]  # ✅ writes raw ref, but user must know format
```

### Flow (workspace)

Connections live in the **link table** (`flow["links"]`), not on the node:
```
[link_id, src_node_id, src_slot, dst_node_id, dst_slot, type_name]
[1,       4,           0,        3,            0,        "MODEL"]
```

Nodes reference links by ID in their `inputs[].link` and `outputs[].links[]` fields.

Widget values are in `widgets_values` (positional array). `FlowNodeProxy.__getattr__` maps
widget names to indices via `node_info`, so dot notation works for widgets:
```python
flow = Flow("workflow.json", node_info="node_info.json")
flow.nodes.ksampler[0].seed   # ✅ resolves via node_info widget map
```

But connections are only accessible via raw data:
```python
flow.nodes.ksampler[0].inputs  # → ListView of input slot dicts
flow.nodes.ksampler[0].inputs[0]  # → {"name": "model", "type": "MODEL", "link": 1}
```

### Summary of Gaps

| Capability | ApiFlow | Flow |
|---|---|---|
| **Read widget value** by name | ✅ `api.ks[0].seed` | ✅ `flow.nodes.ks[0].seed` |
| **Write widget value** by name | ✅ `api.ks[0].seed = 42` | ✅ `flow.nodes.ks[0].seed = 42` |
| **Read connection** by input name | ⚠️ Returns raw `["4", 0]` | ❌ Must dig into `inputs[i].link` → link table |
| **Read what a connection points to** | ❌ Must manually dereference | ❌ Must manually cross-reference link table |
| **Rewire a connection** | ⚠️ Must write raw `["id", slot]` | ❌ Must edit link table + node slots |
| **List all connections** on a node | ❌ No method | ❌ No method |
| **View outputs** (what downstream consumes this) | ❌ Not in data model | ⚠️ Raw `outputs[].links[]` → link table |

## Proposed Dot Notation Extensions

### 1. `node.connections` — View all connections

```python
# ApiFlow
node = api.ksampler[0]
node.connections
# → {
#     "model":        Connection(input="model", from_node="4", from_output=0, class_type="CheckpointLoaderSimple"),
#     "positive":     Connection(input="positive", from_node="6", from_output=0, class_type="CLIPTextEncode"),
#     "negative":     Connection(input="negative", from_node="7", from_output=0, class_type="CLIPTextEncode"),
#     "latent_image": Connection(input="latent_image", from_node="5", from_output=0, class_type="EmptyLatentImage"),
#   }

# Flow
node = flow.nodes.ksampler[0]
node.connections
# → same structure, resolved through the link table
```

**Implementation:** For ApiFlow, scan `inputs` for `[node_id, slot]` patterns (logic already in `_iter_upstream_node_ids`). For Flow, cross-reference `inputs[].link` with the link table.

### 2. `node.outputs` — View downstream consumers

```python
# ApiFlow
node = api.checkpointloadersimple[0]
node.outputs
# → {
#     0: [Connection(to_node="3", to_input="model", class_type="KSampler")],
#     1: [Connection(to_node="6", to_input="clip", class_type="CLIPTextEncode"),
#         Connection(to_node="7", to_input="clip", class_type="CLIPTextEncode")],
#     2: [Connection(to_node="8", to_input="vae", class_type="VAEDecode")],
#   }
```

**Implementation:** For ApiFlow, reverse-scan all nodes' inputs for refs pointing to this node. For Flow, use `outputs[].links[]` → link table.

### 3. `node.connect(input_name, other_node, output_slot=0)` — Rewire

```python
# ApiFlow — connect KSampler's model input to a different checkpoint loader
api.ksampler[0].connect("model", api.checkpointloadersimple[1])

# Equivalent to:
api.ksampler[0].model = [api.checkpointloadersimple[1].id, 0]
```

For Flow, `connect()` would need to:
1. Remove the old link entry from `links[]`
2. Remove the link ID from the old source node's `outputs[slot].links[]`
3. Create a new link entry with a new `link_id`
4. Update the destination node's `inputs[slot].link`
5. Add the link ID to the new source node's `outputs[slot].links[]`
6. Update `last_link_id`

### 4. `node.disconnect(input_name)` — Remove a connection

```python
# ApiFlow — disconnect KSampler's latent_image input
api.ksampler[0].disconnect("latent_image")
# Sets the input to None / removes the ref

# Flow — removes the link entry and cleans up both nodes' slot refs
flow.nodes.ksampler[0].disconnect("latent_image")
```

## Implementation Complexity

| Feature | ApiFlow | Flow | Notes |
|---|---|---|---|
| `node.connections` (read) | Easy | Medium | ApiFlow: pattern-match inputs. Flow: link table lookup |
| `node.outputs` (read) | Medium | Easy | ApiFlow: reverse-scan all nodes. Flow: direct from `outputs[].links[]` |
| `node.connect()` | Easy | Hard | ApiFlow: write `[id, slot]`. Flow: full link table surgery |
| `node.disconnect()` | Easy | Medium-Hard | ApiFlow: set to None. Flow: link table cleanup |

### Key Building Blocks Already In Place

- **`_iter_upstream_node_ids()`** in `dag.py` — detects `[node_id, slot]` patterns in inputs
- **`build_api_dag()`** — scans all nodes for connection edges
- **`build_flow_dag()`** — parses the Flow link table
- **`NodeProxy._get_data()`** — gives access to the raw node dict
- **`FlowNodeProxy` + link table** — `flow["links"]` is directly accessible

### Suggested `Connection` Dataclass

```python
@dataclasses.dataclass
class Connection:
    input_name: str            # e.g. "model"
    from_node_id: str          # source node ID
    from_slot: int             # source output slot index
    from_class_type: str       # source node's class_type (for display)
    # For outputs:
    to_node_id: Optional[str] = None
    to_input_name: Optional[str] = None
    to_class_type: Optional[str] = None
```

## Recommended Approach

1. **Start with read-only** — `node.connections` and `node.outputs` are the most valuable and lowest risk
2. **ApiFlow first** — simpler data model, no link table surgery
3. **`connect()`/`disconnect()` later** — more complex, especially for Flow
4. Consider whether `connect()` on Flow is worth the complexity vs. just editing in ApiFlow and using `apply_api_edits()` to sync back
