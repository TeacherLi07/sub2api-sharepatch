#!/usr/bin/env python3
"""Build the Linux/amd64 update archive and checksums from a patched checkout."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from release_assets import archive_name, normalize_version, prepare_context, sha256, write_checksums


TARGET_OS = "linux"
TARGET_ARCH = "amd64"


def run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument("--upstream-sha", required=True)
    parser.add_argument("--patch-repo", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--docker-context", required=True, type=Path)
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    backend = upstream / "backend"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SystemExit("release output directory must be empty")
    version = normalize_version(args.version)
    actual_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip()
    if actual_sha != args.upstream_sha:
        raise SystemExit(f"checkout SHA is {actual_sha}; expected exactly {args.upstream_sha}")
    patch_commit = os.environ.get("GITHUB_SHA", "local")
    build_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with tempfile.TemporaryDirectory(prefix="sharepatch-build-") as temporary:
        work = Path(temporary)
        binary_name = "sub2api"
        binary_path = work / binary_name
        env = os.environ.copy()
        env.update({"CGO_ENABLED": "0", "GOOS": TARGET_OS, "GOARCH": TARGET_ARCH})
        ldflags = (
            f"-s -w -X main.Version={version} -X main.Commit={args.upstream_sha} "
            f"-X main.Date={build_date} -X main.BuildType=release"
        )
        run(
            ["go", "build", "-p", "2", "-tags", "embed", "-trimpath", "-ldflags", ldflags, "-o", str(binary_path), "./cmd/server"],
            backend,
            env,
        )
        version_output = subprocess.check_output(
            [str(binary_path), "-version"], text=True, stderr=subprocess.STDOUT
        )
        if f"Sub2API {version} (commit: {args.upstream_sha}, built: {build_date})" not in version_output:
            raise SystemExit(f"built binary reported unexpected version: {version_output.strip()}")
        binary_digest = sha256(binary_path)
        archive = output / archive_name(version)
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(binary_path, arcname=binary_name)

    metadata = {
        "release_version": "v" + version,
        "patch_repository": args.patch_repo,
        "patch_commit": patch_commit,
        "upstream_repository": "Wei-Shaw/sub2api",
        "upstream_tag": args.upstream_tag,
        "upstream_commit": args.upstream_sha,
        "built_at": build_date,
        "targets": [f"{TARGET_OS}/{TARGET_ARCH}"],
        "archive": archive.name,
        "binary_sha256": binary_digest,
        "image_repository": "ghcr.io/" + args.patch_repo.lower(),
    }
    metadata_path = output / "release-metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    write_checksums(output, version)
    prepare_context(upstream, output, args.docker_context.resolve(), version,
                    args.patch_repo, args.upstream_sha, patch_commit)


if __name__ == "__main__":
    main()
