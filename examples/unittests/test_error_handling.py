#!/usr/bin/env python3
"""
Script demonstrating error handling capabilities.

Note: this is not a unittest.TestCase suite; it's an import-safe script kept under examples/unittests
to document behavior. It makes no network calls unless you pass a real server_url.
"""

import json
import os

from autoflow import convert_with_errors


def test_validation_errors():
    """Test validation error handling."""
    print("=== Testing Validation Errors ===")

    # Test invalid workflow data
    invalid_workflows = [
        # Missing nodes field
        {"links": []},
        # Missing links field
        {"nodes": []},
        # Invalid nodes type
        {"nodes": "invalid", "links": []},
        # Invalid links type
        {"nodes": [], "links": "invalid"},
    ]

    for i, workflow in enumerate(invalid_workflows):
        print(f"\nTest {i+1}: {list(workflow.keys())}")
        # Use structured conversion directly (does not require Flow.load strict workspace shape).
        result = convert_with_errors(workflow, object_info={})
        print(f"Success: {result.success}")
        for error in result.errors:
            print(f"  Error: {error.category.value}/{error.severity.value} - {error.message}")


def test_node_processing_errors():
    """Test node processing error handling."""
    print("\n=== Testing Node Processing Errors ===")

    # Create a workflow with problematic nodes
    workflow = {
        "nodes": [
            {
                "id": 1,
                "type": "NonExistentNode",
                "widgets_values": [1, 2, 3],
                "inputs": [],
            },
            {
                "id": 2,
                "type": "KSampler",
                "widgets_values": [1, 20, 8, 1, 0, 0],  # Wrong number of values
                "inputs": [
                    {"name": "model", "link": 999}  # Non-existent link
                ],
            },
        ],
        "links": [],
    }

    # Test with empty object_info (should cause warnings)
    object_info = {}

    result = convert_with_errors(workflow, object_info=object_info)
    print(f"Success: {result.success}")
    print(f"Processed: {result.processed_nodes}/{result.total_nodes} nodes")
    print(f"Skipped: {result.skipped_nodes} nodes")

    print("\nErrors:")
    for error in result.errors:
        print(f"  {error.category.value}/{error.severity.value} - {error.message}")
        if error.node_id:
            print(f"    Node: {error.node_id}")
        if error.details:
            print(f"    Details: {error.details}")

    print("\nWarnings:")
    for warning in result.warnings:
        print(f"  {warning.category.value}/{warning.severity.value} - {warning.message}")
        if warning.node_id:
            print(f"    Node: {warning.node_id}")


def test_partial_success():
    """Test partial success scenarios."""
    print("\n=== Testing Partial Success ===")

    # Create a workflow with mix of valid and invalid nodes
    workflow = {
        "nodes": [
            {
                "id": 1,
                "type": "ValidNode",
                "widgets_values": [],
                "inputs": [],
            },
            {
                "id": 2,
                "type": "InvalidNode",
                "widgets_values": [],
                "inputs": [{"name": "input", "link": 999}],  # Bad link
            },
        ],
        "links": [],
    }

    # Provide minimal object_info
    object_info = {
        "ValidNode": {
            "input": {
                "required": {},
                "optional": {},
            }
        }
    }

    result = convert_with_errors(workflow, object_info=object_info)
    print(f"Success: {result.success}")
    print(f"Processed: {result.processed_nodes}/{result.total_nodes} nodes")
    print(f"Has data: {result.data is not None}")

    if result.data:
        print(f"API data contains {len(result.data)} nodes")
        for node_id, node_data in result.data.items():
            print(f"  Node {node_id}: {node_data['class_type']}")


def test_network_errors():
    """Test network error handling."""
    print("\n=== Testing Network Errors ===")

    if os.environ.get("AUTOFLOW_DOCS_ALLOW_NETWORK") not in ("1", "true", "yes", "on"):
        print("SKIP: network tests disabled (set AUTOFLOW_DOCS_ALLOW_NETWORK=1 to enable).")
        return

    workflow = {"nodes": [], "links": []}
    result = convert_with_errors(workflow, server_url="http://invalid-server:9999")
    print(f"Success: {result.success}")
    for error in result.errors:
        print(f"  Error: {error.category.value}/{error.severity.value} - {error.message}")
        if error.details:
            print(f"    Details: {error.details}")


def test_successful_conversion():
    """Test successful conversion with the example files."""
    print("\n=== Testing Successful Conversion ===")

    try:
        from pathlib import Path

        examples_dir = Path(__file__).parent / "examples"

        if (examples_dir / "small.json").exists():
            result = Flow.load(str(examples_dir / "small.json")).convert_with_errors(
                object_info=str(examples_dir / "small_object-info.json")
            )

            print(f"Success: {result.success}")
            print(f"Processed: {result.processed_nodes}/{result.total_nodes} nodes")
            print(f"Errors: {len(result.errors)}")
            print(f"Warnings: {len(result.warnings)}")

            if result.data:
                print(f"Generated API data for {len(result.data)} nodes")
        else:
            print("Example files not found, skipping successful conversion test")

    except Exception as e:
        print(f"Could not test with example files: {e}")


if __name__ == "__main__":
    print("ComfyUI Workflow Converter - Error Handling Test")
    print("=" * 50)

    test_validation_errors()
    test_node_processing_errors()
    test_partial_success()
    test_network_errors()
    test_successful_conversion()

    print("\n" + "=" * 50)
    print("Test completed!")


