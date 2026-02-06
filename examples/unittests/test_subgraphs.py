#!/usr/bin/env python3
"""Offline tests for workspace subgraph flattening.

Run:
  python3 -m unittest examples.unittests.test_subgraphs -v
"""

import json
import sys
import unittest
from pathlib import Path

# Allow running this file directly without installing the package.
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root))

from autoflow import Flow
from examples.unittests._fixtures import fixture_path


def _mini_object_info():
    # Minimal object_info for the nodes used in default workflows.
    # Use API-mode list specs so conversion stays offline.
    return {
        "CheckpointLoaderSimple": {
            "input": {
                "required": {
                    "ckpt_name": ["STRING", {"default": ""}],
                },
                "optional": {},
            }
        },
        "CLIPTextEncode": {
            "input": {
                "required": {
                    "text": ["STRING", {"default": ""}],
                    "clip": ["CLIP", {}],  # connection-only
                },
                "optional": {},
            }
        },
        "EmptyLatentImage": {
            "input": {
                "required": {
                    "width": ["INT", {"default": 512}],
                    "height": ["INT", {"default": 512}],
                    "batch_size": ["INT", {"default": 1}],
                },
                "optional": {},
            }
        },
        "KSampler": {
            "input": {
                "required": {
                    # widget inputs (order matters; matches workflow widgets_values)
                    "seed": ["INT", {"default": 0}],
                    "control_after_generate": ["STRING", {"default": "randomize"}],
                    "steps": ["INT", {"default": 20}],
                    "cfg": ["FLOAT", {"default": 8}],
                    "sampler_name": ["STRING", {"default": "euler"}],
                    "scheduler": ["STRING", {"default": "normal"}],
                    "denoise": ["FLOAT", {"default": 1.0}],
                    # connection-only inputs (skipped as widgets)
                    "model": ["MODEL", {}],
                    "positive": ["CONDITIONING", {}],
                    "negative": ["CONDITIONING", {}],
                    "latent_image": ["LATENT", {}],
                },
                "optional": {},
            }
        },
        "VAEDecode": {
            "input": {
                "required": {
                    "samples": ["LATENT", {}],
                    "vae": ["VAE", {}],
                },
                "optional": {},
            }
        },
        "SaveImage": {
            "input": {
                "required": {
                    "filename_prefix": ["STRING", {"default": "output"}],
                    "images": ["IMAGE", {}],
                },
                "optional": {},
            }
        },
    }


class TestSubgraphs(unittest.TestCase):
    def test_default_subgraph_converts_like_default(self):
        wf_flat = json.loads(fixture_path("default.json").read_text(encoding="utf-8"))
        wf_sg = json.loads(fixture_path("default-subgraph.json").read_text(encoding="utf-8"))
        oi = _mini_object_info()

        api_flat = Flow.load(wf_flat).convert(object_info=oi)
        api_sg = Flow.load(wf_sg).convert(object_info=oi)

        # No UUID class_type should remain after flattening.
        for node in api_sg.values():
            self.assertIn("class_type", node)
            ct = node["class_type"]
            self.assertFalse(
                isinstance(ct, str) and "-" in ct and len(ct) >= 32,
                f"Unexpected UUID-ish class_type: {ct!r}",
            )

        # The set of node types should match the non-subgraph version.
        types_flat = sorted([n["class_type"] for n in api_flat.values()])
        types_sg = sorted([n["class_type"] for n in api_sg.values()])
        self.assertEqual(types_sg, types_flat)

        # Spot-check key wiring: SaveImage.images should come from VAEDecode.
        save_ids = [nid for nid, n in api_sg.items() if n.get("class_type") == "SaveImage"]
        self.assertEqual(len(save_ids), 1)
        save = api_sg[save_ids[0]]
        images = save.get("inputs", {}).get("images")
        self.assertIsInstance(images, list)
        self.assertEqual(len(images), 2)
        upstream_id = str(images[0])
        upstream = api_sg.get(upstream_id)
        self.assertIsNotNone(upstream)
        self.assertEqual(upstream.get("class_type"), "VAEDecode")


if __name__ == "__main__":
    unittest.main()


