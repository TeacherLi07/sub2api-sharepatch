"""Verify shard coverage, nested tests, examples, fuzz seeds, and failure propagation."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_patch_anchors import load_script


class GoPartitionTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script("run-go-tests")

    def test_partitions_cover_every_target_exactly_once_and_are_stable(self):
        names = [f"TestCase{i}" for i in range(9000)] + ["ExampleAlpha", "FuzzAlpha", "Test中文"]
        shards = [self.script.shard_names(names, i) for i in range(3)]
        self.assertEqual(sorted(name for shard in shards for name in shard), sorted(names))
        for i, shard in enumerate(shards):
            self.assertEqual(shard, self.script.shard_names(list(reversed(names)), i))
            pattern = self.script.name_pattern(shard)
            self.assertLess(len(pattern.encode()), 100_000)
            selected = set(shard)
            self.assertEqual([name for name in names if re.fullmatch(pattern, name)],
                             [name for name in names if name in selected])
            self.assertIsNone(re.fullmatch(pattern, "TestCase0UnexpectedSuffix"))

    def test_growing_test_names_are_batched_with_no_overlap_or_argument_overflow(self):
        names = [f"TestCase{i:04d}" for i in range(100)]
        patterns = self.script.name_patterns(names, max_bytes=70)
        self.assertGreater(len(patterns), 1)
        matched = [name for pattern in patterns for name in names if re.fullmatch(pattern, name)]
        self.assertCountEqual(matched, names)
        self.assertTrue(all(len(pattern.encode()) <= 70 for pattern in patterns))

    def test_package_partition_excludes_only_the_service_package(self):
        service = self.script.SERVICE
        packages = [service + "/openai_ws_v2", service, "example.test/another"]
        with patch.object(self.script.subprocess, "check_output", return_value="\n".join(packages)), \
                patch.object(self.script.subprocess, "run") as run:
            self.script.run(Path("."), "unit", "packages")
        self.assertEqual(run.call_args.args[0],
                         ["go", "test", "-tags=unit", packages[0], packages[2]])

    def test_missing_service_and_failed_discovery_do_not_silently_pass(self):
        with patch.object(self.script.subprocess, "check_output", return_value="example.test/other\n"):
            with self.assertRaisesRegex(ValueError, "moved"):
                self.script.run(Path("."), "unit", "packages")
        with patch.object(self.script.subprocess, "check_output", return_value="ok example.test/service\n"):
            with self.assertRaisesRegex(ValueError, "missing"):
                self.script.run(Path("."), "integration", "service-0")
        with patch.object(self.script.subprocess, "check_output",
                          side_effect=subprocess.CalledProcessError(1, ["go", "test"])):
            with self.assertRaises(subprocess.CalledProcessError):
                self.script.run(Path("."), "integration", "service-0")

    @unittest.skipUnless(shutil.which("go"), "Go is required for the executable partition fixture")
    def test_real_go_runs_nested_tests_examples_and_fuzz_seeds_once_and_reports_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module github.com/Wei-Shaw/sub2api\n\ngo 1.23\n")
            service = root / "internal/service"
            service.mkdir(parents=True)
            (service / "service.go").write_text("package service\nfunc Alpha() {}\n")
            other = root / "internal/other"
            other.mkdir()
            (other / "other_test.go").write_text("package other\nimport \"testing\"\nfunc TestOther(t *testing.T) {}\n")
            record = '''package service
import ("fmt"; "os"; "testing")
func record(name string) {
    f, err := os.OpenFile(os.Getenv("SHAREPATCH_PARTITION_LOG"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0600)
    if err != nil { panic(err) }; defer f.Close(); fmt.Fprintln(f, name)
}
'''
            names = [f"TestCase{i:02d}" for i in range(18)]
            source = record + "\n".join(
                f'func {name}(t *testing.T) {{ record(t.Name()); t.Run("child", func(t *testing.T) {{ record(t.Name()) }}) }}'
                for name in names
            )
            source += '''
func ExampleAlpha() { record("ExampleAlpha"); fmt.Println("ok")
// Output: ok
}
func FuzzAlpha(f *testing.F) { f.Add("seed"); f.Fuzz(func(t *testing.T, value string) { record("FuzzAlpha") }) }
func Test中文(t *testing.T) { record(t.Name()) }
'''
            (service / "service_test.go").write_text(source)
            for tag in ("unit", "integration"):
                (service / f"{tag}_test.go").write_text(
                    f'//go:build {tag}\n\npackage service\nimport "testing"\n'
                    f'func Test{tag.title()}Only(t *testing.T) {{ record(t.Name()) }}\n'
                )
            (service / "not_unit_test.go").write_text(
                '//go:build !unit\n\npackage service\nimport "testing"\n'
                'func TestNonUnitOnly(t *testing.T) { record(t.Name()) }\n'
            )
            log = root / "targets.log"
            with patch.dict(os.environ, {"SHAREPATCH_PARTITION_LOG": str(log)}):
                for tag in ("unit", "integration"):
                    with self.subTest(tag=tag):
                        log.unlink(missing_ok=True)
                        self.script.run(root, tag, "packages")
                        for i in range(3):
                            self.script.run(root, tag, f"service-{i}")
                        actual = log.read_text().splitlines()
                        expected = names + [name + "/child" for name in names] + [
                            "ExampleAlpha", "FuzzAlpha", "Test中文", f"Test{tag.title()}Only",
                        ]
                        if tag == "integration":
                            expected.append("TestNonUnitOnly")
                        self.assertCountEqual(actual, expected)
                failing = "TestDeliberateFailure"
                with (service / "service_test.go").open("a") as target:
                    target.write(f'\nfunc {failing}(t *testing.T) {{ t.Fatal("expected fixture failure") }}\n')
                shard = next(i for i in range(3) if self.script.shard_names([failing], i))
                with self.assertRaises(subprocess.CalledProcessError):
                    self.script.run(root, "unit", f"service-{shard}")


if __name__ == "__main__":
    unittest.main()
