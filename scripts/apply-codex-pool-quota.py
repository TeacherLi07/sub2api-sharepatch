#!/usr/bin/env python3
"""Apply the pinned PR #9024 diff without changing the upstream release HEAD."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "customizations/codex-pool-quota"


def fail(message: str) -> None:
    raise SystemExit(f"apply-codex-pool-quota: {message}")


def git(upstream: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(upstream), *args], text=True, capture_output=True, check=False,
    )


def apply(upstream: Path, upstream_sha: str) -> str:
    head = git(upstream, "rev-parse", "HEAD")
    if head.returncode or head.stdout.strip() != upstream_sha:
        fail(f"checkout SHA is {head.stdout.strip()!r}; expected exactly {upstream_sha}")
    status = git(upstream, "status", "--porcelain", "--untracked-files=all")
    if status.returncode or status.stdout.strip():
        fail("target must be a clean, disposable checkout; apply this patch before other overlays")

    manifest = json.loads((SOURCE / "manifest.json").read_text())
    patch = SOURCE / "pr-9024.patch"
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest["patch_sha256"]:
        fail("vendored patch SHA256 does not match manifest.json")
    # A complete reverse check also handles upstream squash merges. Partial
    # adoption or later edits require review rather than a silent partial apply.
    if git(upstream, "apply", "--reverse", "--check", str(patch)).returncode == 0:
        return "already present in upstream"
    checked = git(upstream, "apply", "--check", str(patch))
    if checked.returncode:
        fail("pinned PR conflicts with upstream; review before publishing:\n" + checked.stderr.strip())
    applied = git(upstream, "apply", str(patch))
    if applied.returncode:
        fail(applied.stderr.strip())
    return "applied"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--upstream-sha", required=True)
    args = parser.parse_args()
    result = apply(args.upstream.resolve(), args.upstream_sha)
    print(f"Codex pool quota PR #9024: {result} (upstream HEAD {args.upstream_sha})")


if __name__ == "__main__":
    main()
