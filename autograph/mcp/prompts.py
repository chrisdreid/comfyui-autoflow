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
