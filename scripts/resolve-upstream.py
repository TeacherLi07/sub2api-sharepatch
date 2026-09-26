#!/usr/bin/env python3
"""Resolve the latest official Sub2API release to its immutable commit SHA."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


API = "https://api.github.com"
ROOT = Path(__file__).resolve().parents[1]


def github_json(url: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "sub2api-sharepatch-release-resolver",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise SystemExit(f"GitHub API request failed for {url}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"GitHub API returned an unexpected response for {url}")
    return value


def resolve_tag_commit(repo: str, tag: str) -> str:
    ref = github_json(f"{API}/repos/{repo}/git/ref/tags/{urllib.parse.quote(tag, safe='')}")
    obj = ref.get("object") or {}
    while obj.get("type") == "tag":
        tag_obj = github_json(f"{API}/repos/{repo}/git/tags/{obj['sha']}")
        obj = tag_obj.get("object") or {}
    if obj.get("type") != "commit" or not re.fullmatch(r"[0-9a-f]{40}", str(obj.get("sha", ""))):
        raise SystemExit(f"release tag {tag} did not resolve to a commit")
    return obj["sha"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="Wei-Shaw/sub2api")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args()
    release = github_json(f"{API}/repos/{args.repo}/releases/latest")
    if release.get("draft") or release.get("prerelease"):
        raise SystemExit("GitHub latest-release endpoint returned a draft or prerelease")
    tag = str(release.get("tag_name", ""))
    match = re.fullmatch(r"v(\d+\.\d+\.\d+)", tag)
    if not match:
        raise SystemExit(f"unsupported upstream release tag: {tag!r}")
    sha = resolve_tag_commit(args.repo, tag)

    try:
        revision = int((ROOT / "PATCH_REVISION").read_text().strip())
    except (OSError, ValueError) as exc:
        raise SystemExit(f"PATCH_REVISION must contain a positive integer: {exc}") from exc
    if revision <= 0:
        raise SystemExit("PATCH_REVISION must be a positive integer")
    version = f"{match.group(1)}-share.{revision}"
    values = {
        "upstream_tag": tag,
        "upstream_sha": sha,
        "upstream_version": match.group(1),
        "sharepatch_revision": str(revision),
        "release_version": version,
    }
    for key, value in values.items():
        print(f"{key}={value}")
        if args.github_output:
            with open(args.github_output, "a", encoding="utf-8") as output:
                output.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
