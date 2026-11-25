#!/usr/bin/env python3
"""Keep normal packages together and shard the large service package by test name."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import subprocess


SERVICE = "github.com/Wei-Shaw/sub2api/internal/service"
SERVICE_SHARDS = 3
# Go's -list output includes top-level tests, examples, and fuzz seed targets.
# Benchmarks do not run under the original `go test` commands.
TEST_NAME = re.compile(r"(?:Test|Example|Fuzz)\w*")


def shard_names(names: list[str], index: int, count: int = SERVICE_SHARDS) -> list[str]:
    if not 0 <= index < count:
        raise ValueError("invalid service shard")
    return sorted(name for name in names
                  if int.from_bytes(hashlib.sha256(name.encode()).digest(), "big") % count == index)


def name_pattern(names: list[str]) -> str:
    """Compress common prefixes so thousands of names fit the OS argument limit."""
    def alternatives(words: list[str]) -> str:
        groups: dict[str, list[str]] = {}
        for word in words:
            groups.setdefault(word[:1], []).append(word[1:])
        branches = [re.escape(char) + alternatives(tails) if char else ""
                    for char, tails in sorted(groups.items())]
        if not branches:
            return ""
        return branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"

    if not names:
        raise ValueError("cannot build an empty test pattern")
    return "^" + alternatives(names) + "$"


def name_patterns(names: list[str], max_bytes: int = 120_000) -> list[str]:
    # Linux limits each argv entry to 128 KiB. Leave headroom and split only
    # if upstream adds enough tests to exceed it, preserving complete coverage.
    pattern = name_pattern(names)
    if len(pattern.encode()) <= max_bytes:
        return [pattern]
    if len(names) == 1:
        raise ValueError("test name exceeds the command argument limit")
    middle = len(names) // 2
    return name_patterns(names[:middle], max_bytes) + name_patterns(names[middle:], max_bytes)


def run(backend: Path, tag: str, partition: str) -> None:
    base = ["go", "test", f"-tags={tag}"]
    if partition == "packages":
        packages = subprocess.check_output(
            ["go", "list", f"-tags={tag}", "./..."], cwd=backend, text=True,
        ).splitlines()
        if SERVICE not in packages:
            raise ValueError("upstream service package moved; update test partitioning")
        selected = [package for package in packages if package != SERVICE]
        if not selected:
            raise ValueError("no packages selected")
        commands = [[*base, *selected]]
    else:
        index = int(partition.removeprefix("service-"))
        listing = subprocess.check_output(
            [*base, "-list", ".", SERVICE], cwd=backend, text=True,
        )
        names = [line for line in listing.splitlines() if TEST_NAME.fullmatch(line)]
        if not names or len(names) != len(set(names)):
            raise ValueError("missing or duplicate service tests in go test -list output")
        selected = shard_names(names, index)
        if not selected:
            raise ValueError("empty service shard; update test partitioning")
        print(f"Service shard {index + 1}/{SERVICE_SHARDS}: {len(selected)}/{len(names)} targets", flush=True)
        # Anchoring the complete top-level name keeps all its subtests together.
        commands = [[*base, "-run", pattern, SERVICE] for pattern in name_patterns(selected)]
    print(f"Running {tag} / {partition}", flush=True)
    for command in commands:
        subprocess.run(command, cwd=backend, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, type=Path)
    parser.add_argument("--tag", required=True, choices=("unit", "integration"))
    parser.add_argument("--partition", required=True,
                        choices=("packages", *(f"service-{i}" for i in range(SERVICE_SHARDS))))
    args = parser.parse_args()
    try:
        run(args.backend.resolve(), args.tag, args.partition)
    except subprocess.CalledProcessError as error:
        if error.output:
            print(error.output, flush=True)
        # Avoid dumping a 100 KiB test-name expression into a failure traceback.
        raise SystemExit(f"Go {args.tag} / {args.partition} failed (exit {error.returncode})") from None


if __name__ == "__main__":
    main()
