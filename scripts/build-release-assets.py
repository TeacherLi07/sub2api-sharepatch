#!/usr/bin/env python3
"""Cross-build supported update archives and checksums from a patched checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


TARGETS = (
    ("linux", "amd64"),
    ("linux", "arm64"),
    ("darwin", "amd64"),
    ("darwin", "arm64"),
    ("windows", "amd64"),
)


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
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    backend = upstream / "backend"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    patch_commit = os.environ.get("GITHUB_SHA", "local")
    build_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with tempfile.TemporaryDirectory(prefix="sharepatch-build-") as temporary:
        work = Path(temporary)
        for goos, goarch in TARGETS:
            filename = f"sub2api_{args.version}_{goos}_{goarch}"
            binary_name = "sub2api.exe" if goos == "windows" else "sub2api"
            binary_path = work / binary_name
            env = os.environ.copy()
            env.update({"CGO_ENABLED": "0", "GOOS": goos, "GOARCH": goarch})
            ldflags = (
                f"-s -w -X main.Version={args.version} -X main.Commit={args.upstream_sha} "
                f"-X main.Date={build_date} -X main.BuildType=release"
            )
            run(
                ["go", "build", "-p", "2", "-tags", "embed", "-trimpath", "-ldflags", ldflags, "-o", str(binary_path), "./cmd/server"],
                backend,
                env,
            )
            if goos == "linux" and goarch == "amd64":
                version_output = subprocess.check_output([str(binary_path), "-version"], text=True)
                if args.version not in version_output:
                    raise SystemExit(f"built binary reported unexpected version: {version_output.strip()}")
            archive = output / (filename + (".zip" if goos == "windows" else ".tar.gz"))
            if goos == "windows":
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                    bundle.write(binary_path, binary_name)
            else:
                with tarfile.open(archive, "w:gz") as bundle:
                    bundle.add(binary_path, arcname=binary_name)
            binary_path.unlink()

    metadata = {
        "release_version": args.version,
        "patch_repository": args.patch_repo,
        "patch_commit": patch_commit,
        "upstream_repository": "Wei-Shaw/sub2api",
        "upstream_tag": args.upstream_tag,
        "upstream_commit": args.upstream_sha,
        "built_at": build_date,
        "targets": [f"{goos}/{goarch}" for goos, goarch in TARGETS],
    }
    metadata_path = output / "release-metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    checksums = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "checksums.txt":
            checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (output / "checksums.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
