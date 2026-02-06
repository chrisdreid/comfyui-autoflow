#!/usr/bin/env python3
"""Offline tests for FilesResult.save() filename templating and selection.

Run:
  python3 -m unittest examples.unittests.test_save_formatting -v
"""

import sys
import unittest
from pathlib import Path
import tempfile

# Allow running this file directly without installing the package.
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root))

from autoflow.api import FilesResult, FileResult  # noqa: E402


class TestFilesSaveFormatting(unittest.TestCase):
    def _files(self):
        return FilesResult(
            [
                FileResult(
                    {
                        "ref": {"kind": "images", "filename": "SD1.5_00108_.png", "subfolder": "", "type": "output"},
                        "bytes": b"PNGDATA",
                    }
                ),
                FileResult(
                    {
                        "ref": {"kind": "files", "filename": "mesh_12.obj", "subfolder": "", "type": "output"},
                        "bytes": b"OBJDATA",
                    }
                ),
            ]
        )

    def test_list_property(self):
        f = self._files()
        self.assertEqual(f.list, ["SD1.5_00108_.png", "mesh_12.obj"])

    def test_save_default_keeps_names(self):
        f = self._files()
        with tempfile.TemporaryDirectory() as td:
            paths = f.save(output_path=td)
            names = sorted([p.name for p in paths])
            self.assertEqual(names, ["SD1.5_00108_.png", "mesh_12.obj"])

    def test_save_template_tokens(self):
        f = self._files()
        with tempfile.TemporaryDirectory() as td:
            paths = f.save(output_path=td, filename="{base}_v01.{sequence}.{ext}")
            names = sorted([p.name for p in paths])
            # mesh_12.obj -> base="mesh_", sequence="12", tail=""
            self.assertIn("SD1.5__v01.00108.png", names)
            self.assertIn("mesh__v01.12.obj", names)

    def test_save_hash_index(self):
        f = self._files()
        with tempfile.TemporaryDirectory() as td:
            paths = f.save(output_path=td, filename="out.####.{ext}", index_offset=1000)
            names = sorted([p.name for p in paths])
            self.assertEqual(names, ["out.1000.png", "out.1001.obj"])

    def test_save_percent_index(self):
        f = self._files()
        with tempfile.TemporaryDirectory() as td:
            paths = f.save(output_path=td, filename="out.%04d.{ext}", index_offset=7)
            names = sorted([p.name for p in paths])
            self.assertEqual(names, ["out.0007.png", "out.0008.obj"])

    def test_save_only_subset(self):
        f = self._files()
        with tempfile.TemporaryDirectory() as td:
            paths = f.save(only=["mesh_12.obj"], output_path=td)
            self.assertEqual([p.name for p in paths], ["mesh_12.obj"])

    def test_regex_overrides_tokens(self):
        f = self._files()
        # Note: this regex matches "SD1.5_00108_.png" and exposes {prefix},{sequence},{ext}
        rx = r"(?P<prefix>.*)_(?P<sequence>\d+)_\.(?P<ext>.*)"
        with tempfile.TemporaryDirectory() as td:
            paths = f.save(
                only=["SD1.5_00108_.png"],
                output_path=td,
                filename="{prefix}.{sequence}.{ext}",
                regex_parser=rx,
                overwrite=True,
            )
            self.assertEqual([p.name for p in paths], ["SD1.5.00108.png"])

    def test_src_frame_token(self):
        f = self._files()
        with tempfile.TemporaryDirectory() as td:
            paths = f.save(only=["SD1.5_00108_.png"], output_path=td, filename="frame.{src_frame}.{ext}", overwrite=True)
            self.assertEqual([p.name for p in paths], ["frame.108.png"])


if __name__ == "__main__":
    unittest.main()


