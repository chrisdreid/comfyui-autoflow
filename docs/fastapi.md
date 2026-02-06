# FastAPI integration

This repo includes a full service + client example:
- server: `examples/code/fastapi_example.py`
- client: `examples/code/client_example.py`

```mermaid
flowchart  LR
  client["Client"] --> api["YourFastAPIService"]
  api --> convertFn["Flow.load(...) + .convert(...)"]
  convertFn --> submitFn["ApiFlow.submit(...)"]
  submitFn --> comfy["ComfyUI server"]
```

## Service tips
- **Conversion**: use `Flow.load(...)` + `Flow.convert_with_errors(...)`
- **Errors**: return structured `errors`/`warnings` (see [`error-handling.md`](error-handling.md))
- **Network**: keep server calls explicit and opt-in


