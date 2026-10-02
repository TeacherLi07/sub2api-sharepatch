#!/usr/bin/env python3
"""Resume draft releases and promote only complete, verified release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from release_assets import (
    DIGEST_PATTERN, archive_name, normalize_version, parse_checksums,
    validate_metadata, verify_directory, write_checksums,
)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and urllib.parse.urlparse(newurl).hostname != "api.github.com":
            redirected.remove_header("Authorization")
        return redirected


class GitHub:
    def __init__(self, repo: str):
        self.repo = repo
        self.token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GH_TOKEN or GITHUB_TOKEN is required")
        self.opener = urllib.request.build_opener(SafeRedirect())

    def request(self, path: str, method: str = "GET", data=None,
                missing_ok: bool = False, binary: bool = False):
        url = "https://api.github.com/repos/" + self.repo + "/" + path
        headers = {
            "Authorization": "Bearer " + self.token,
            "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "sub2api-sharepatch-publisher",
        }
        body = None if data is None else json.dumps(data).encode()
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=120) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and missing_ok:
                return None
            raise RuntimeError(f"GitHub {method} {path} failed: HTTP {exc.code}") from exc
        return content if binary else (json.loads(content) if content else None)

    def releases(self):
        page = 1
        while True:
            releases = self.request(f"releases?per_page=100&page={page}")
            yield from releases
            if len(releases) < 100:
                return
            page += 1

    def release(self, tag: str):
        # Include drafts: the by-tag endpoint may not find unpublished tags.
        matches = [item for item in self.releases() if item["tag_name"] == tag]
        if len(matches) > 1:
            raise ValueError(f"duplicate releases for {tag}; resolve them before publishing")
        return self.request(f"releases/{matches[0]['id']}") if matches else None

    def check_tag(self, tag: str, patch_sha: str) -> None:
        ref = self.request("git/ref/tags/" + urllib.parse.quote(tag, safe=""), missing_ok=True)
        if ref is None:
            return
        obj = ref["object"]
        while obj["type"] == "tag":
            obj = self.request("git/tags/" + obj["sha"])["object"]
        if obj["type"] != "commit" or obj["sha"] != patch_sha:
            raise ValueError("existing release tag points to another patch commit; bump PATCH_REVISION")

    def asset(self, asset: dict) -> bytes:
        return self.request(f"releases/assets/{asset['id']}", binary=True)


def output(key: str, value) -> None:
    print(f"{key}={value}")
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as target:
            target.write(f"{key}={value}\n")


def complete_release(github: GitHub, release: dict, args) -> dict | None:
    assets = {asset["name"]: asset for asset in release["assets"]}
    expected = {archive_name(args.version), "release-metadata.json", "checksums.txt"}
    if "release-metadata.json" not in assets:
        return None
    try:
        metadata_data = github.asset(assets["release-metadata.json"])
        metadata = json.loads(metadata_data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    # A different source must never be treated as an incomplete retry.
    validate_metadata(metadata, args.version, args.repo, args.upstream_sha, args.patch_sha)
    if set(assets) != expected or len(assets) != len(release["assets"]):
        return None
    if any(asset.get("state") != "uploaded" or asset.get("size", 0) <= 0 for asset in assets.values()):
        return None
    if not DIGEST_PATTERN.fullmatch(str(metadata.get("image_digest", ""))):
        return None
    try:
        checksums = parse_checksums(github.asset(assets["checksums.txt"]).decode(), args.version)
    except (ValueError, UnicodeDecodeError):
        return None
    if hashlib.sha256(metadata_data).hexdigest() != checksums["release-metadata.json"]:
        return None
    archive = assets[archive_name(args.version)]
    actual = archive.get("digest")
    if not actual:
        actual = "sha256:" + hashlib.sha256(github.asset(archive)).hexdigest()
    if actual != "sha256:" + checksums[archive["name"]]:
        return None
    if release.get("prerelease") != args.prerelease:
        raise ValueError("release channel does not match the selected publication mode")
    return metadata


def promote_allowed(github: GitHub, args) -> bool:
    if args.prerelease:
        return False
    def order(version):
        normalized = normalize_version(version)
        if "-preview." in normalized:
            raise ValueError("latest release unexpectedly points to a preview")
        return tuple(int(part) for part in re.split(r"[.]|-share[.]", normalized))
    selected = order(args.version)
    # Include published versions whose latest promotion failed. Checking only
    # /latest would allow an older run to overwrite their newer Docker latest.
    return all(order(release["tag_name"]) <= selected for release in github.releases()
               if not release["draft"] and not release["prerelease"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "bind-image", "stage", "publish", "inspect", "activate"))
    parser.add_argument("--assets", type=Path, default=Path("release-assets"))
    parser.add_argument("--notes", type=Path, default=Path("release-notes.md"))
    parser.add_argument("--image")
    args = parser.parse_args()
    args.repo = os.environ["GITHUB_REPOSITORY"]
    args.version = normalize_version(os.environ["SHAREPATCH_VERSION"])
    args.upstream_sha = os.environ["UPSTREAM_SHA"]
    args.patch_sha = os.environ["GITHUB_SHA"]
    args.prerelease = os.environ.get("SHAREPATCH_PRERELEASE") == "true"
    if args.prerelease != ("-preview." in args.version):
        raise ValueError("preview version and publication channel must agree")
    tag = "v" + args.version
    if args.command == "bind-image":
        metadata = verify_directory(args.assets, args.version, args.repo, args.upstream_sha, args.patch_sha)
        image_repo, digest = (args.image or "").rsplit("@", 1)
        if image_repo != metadata["image_repository"] or not DIGEST_PATTERN.fullmatch(digest):
            raise ValueError("pushed image reference does not match the release repository")
        metadata["image_digest"] = digest
        (args.assets / "release-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        write_checksums(args.assets, args.version)
        verify_directory(args.assets, args.version, args.repo, args.upstream_sha, args.patch_sha, True)
        return

    github = GitHub(args.repo)
    github.check_tag(tag, args.patch_sha)
    release = github.release(tag)
    metadata = complete_release(github, release, args) if release else None
    if args.command == "preflight":
        output("skip", str(bool(release and not release["draft"] and metadata)).lower())
        return
    if args.command == "stage":
        verify_directory(args.assets, args.version, args.repo, args.upstream_sha, args.patch_sha, True)
        if release and not release["draft"] and metadata:
            raise ValueError("release became complete; rerun to reuse its existing image")
        payload = {"tag_name": tag, "target_commitish": args.patch_sha,
                   "name": tag, "body": args.notes.read_text(), "draft": True,
                   "prerelease": args.prerelease, "make_latest": "false"}
        if release:
            if release.get("immutable"):
                raise ValueError("incomplete immutable release cannot be repaired; bump PATCH_REVISION")
            release = github.request(f"releases/{release['id']}", "PATCH", payload)
            # Replace incomplete draft assets as one set, including obsolete filenames.
            for asset in release["assets"]:
                github.request(f"releases/assets/{asset['id']}", "DELETE")
        else:
            release = github.request("releases", "POST", payload)
        paths = [str(args.assets / name) for name in (archive_name(args.version), "release-metadata.json", "checksums.txt")]
        subprocess.run(["gh", "release", "upload", tag, *paths, "--repo", args.repo], check=True)
        release = github.request(f"releases/{release['id']}")
        remote = complete_release(github, release, args)
        local = verify_directory(args.assets, args.version, args.repo, args.upstream_sha, args.patch_sha, True)
        if remote != local:
            raise ValueError("uploaded release does not match local verified artifacts")
        return
    if not release or not metadata:
        raise ValueError("release is missing verified artifacts")
    if args.command == "publish":
        github.request(f"releases/{release['id']}", "PATCH", {"draft": False, "make_latest": "false"})
        return
    if release["draft"]:
        raise ValueError("draft releases cannot be promoted")
    if args.command == "inspect":
        output("image_ref", metadata["image_repository"] + "@" + metadata["image_digest"])
        output("promote", str(promote_allowed(github, args)).lower())
    elif args.command == "activate" and promote_allowed(github, args):
        github.request(f"releases/{release['id']}", "PATCH", {"make_latest": "true"})


if __name__ == "__main__":
    main()
