#!/usr/bin/env python3
"""Reuse the known upstream build typecheck; preserve explicit checks on drift."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess


# This exact combination checks the same source project with vue-tsc -b,
# including its referenced Vite config, and retains i18n and Vite's checker.
CHECKED_TYPECHECK = "vue-tsc --noEmit"
CHECKED_BUILD = "pnpm run check:i18n && vue-tsc -b && vite build"


def build(frontend: Path) -> None:
    scripts = json.loads((frontend / "package.json").read_text())["scripts"]
    if (scripts.get("typecheck"), scripts.get("build")) == (CHECKED_TYPECHECK, CHECKED_BUILD):
        print("Typecheck is included in the verified upstream production build", flush=True)
    else:
        print("Upstream scripts changed: preserving the separate typecheck", flush=True)
        subprocess.run(["pnpm", "run", "typecheck"], cwd=frontend, check=True)
    # Keep the entire upstream command, including all current and future checks.
    subprocess.run(["pnpm", "run", "build"], cwd=frontend, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", required=True, type=Path)
    args = parser.parse_args()
    build(args.frontend.resolve())


if __name__ == "__main__":
    main()
