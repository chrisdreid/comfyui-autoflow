"""Reusable conversation templates exposed as MCP prompts."""

from __future__ import annotations

from typing import Optional


TEXT_TO_IMAGE_TEMPLATE = """\
Generate an image with ComfyUI using the autograph MCP tools.

Goal:
  Prompt:    {prompt}
  Negative:  {negative}
  Model:     {model}
  Steps:     {steps}
  Seed:      {seed}

Workflow plan:
  1. Call `comfyui_status` to confirm the server is reachable and learn its URL.
  2. If the user supplied a workflow path or you have one cached, call `inspect_workflow`
     on it. Otherwise call `list_node_types(query="checkpoint")` and `list_models("checkpoints")`
     to plan the workflow and confirm the model is available.
  3. Use `set_workflow_values` to update CLIPTextEncode (positive/negative), the chosen
     KSampler (`seed`, `steps`), and CheckpointLoaderSimple (`ckpt_name`) values.
  4. Call `validate_workflow` and stop with a clear summary if there are errors.
  5. Call `run_workflow` with `wait=True, fetch_outputs=True, inline_images=True`.
  6. Show the user the returned image(s) and the saved file paths.
"""


DIAGNOSE_WORKFLOW_TEMPLATE = """\
Diagnose a ComfyUI workflow by walking through autograph's structured errors.

Workflow plan:
  1. Call `validate_workflow` on the user's workflow. Group results by severity.
  2. For each error/warning, name the offending node (id + class_type) and explain the
     fix in one or two sentences.
  3. If a fix can be applied automatically (a missing widget value, a typo'd model name,
     a wrong connection), propose `set_workflow_values` patches the user can run.
  4. Re-run `validate_workflow` after applying any proposed fixes and confirm clean.
"""


def text_to_image(
    prompt: str,
    negative: Optional[str] = "",
    model: Optional[str] = "auto",
    steps: Optional[int] = 20,
    seed: Optional[int] = 0,
) -> str:
    return TEXT_TO_IMAGE_TEMPLATE.format(
        prompt=prompt,
        negative=negative or "(none)",
        model=model or "auto",
        steps=steps if steps is not None else 20,
        seed=seed if seed is not None else 0,
    )


def diagnose_workflow() -> str:
    return DIAGNOSE_WORKFLOW_TEMPLATE


VIBE_BUILD_TEMPLATE = """\
Vibe-build a ComfyUI workflow end-to-end without using the GUI.

Goal:
  {goal}

Workflow plan:
  1. Confirm the server is reachable: `comfyui_status`. Note the URL.
  2. Decide where to start:
     a. If the user has a workflow file, call `load_workflow(source=...)` and remember the returned `workflow_id`.
     b. Otherwise call `search_local_workflows(query=...)` and `load_local_workflow(name)` to start from a known-good
        starter, OR `create_workflow()` to build from scratch.
  3. Read the current graph: `inspect_workflow(workflow_id=...)`. Note class_types, free vs wired inputs, and titles.
  4. Resolve any unknown nodes: `describe_node_type(class_type)` to learn input/output/widget shapes.
  5. Edit:
     a. For widget tweaks (seed, prompt text, model name): `set_workflow_values(workflow_id, updates=[...])`.
     b. To add capability: prefer `merge_workflow(workflow_id, fragment=...)` if you can find a workflow snippet
        (online via WebFetch on a `list_workflow_sources` URL, or in `search_local_workflows`). Otherwise build
        node-by-node with `add_node` + `connect_nodes`.
     c. To remove or rewire: `remove_node` / `disconnect_input` / `connect_nodes`.
  6. After every structural change, call `validate_workflow(workflow_id)`. Stop and explain if there are errors.
  7. Render: `run_workflow(workflow_id, wait=True, fetch_outputs=True)`. If the result has `ok: false`, the `errors`
     array names the offending node — fix and retry.
  8. Show the user the inline image(s) and saved file paths. If they like it, suggest `save_workflow(workflow_id, path)`
     so the design lands on disk.
"""


def vibe_build_workflow(goal: str = "describe what the user wants to render") -> str:
    return VIBE_BUILD_TEMPLATE.format(goal=goal)
