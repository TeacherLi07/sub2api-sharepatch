"""Exercise the downstream patch safety gates with real disposable Git repos."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_patch_anchors import load_script


class CodexPoolQuotaPatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        self.source = self.root / "source"
        self.source.mkdir()
        self.script = load_script("apply-codex-pool-quota")
        self.script.SOURCE = self.source
        self.git("init", "-q")
        for name in ("one", "two"):
            (self.upstream / name).write_text("before\n")
        self.commit()
        self.sha = self.git("rev-parse", "HEAD")
        for name in ("one", "two"):
            (self.upstream / name).write_text("after\n")
        patch = self.git("diff") + "\n"
        (self.source / "pr-9024.patch").write_text(patch)
        (self.source / "manifest.json").write_text(json.dumps({
            "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
        }))
        self.git("reset", "--hard", "HEAD")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.upstream), *args], text=True, stderr=subprocess.PIPE,
        ).strip()

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=Patch test", "-c", "user.email=patch@example.test",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")

    def test_applies_both_files_and_preserves_release_head(self):
        self.assertEqual(self.script.apply(self.upstream, self.sha), "applied")
        for name in ("one", "two"):
            self.assertEqual((self.upstream / name).read_text(), "after\n")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.sha)

    def test_rejects_wrong_sha_and_dirty_or_untracked_files(self):
        with self.assertRaisesRegex(SystemExit, "expected exactly"):
            self.script.apply(self.upstream, "0" * 40)
        for name in ("one", "untracked"):
            with self.subTest(name=name):
                path = self.upstream / name
                path.write_text("local work\n")
                with self.assertRaisesRegex(SystemExit, "clean, disposable"):
                    self.script.apply(self.upstream, self.sha)
                self.assertEqual(path.read_text(), "local work\n")
                if name == "one":
                    self.git("restore", name)
                else:
                    path.unlink()

    def test_conflict_does_not_partially_apply_other_file(self):
        (self.upstream / "two").write_text("upstream changed\n")
        self.commit()
        with self.assertRaisesRegex(SystemExit, "conflicts with upstream"):
            self.script.apply(self.upstream, self.git("rev-parse", "HEAD"))
        self.assertEqual((self.upstream / "one").read_text(), "before\n")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_skips_fully_merged_patch_but_rejects_partial_adoption(self):
        (self.upstream / "one").write_text("after\n")
        self.commit()
        with self.assertRaisesRegex(SystemExit, "conflicts with upstream"):
            self.script.apply(self.upstream, self.git("rev-parse", "HEAD"))
        self.assertEqual((self.upstream / "two").read_text(), "before\n")
        (self.upstream / "two").write_text("after\n")
        self.commit()
        self.assertEqual(
            self.script.apply(self.upstream, self.git("rev-parse", "HEAD")),
            "already present in upstream",
        )
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_rejects_patch_checksum_mismatch_before_writing(self):
        (self.source / "pr-9024.patch").write_text("corrupt patch\n")
        with self.assertRaisesRegex(SystemExit, "SHA256"):
            self.script.apply(self.upstream, self.sha)
        self.assertEqual(self.git("status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
