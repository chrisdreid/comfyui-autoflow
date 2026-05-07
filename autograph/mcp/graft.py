"""Graft / merge engine: insert a workflow fragment into an active workflow.

The user's typical loop:
  1. The LLM finds a workflow JSON online (or in the local library) that does
     something the user wants — say, a ControlNet branch or a LoRA stack.
  2. The MCP merges that fragment into the active workflow:
     * renumbers the fragment's node and link IDs to avoid collisions,
     * inserts it,
     * detects dangling input/output slots,
     * auto-wires the unambiguous ones against the existing graph,
     * returns a structured report so the LLM can wire up the rest.

Workspace-format only. Fragments in API format should be loaded into a Flow
first (autograph auto-converts) and then handed in as a workspace dict.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import autograph


WorkflowDict = Dict[str, Any]
FragmentArg = Union[str, Path, bytes, WorkflowDict, "autograph.Flow"]


def _load_fragment(source: FragmentArg) -> WorkflowDict:
    """Coerce a fragment into a plain workspace-format dict."""
    if isinstance(source, autograph.Flow):
        return json.loads(source.to_json())
    if isinstance(source, dict):
        return copy.deepcopy(source)
    if isinstance(source, (bytes, bytearray)):
        return json.loads(bytes(source).decode("utf-8"))
    if isinstance(source, Path):
        return json.loads(source.read_text(encoding="utf-8"))
    if isinstance(source, str):
        stripped = source.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            return json.loads(source)
        p = Path(source).expanduser()
        if p.exists() and p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
        return json.loads(source)
    raise TypeError(f"Cannot load workflow fragment from {type(source).__name__}")


def _flow_data(flow: "autograph.Flow") -> WorkflowDict:
    """Return the underlying mutable workspace dict."""
    return flow._flow  # autograph.Flow exposes its legacy Flow as ._flow


def _is_workspace(data: WorkflowDict) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("nodes"), list)
        and isinstance(data.get("links"), list)
    )


# ---------------------------------------------------------------------------
# Renumber + insert
# ---------------------------------------------------------------------------


def _renumber(fragment: WorkflowDict, node_offset: int, link_offset: int) -> Tuple[List[Dict[str, Any]], List[List[Any]], Dict[int, int], Dict[int, int]]:
    """Return (new_nodes, new_links, node_id_map, link_id_map)."""
    node_id_map: Dict[int, int] = {}
    link_id_map: Dict[int, int] = {}

    # Map node ids first.
    nodes_in = fragment.get("nodes", []) or []
    for n in nodes_in:
        nid = n.get("id")
        if isinstance(nid, int):
            node_id_map[nid] = nid + node_offset

    # Map link ids.
    links_in = fragment.get("links", []) or []
    for ln in links_in:
        if isinstance(ln, list) and ln and isinstance(ln[0], int):
            link_id_map[ln[0]] = ln[0] + link_offset

    # Renumber nodes.
    new_nodes: List[Dict[str, Any]] = []
    for n in nodes_in:
        if not isinstance(n, dict):
            continue
        nn = copy.deepcopy(n)
        old_id = nn.get("id")
        if isinstance(old_id, int):
            nn["id"] = node_id_map[old_id]
        # Inputs reference link ids.
        for inp in nn.get("inputs", []) or []:
            link = inp.get("link")
            if isinstance(link, int) and link in link_id_map:
                inp["link"] = link_id_map[link]
        # Outputs hold lists of link ids.
        for outp in nn.get("outputs", []) or []:
            outp["links"] = [link_id_map.get(li, li) for li in (outp.get("links") or [])]
        new_nodes.append(nn)

    # Renumber link entries: [link_id, src_node, src_slot, dst_node, dst_slot, type]
    new_links: List[List[Any]] = []
    for ln in links_in:
        if not isinstance(ln, list) or len(ln) < 6:
            continue
        new_link = list(ln)
        new_link[0] = link_id_map.get(new_link[0], new_link[0])
        if isinstance(new_link[1], int):
            new_link[1] = node_id_map.get(new_link[1], new_link[1])
        if isinstance(new_link[3], int):
            new_link[3] = node_id_map.get(new_link[3], new_link[3])
        new_links.append(new_link)

    return new_nodes, new_links, node_id_map, link_id_map


def _next_link_id(flow_data: WorkflowDict) -> int:
    last = int(flow_data.get("last_link_id", 0) or 0)
    last += 1
    flow_data["last_link_id"] = last
    return last


# ---------------------------------------------------------------------------
# Dangling-slot detection
# ---------------------------------------------------------------------------


def _dangling_inputs(nodes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for n in nodes:
        node_id = n.get("id")
        for slot_idx, inp in enumerate(n.get("inputs", []) or []):
            if inp.get("link") is None:
                out.append(
                    {
                        "node_id": str(node_id),
                        "class_type": n.get("type"),
                        "input_name": inp.get("name"),
                        "input_type": inp.get("type", "*"),
                        "slot_index": slot_idx,
                    }
                )
    return out


def _dangling_outputs(nodes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for n in nodes:
        node_id = n.get("id")
        for slot_idx, outp in enumerate(n.get("outputs", []) or []):
            if not (outp.get("links") or []):
                out.append(
                    {
                        "node_id": str(node_id),
                        "class_type": n.get("type"),
                        "output_name": outp.get("name"),
                        "output_type": outp.get("type", "*"),
                        "slot_index": slot_idx,
                    }
                )
    return out


# ---------------------------------------------------------------------------
# Auto-stitch
# ---------------------------------------------------------------------------


def _by_id(nodes: Iterable[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    return {n["id"]: n for n in nodes if isinstance(n, dict) and isinstance(n.get("id"), int)}


def _candidates_with_output(
    flow_data: WorkflowDict,
    *,
    slot_type: str,
    exclude_node_ids: Iterable[int],
) -> List[Tuple[Dict[str, Any], int, Dict[str, Any]]]:
    """Find all (node, output_idx, output_slot) producing a value of slot_type."""
    excluded = set(int(x) for x in exclude_node_ids)
    out: List[Tuple[Dict[str, Any], int, Dict[str, Any]]] = []
    for n in flow_data.get("nodes", []) or []:
        if not isinstance(n, dict):
            continue
        if n.get("id") in excluded:
            continue
        for idx, outp in enumerate(n.get("outputs", []) or []):
            if (outp.get("type") or "") == slot_type and slot_type != "*":
                out.append((n, idx, outp))
    return out


def _candidates_with_free_input(
    flow_data: WorkflowDict,
    *,
    slot_type: str,
    exclude_node_ids: Iterable[int],
) -> List[Tuple[Dict[str, Any], int, Dict[str, Any]]]:
    """Find all (node, input_idx, input_slot) accepting slot_type AND not yet wired."""
    excluded = set(int(x) for x in exclude_node_ids)
    out: List[Tuple[Dict[str, Any], int, Dict[str, Any]]] = []
    for n in flow_data.get("nodes", []) or []:
        if not isinstance(n, dict):
            continue
        if n.get("id") in excluded:
            continue
        for idx, inp in enumerate(n.get("inputs", []) or []):
            if (inp.get("type") or "") != slot_type or slot_type == "*":
                continue
            if inp.get("link") is None:
                out.append((n, idx, inp))
    return out


def _wire(
    flow_data: WorkflowDict,
    *,
    src_node: Dict[str, Any],
    src_slot_idx: int,
    src_slot: Dict[str, Any],
    dst_node: Dict[str, Any],
    dst_slot_idx: int,
    dst_slot: Dict[str, Any],
) -> int:
    """Append a link entry and update slot link refs. Returns new link_id."""
    link_id = _next_link_id(flow_data)
    link_type = dst_slot.get("type") or src_slot.get("type") or "*"
    flow_data.setdefault("links", []).append(
        [link_id, src_node["id"], src_slot_idx, dst_node["id"], dst_slot_idx, link_type]
    )
    dst_slot["link"] = link_id
    src_slot.setdefault("links", []).append(link_id)
    return link_id


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def merge_into_flow(
    flow: "autograph.Flow",
    fragment: FragmentArg,
    *,
    auto_connect: bool = True,
    pos_offset: Tuple[int, int] = (450, 0),
) -> Dict[str, Any]:
    """Insert ``fragment`` into ``flow`` and try to auto-wire it sensibly.

    Returns a report::

        {
          "added_nodes": [{node_id, class_type, title}, ...],
          "node_id_map": {old_id: new_id, ...},
          "auto_connected": [{from, to, slot_type, reason}, ...],
          "still_dangling_inputs":  [{node_id, class_type, input_name, input_type, candidates}, ...],
          "still_dangling_outputs": [{node_id, class_type, output_name, output_type, candidates}, ...],
          "interposer_suggestions": [{node_id, class_type, slot_type, hint}, ...],
        }
    """
    fragment_data = _load_fragment(fragment)
    if not _is_workspace(fragment_data):
        raise ValueError(
            "Fragment must be in workspace format (top-level `nodes` and `links` lists). "
            "Convert API-format payloads to workspace first via `autograph.Flow(api_data)`."
        )

    flow_data = _flow_data(flow)
    last_node_id = int(flow_data.get("last_node_id", 0) or 0)
    last_link_id = int(flow_data.get("last_link_id", 0) or 0)

    new_nodes, new_links, node_id_map, link_id_map = _renumber(
        fragment_data, node_offset=last_node_id, link_offset=last_link_id
    )
    if not new_nodes:
        return {
            "added_nodes": [],
            "node_id_map": {},
            "auto_connected": [],
            "still_dangling_inputs": [],
            "still_dangling_outputs": [],
            "interposer_suggestions": [],
        }

    # Apply position offset so the merged fragment doesn't overlap the existing graph.
    dx, dy = pos_offset
    for n in new_nodes:
        pos = n.get("pos")
        if isinstance(pos, list) and len(pos) == 2:
            try:
                n["pos"] = [pos[0] + dx, pos[1] + dy]
            except Exception:
                pass

    # Splice into the active flow.
    flow_data.setdefault("nodes", []).extend(new_nodes)
    flow_data.setdefault("links", []).extend(new_links)
    flow_data["last_node_id"] = max((int(n["id"]) for n in new_nodes if isinstance(n.get("id"), int)), default=last_node_id)
    if new_links:
        flow_data["last_link_id"] = max(int(ln[0]) for ln in new_links if isinstance(ln[0], int))

    added_node_ids = [int(n["id"]) for n in new_nodes if isinstance(n.get("id"), int)]
    added_summary = [
        {
            "node_id": str(n.get("id")),
            "class_type": n.get("type"),
            "title": n.get("title") or "",
        }
        for n in new_nodes
    ]

    auto_connected: List[Dict[str, Any]] = []
    still_in: List[Dict[str, Any]] = []
    still_out: List[Dict[str, Any]] = []
    interposers: List[Dict[str, Any]] = []

    if auto_connect:
        # Wire dangling fragment INPUTS from existing flow OUTPUTS (1-to-many is fine).
        for d in _dangling_inputs(new_nodes):
            slot_type = d["input_type"]
            cands = _candidates_with_output(
                flow_data, slot_type=slot_type, exclude_node_ids=added_node_ids
            )
            if len(cands) == 1:
                src_node, src_idx, src_slot = cands[0]
                dst_node = next(n for n in new_nodes if str(n.get("id")) == d["node_id"])
                dst_slot = dst_node["inputs"][d["slot_index"]]
                _wire(
                    flow_data,
                    src_node=src_node,
                    src_slot_idx=src_idx,
                    src_slot=src_slot,
                    dst_node=dst_node,
                    dst_slot_idx=d["slot_index"],
                    dst_slot=dst_slot,
                )
                auto_connected.append(
                    {
                        "from": {
                            "node_id": str(src_node["id"]),
                            "class_type": src_node.get("type"),
                            "output_name": src_slot.get("name"),
                        },
                        "to": {
                            "node_id": d["node_id"],
                            "class_type": d["class_type"],
                            "input_name": d["input_name"],
                        },
                        "slot_type": slot_type,
                        "reason": "unique-source-by-type",
                    }
                )
            else:
                still_in.append(
                    {
                        **d,
                        "candidates": [
                            {
                                "node_id": str(c[0]["id"]),
                                "class_type": c[0].get("type"),
                                "output_name": c[2].get("name"),
                            }
                            for c in cands
                        ],
                    }
                )

        # Wire dangling fragment OUTPUTS into existing free INPUTS, but only when
        # there is a unique matching free input (rare; usually the LLM picks).
        for d in _dangling_outputs(new_nodes):
            slot_type = d["output_type"]
            cands = _candidates_with_free_input(
                flow_data, slot_type=slot_type, exclude_node_ids=added_node_ids
            )
            if len(cands) == 1:
                dst_node, dst_idx, dst_slot = cands[0]
                src_node = next(n for n in new_nodes if str(n.get("id")) == d["node_id"])
                src_slot = src_node["outputs"][d["slot_index"]]
                _wire(
                    flow_data,
                    src_node=src_node,
                    src_slot_idx=d["slot_index"],
                    src_slot=src_slot,
                    dst_node=dst_node,
                    dst_slot_idx=dst_idx,
                    dst_slot=dst_slot,
                )
                auto_connected.append(
                    {
                        "from": {
                            "node_id": d["node_id"],
                            "class_type": d["class_type"],
                            "output_name": d["output_name"],
                        },
                        "to": {
                            "node_id": str(dst_node["id"]),
                            "class_type": dst_node.get("type"),
                            "input_name": dst_slot.get("name"),
                        },
                        "slot_type": slot_type,
                        "reason": "unique-free-sink-by-type",
                    }
                )
            else:
                # Detect interposer pattern: same node has BOTH a dangling input
                # and a dangling output of the same type (e.g. LoraLoader takes
                # MODEL in / produces MODEL out). Suggest interposing.
                node_in = next(
                    (di for di in still_in if di["node_id"] == d["node_id"] and di["input_type"] == slot_type),
                    None,
                )
                if node_in is not None:
                    interposers.append(
                        {
                            "node_id": d["node_id"],
                            "class_type": d["class_type"],
                            "slot_type": slot_type,
                            "hint": (
                                f"This node looks like an interposer for {slot_type}: it expects {slot_type} in "
                                f"and produces {slot_type} out. To insert it into an existing path, find the link "
                                f"currently feeding the original {slot_type} consumer, disconnect it with "
                                f"`disconnect_input`, then `connect_nodes` the original source to this node's "
                                f"{slot_type} input and this node's {slot_type} output to the original consumer."
                            ),
                        }
                    )
                still_out.append(
                    {
                        **d,
                        "candidates": [
                            {
                                "node_id": str(c[0]["id"]),
                                "class_type": c[0].get("type"),
                                "input_name": c[2].get("name"),
                            }
                            for c in cands
                        ],
                    }
                )
    else:
        still_in = [{**d, "candidates": []} for d in _dangling_inputs(new_nodes)]
        still_out = [{**d, "candidates": []} for d in _dangling_outputs(new_nodes)]

    return {
        "added_nodes": added_summary,
        "node_id_map": {str(k): str(v) for k, v in node_id_map.items()},
        "auto_connected": auto_connected,
        "still_dangling_inputs": still_in,
        "still_dangling_outputs": still_out,
        "interposer_suggestions": interposers,
    }
