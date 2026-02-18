# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-02-18

### Added
- `Workflow(...)` — unified entry point: load workspace *or* API payload, auto-convert, optionally submit
- `ObjectInfo.fetch(...)` / `ObjectInfo.from_comfyui_modules()` — first-class object_info helpers
- `AUTOFLOW_OBJECT_INFO_SOURCE` env var for automatic object_info resolution
- `.execute()` serverless rendering (in-process ComfyUI, no HTTP server)
- `Dag` / `.dag()` graph helpers with `.to_mermaid()` and `.to_dot()` output
- `ProgressPrinter` with custom format strings and event-type filtering
- `SubmissionResult.save()` one-call output saving (images + files)
- `force_recompute()` cache-busting helper
- `map_strings()` / `map_paths()` declarative mapping helpers
- `chain_callbacks()` for composing progress callbacks
- Subgraph flattening for nested `definitions.subgraphs`
- PNG metadata extraction (stdlib-only, no Pillow required)
- CLI: `--save-files`, `--output-types`, `--filepattern`, `--index-offset` flags

### Changed
- Default model layer is now `flowtree` (navigation-first wrappers)
- `ErrorSeverity` / `ErrorCategory` use `str` mixin for JSON compatibility
- `api.py` public API cleaned: private `_`-prefixed names replaced with public equivalents

## [1.1.0] - 2026-01-15

### Added
- Flow/ApiFlow polymorphic `.load()` — accepts dict, bytes, JSON string, file path, or PNG
- Attribute-style node access (`api.ksampler[0].seed = 42`)
- `.find()` helpers for node search with regex support
- `DictView` / `ListView` drilling proxies
- `api_mapping()` callback-first mapping

## [1.0.0] - 2026-01-01

### Added
- Initial release
- Workspace → API payload conversion
- Offline conversion with saved `object_info.json`
- Online conversion via ComfyUI server `/object_info`
- Submit API payloads and fetch output images
- CLI entrypoint (`python -m autoflow`)
