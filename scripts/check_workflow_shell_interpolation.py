#!/usr/bin/env python3
"""Reject unsafe GitHub expression interpolation inside shell scripts.

GitHub expands `${{ ... }}` expressions before the selected shell parses a
`run:` block. Secrets and workflow-dispatch inputs therefore must cross the
shell boundary through `env:` rather than being embedded in script source.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WORKFLOW_DIR = Path(".github/workflows")
FORBIDDEN = re.compile(r"\$\{\{\s*(?:secrets|inputs)\.", re.IGNORECASE)
RUN_LINE = re.compile(r"^(?P<indent>\s*)run:\s*(?P<body>.*)$")


def scan_workflow(path: Path) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    findings: list[tuple[int, str]] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        match = RUN_LINE.match(line)
        if not match:
            index += 1
            continue

        indent = len(match.group("indent"))
        body = match.group("body").strip()

        # One-line form: `run: command ...`.
        if body and not body.startswith(("|", ">")):
            if FORBIDDEN.search(body):
                findings.append((index + 1, line.strip()))
            index += 1
            continue

        # Block scalar form. Blank lines belong to the block; a non-blank line
        # at the same or lower indentation ends it.
        index += 1
        while index < len(lines):
            block_line = lines[index]
            stripped = block_line.lstrip()
            block_indent = len(block_line) - len(stripped)
            if stripped and block_indent <= indent:
                break
            if FORBIDDEN.search(block_line):
                findings.append((index + 1, stripped))
            index += 1

    return findings


def main() -> int:
    failed = False
    for path in sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")]):
        for line_no, excerpt in scan_workflow(path):
            failed = True
            print(
                f"{path}:{line_no}: unsafe GitHub expression interpolation in run block: {excerpt}",
                file=sys.stderr,
            )

    if failed:
        print(
            "Pass secrets/workflow inputs through step-level env: and reference the environment variable from the script.",
            file=sys.stderr,
        )
        return 1

    print("Workflow shell interpolation check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
