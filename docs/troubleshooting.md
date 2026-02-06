# Troubleshooting

```mermaid
flowchart TD
  start["Start"] --> checkShape["Is input workflow.json or workflow-api.json?"]
  checkShape -->|"workflow.json"| needInfo["Need object_info (file or /object_info)"]
  checkShape -->|"workflow-api.json"| submit["Submit ApiFlow"]
  needInfo --> convert["Convert to ApiFlow"]
  convert --> submit
  submit --> done["Done"]
```

## “Not a ComfyUI workspace workflow.json”
- `Flow` is strict
- required keys:
  - `nodes` (list)
  - `links` (list)
  - `last_node_id`
  - `last_link_id`

## "API payload node missing class_type/inputs"
- `ApiFlow` is strict
- top-level must be: `{"node_id": {"class_type": "...", "inputs": {...}}, ...}`

## “Missing server URL”
- submission requires:
  - `server_url=...` (Python), or
  - `AUTOFLOW_COMFYUI_SERVER_URL` (env var)

