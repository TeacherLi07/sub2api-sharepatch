"""Keep upstream checks and fail closed when an independent CI job fails."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_patch_anchors import load_script


class FrontendBuildTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script("build-frontend")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.frontend = Path(temporary.name)

    def commands(self, typecheck, build, failure=None):
        (self.frontend / "package.json").write_text(json.dumps({
            "scripts": {"typecheck": typecheck, "build": build},
        }))
        with patch.object(self.script.subprocess, "run", side_effect=failure) as run:
            if failure:
                with self.assertRaises(subprocess.CalledProcessError):
                    self.script.build(self.frontend)
            else:
                self.script.build(self.frontend)
        return [call.args[0] for call in run.call_args_list]

    def test_known_build_keeps_the_whole_upstream_build_command(self):
        self.assertEqual(self.commands(self.script.CHECKED_TYPECHECK, self.script.CHECKED_BUILD),
                         [["pnpm", "run", "build"]])

    def test_changes_to_either_script_preserve_the_explicit_typecheck(self):
        for typecheck, build in (
            ("vue-tsc --noEmit && extra-check", self.script.CHECKED_BUILD),
            (self.script.CHECKED_TYPECHECK, "vite build"),
            (self.script.CHECKED_TYPECHECK, self.script.CHECKED_BUILD + " && extra-check"),
        ):
            with self.subTest(typecheck=typecheck, build=build):
                self.assertEqual(self.commands(typecheck, build),
                                 [["pnpm", "run", "typecheck"], ["pnpm", "run", "build"]])

    def test_failed_typecheck_stops_build_and_failed_build_is_not_swallowed(self):
        failure = subprocess.CalledProcessError(2, ["pnpm"])
        self.assertEqual(self.commands("changed-typecheck", "vite build", failure),
                         [["pnpm", "run", "typecheck"]])
        self.assertEqual(self.commands(self.script.CHECKED_TYPECHECK, self.script.CHECKED_BUILD, failure),
                         [["pnpm", "run", "build"]])

    def test_cli_propagates_a_real_nonzero_build_exit(self):
        (self.frontend / "package.json").write_text(json.dumps({"scripts": {
            "typecheck": self.script.CHECKED_TYPECHECK, "build": self.script.CHECKED_BUILD,
        }}))
        binaries = self.frontend / "bin"
        binaries.mkdir()
        pnpm = binaries / "pnpm"
        pnpm.write_text("#!/bin/sh\nexit 2\n")
        pnpm.chmod(0o755)
        env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"])
        result = subprocess.run(
            ["python3", self.script.__file__, "--frontend", str(self.frontend)],
            env=env, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)


class VerificationGateTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script("verify-ci-results")
        self.results = {name: {"result": "success"} for name in self.script.REQUIRED_JOBS}

    def test_every_required_job_must_succeed(self):
        self.assertEqual(self.script.verified_artifact(self.results, "verified-release-123"),
                         "verified-release-123")
        for name in self.results:
            for result in ("failure", "skipped", "cancelled"):
                with self.subTest(job=name, result=result):
                    failed = dict(self.results, **{name: {"result": result}})
                    with self.assertRaisesRegex(ValueError, "did not succeed"):
                        self.script.verified_artifact(failed, "verified-release-123")

    def test_missing_dependency_or_artifact_cannot_release_an_existing_package(self):
        for name in self.results:
            missing = {key: value for key, value in self.results.items() if key != name}
            with self.subTest(missing=name), self.assertRaisesRegex(ValueError, "dependencies changed"):
                self.script.verified_artifact(missing, "verified-release-123")
        for artifact in ("", "artifact\nextra-output=true"):
            with self.subTest(artifact=artifact), self.assertRaisesRegex(ValueError, "artifact name"):
                self.script.verified_artifact(self.results, artifact)

    def test_failed_frontend_tests_do_not_emit_an_artifact_even_when_packaging_passed(self):
        self.results["frontend-tests"] = {"result": "failure"}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            env = dict(os.environ, CHECK_RESULTS=json.dumps(self.results),
                       VERIFIED_ARTIFACT="verified-release-123", GITHUB_OUTPUT=str(output))
            result = subprocess.run(["python3", self.script.__file__], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
