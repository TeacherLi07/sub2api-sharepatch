#!/usr/bin/env python3
"""Expose release assets only after the complete verification graph succeeds."""

from __future__ import annotations

import json
import os


REQUIRED_JOBS = {"prepare", "go-tests", "frontend-tests", "frontend-build", "package"}


def verified_artifact(results: dict, artifact: str) -> str:
    if set(results) != REQUIRED_JOBS:
        raise ValueError("verification dependencies changed; review the complete check list")
    incomplete = [name for name, job in results.items() if job.get("result") != "success"]
    if incomplete:
        raise ValueError("verification did not succeed: " + ", ".join(sorted(incomplete)))
    if not artifact or any(character in artifact for character in "\r\n"):
        raise ValueError("missing or invalid verified artifact name")
    return artifact


def main() -> None:
    artifact = verified_artifact(json.loads(os.environ["CHECK_RESULTS"]), os.environ["VERIFIED_ARTIFACT"])
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"artifact-name={artifact}\n")


if __name__ == "__main__":
    main()
