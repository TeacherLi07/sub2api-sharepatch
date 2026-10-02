"""Shared validation for the Linux/amd64 release and its Docker context."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
from pathlib import Path


VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+-share\.\d+(?:-preview\.\d+\.\d+)?")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def normalize_version(value: str) -> str:
    version = value.removeprefix("v")
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"unsupported sharepatch version: {value!r}")
    return version


def archive_name(version: str) -> str:
    return f"sub2api_{normalize_version(version)}_linux_amd64.tar.gz"


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_checksums(directory: Path, version: str) -> None:
    names = sorted((archive_name(version), "release-metadata.json"))
    (directory / "checksums.txt").write_text(
        "".join(f"{sha256(directory / name)}  {name}\n" for name in names), encoding="utf-8"
    )


def parse_checksums(data: str, version: str) -> dict[str, str]:
    result = {}
    for line in data.splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]) or parts[1] in result:
            raise ValueError("invalid or duplicate release checksum")
        result[parts[1]] = parts[0]
    if set(result) != {archive_name(version), "release-metadata.json"}:
        raise ValueError("missing or unexpected release checksum entries")
    return result


def validate_metadata(metadata: dict, version: str, repo: str, upstream_sha: str,
                      patch_sha: str, require_image: bool = False) -> None:
    expected = {
        "release_version": "v" + normalize_version(version),
        "patch_repository": repo,
        "patch_commit": patch_sha,
        "upstream_repository": "Wei-Shaw/sub2api",
        "upstream_tag": "v" + normalize_version(version).split("-share.", 1)[0],
        "upstream_commit": upstream_sha,
        "targets": ["linux/amd64"],
        "archive": archive_name(version),
        "image_repository": "ghcr.io/" + repo.lower(),
    }
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise ValueError("release provenance does not match the selected source/version")
    if not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("binary_sha256", ""))):
        raise ValueError("missing binary SHA256")
    if require_image and not DIGEST_PATTERN.fullmatch(str(metadata.get("image_digest", ""))):
        raise ValueError("missing verified image digest")


def verify_directory(directory: Path, version: str, repo: str, upstream_sha: str,
                     patch_sha: str, require_image: bool = False) -> dict:
    expected = {archive_name(version), "release-metadata.json", "checksums.txt"}
    if {path.name for path in directory.iterdir()} != expected:
        raise ValueError("missing or unexpected release files")
    checksums = parse_checksums((directory / "checksums.txt").read_text(), version)
    for name, digest in checksums.items():
        if sha256(directory / name) != digest:
            raise ValueError(f"checksum mismatch: {name}")
    metadata = json.loads((directory / "release-metadata.json").read_text())
    validate_metadata(metadata, version, repo, upstream_sha, patch_sha, require_image)
    return metadata


def prepare_context(upstream: Path, directory: Path, context: Path, version: str,
                    repo: str, upstream_sha: str, patch_sha: str) -> None:
    metadata = verify_directory(directory, version, repo, upstream_sha, patch_sha)
    context.mkdir(parents=True, exist_ok=True)
    if any(context.iterdir()):
        raise ValueError("Docker context must be empty")
    # Extract only the verified regular executable, never arbitrary archive paths.
    with tarfile.open(directory / archive_name(version), "r:gz") as archive:
        members = archive.getmembers()
        if len(members) != 1 or members[0].name != "sub2api" or not members[0].isfile():
            raise ValueError("archive must contain exactly one regular sub2api binary")
        with archive.extractfile(members[0]) as source, (context / "sub2api").open("wb") as target:
            shutil.copyfileobj(source, target)
    binary = context / "sub2api"
    if sha256(binary) != metadata["binary_sha256"]:
        raise ValueError("archive binary does not match release metadata")
    with binary.open("rb") as source:
        header = source.read(20)
    if header[:6] != b"\x7fELF\x02\x01" or header[18:20] != b"\x3e\x00":
        raise ValueError("release executable must be a Linux/amd64 ELF binary")
    binary.chmod(0o755)
    shutil.copy2(upstream / "Dockerfile.goreleaser", context / "Dockerfile")
    (context / "deploy").mkdir()
    shutil.copy2(upstream / "deploy/docker-entrypoint.sh", context / "deploy/docker-entrypoint.sh")
    shutil.copytree(upstream / "backend/resources", context / "backend/resources")
