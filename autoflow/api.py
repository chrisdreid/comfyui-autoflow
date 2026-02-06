#!/usr/bin/env python3
"""autoflow.api

Thin compatibility façade.

The implementation was split across:
- autoflow.models   (Flow/ApiFlow/ObjectInfo/Workflow + drilling helpers)
- autoflow.convert  (conversion core + errors)
- autoflow.results  (submit + outputs + save helpers)
- autoflow.net/pngmeta/defaults (stdlib helpers)

This module re-exports the public API for backwards compatibility.
"""

from __future__ import annotations

from .version import __version__

# Public models
from .model_layer import (  # noqa: F401
    ApiFlow,
    Flow,
    Workflow,
    ObjectInfo,
)
from .models import DictView  # noqa: F401
from .convert import (  # noqa: F401
    ConvertResult,
    WorkflowConverterError,
    NodeInfoError,
    ErrorSeverity,
    ErrorCategory,
    ConversionError,
    ConversionResult,
    comfyui_available,
)

# Conversion functions
from .convert import (  # noqa: F401
    convert,
    convert_with_errors,
    convert_workflow,
    convert_workflow_with_errors,
    workflow_to_api_format,
    workflow_to_api_format_with_errors,
    validate_workflow_data,
    flatten_subgraphs,
    resolve_object_info,
    fetch_object_info,
    fetch_object_info_from_url,
    load_workflow_from_file,
    save_workflow_to_file,
    load_object_info_from_file,
    save_object_info_to_file,
    get_widget_input_names,
    align_widgets_values,
)

# Submission + outputs
from .results import (  # noqa: F401
    _sanitize_api_prompt,
    SubmissionResult,
    FilesResult,
    FileResult,
    ImagesResult,
    ImageResult,
)

# Helpers that were historically reachable from autoflow.api
from .defaults import (  # noqa: F401
    DEFAULT_HTTP_TIMEOUT_S,
    DEFAULT_POLL_INTERVAL_S,
    DEFAULT_WAIT_TIMEOUT_S,
    DEFAULT_OUTPUT_PATH,
    DEFAULT_SUBMIT_CLIENT_ID,
)
from .net import _http_json, _comfy_url, _resolve_comfy_server_url  # noqa: F401
from .pngmeta import (  # noqa: F401
    _parse_png_metadata_from_bytes,
    _extract_png_comfyui_metadata,
    _looks_like_json,
    _looks_like_path,
    _is_png_bytes,
    _is_png_path,
)

# CLI entrypoint
from .cli import main  # noqa: F401

__all__ = [
    "__version__",
    # models
    "ApiFlow",
    "Flow",
    "Workflow",
    "ObjectInfo",
    "ConvertResult",
    "SubmissionResult",
    "FilesResult",
    "FileResult",
    "ImagesResult",
    "ImageResult",
    "DictView",
    # conversion + errors
    "WorkflowConverterError",
    "NodeInfoError",
    "ErrorSeverity",
    "ErrorCategory",
    "ConversionError",
    "ConversionResult",
    "comfyui_available",
    "convert",
    "convert_with_errors",
    "convert_workflow",
    "convert_workflow_with_errors",
    "workflow_to_api_format",
    "workflow_to_api_format_with_errors",
    "validate_workflow_data",
    "flatten_subgraphs",
    "resolve_object_info",
    "fetch_object_info",
    "fetch_object_info_from_url",
    "load_workflow_from_file",
    "save_workflow_to_file",
    "load_object_info_from_file",
    "save_object_info_to_file",
    "get_widget_input_names",
    "align_widgets_values",
    # misc historical helpers
    "_http_json",
    "_comfy_url",
    "_resolve_comfy_server_url",
    "_sanitize_api_prompt",
    "_parse_png_metadata_from_bytes",
    "_extract_png_comfyui_metadata",
    "_looks_like_json",
    "_looks_like_path",
    "_is_png_bytes",
    "_is_png_path",
    # cli
    "main",
]


