"""Patch scripts must reject upstream drift without partially writing a file."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PatchAnchorTests(unittest.TestCase):
    def test_missing_or_ambiguous_regex_anchors_leave_source_unchanged(self):
        for name in ("apply-overlay", "apply-codex-customizations"):
            script = load_script(name)
            for source, count in (("unrelated source\n", 0), ("anchor\nanchor\n", 2)):
                with self.subTest(script=name, count=count), tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / "source.ts"
                    path.write_text(source)
                    with self.assertRaisesRegex(SystemExit, f"found {count}"):
                        script.patch_regex(path, r"^anchor$", "patched", "test", "patched")
                    self.assertEqual(path.read_text(), source)

if __name__ == "__main__":
    unittest.main()
