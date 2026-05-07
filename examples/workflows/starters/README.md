# Starter workflows

The `comfyui-autograph` MCP server ships these as a starting library. They are
discoverable via `search_local_workflows()` and `load_local_workflow(name)` and
also live on disk so the user can edit / extend them by hand.

## Layout

* `*.json` — the workflow itself (workspace format, the JSON ComfyUI saves).
* `*.metadata.json` — optional sidecar with `name`, `title`, `description`,
  `tags`, `models_required`, `source`.

## Add your own

The library also searches:

1. Anything in `$AUTOGRAPH_MCP_LIBRARY_DIRS` (colon-separated dirs).
2. `./.autograph-workflows/` (project-local).
3. `~/.comfyui-autograph/workflows/` (user-home).

Drop a `.json` file in any of those — with an optional `.metadata.json`
sidecar — and the MCP picks it up the next call to `search_local_workflows`.
