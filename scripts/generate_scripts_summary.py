#!/usr/bin/env python3
"""Generate a one-line summary for each script in the scripts/ directory.

Scans the specified directory (default: `scripts/`) for top-level Python
scripts and (best-effort) extracts a short description from the module
docstring or leading comment block. Outputs a Markdown or plain text list to
stdout or writes to a file when `--write` is provided.

This tool intentionally does not modify README.md by default; use `--write`
to save the generated snippet to a file you control.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path
from typing import List, Optional


def extract_description(path: Path) -> Optional[str]:
    """Return a short description for a Python file by reading its header.

    Strategy:
    - Prefer a module-level triple-quoted docstring (first docstring in file).
    - Otherwise, collect the top contiguous block of `#` comments and use
      that as the description.
    - Return None if nothing useful is found.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    # Prefer a proper module docstring using the AST (handles shebangs/comments)
    try:
        module = ast.parse(text)
        doc = ast.get_docstring(module)
    except Exception:
        doc = None
    if doc:
        # take first line or sentence
        first_line = doc.splitlines()[0].strip()
        # prefer up to first sentence-ending punctuation
        sent = re.split(r"[\.\!\?]\s+", first_line)[0].strip()
        return sent

    # Fallback: leading block comments
    lines = text.splitlines()
    comments: List[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            # stop on first blank line (only consider leading block)
            break
        # ignore a shebang (#!/usr/bin/env python3) when collecting comments
        if s.startswith("#!"):
            continue
        if s.startswith("#"):
            comments.append(s.lstrip("# "))
        else:
            break
    if comments:
        first = comments[0].strip()
        # clean up and shorten
        first = re.sub(r"\s+", " ", first)
        sent = re.split(r"[\.\!\?]\s+", first)[0].strip()
        return sent

    return None


def generate_list(
    dir_path: Path, pattern: str = "*.py", recursive: bool = False
) -> List[str]:
    files: List[Path] = []
    if recursive:
        files = [p for p in dir_path.rglob(pattern) if p.is_file()]
    else:
        files = [p for p in dir_path.glob(pattern) if p.is_file()]

    # Exclude common internal folders and this generator itself
    ignore_names = {"__init__.py", "logs", "storage", "utils"}
    out: List[str] = []
    for p in sorted(files):
        # skip files in ignored subdirs
        parts = set(p.parts)
        if parts & ignore_names:
            continue
        # skip this script
        if p.name == Path(__file__).name:
            continue
        desc = extract_description(p)
        if not desc:
            desc = "(no top-level docstring or leading comment)"
        out.append(f"- `{p.as_posix()}`: {desc}")
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Generate one-line summaries for scripts/")
    p.add_argument(
        "--dir", default="scripts", help="Directory to scan (default: scripts)"
    )
    p.add_argument("--write", help="Write output to this file instead of stdout")
    p.add_argument(
        "--format",
        choices=("md", "text"),
        default="md",
        help="Output format (md or text)",
    )
    p.add_argument("--recursive", action="store_true", help="Scan recursively")
    args = p.parse_args()

    dir_path = Path(args.dir)
    if not dir_path.exists() or not dir_path.is_dir():
        print(f"Error: directory not found: {dir_path}")
        return 2

    items = generate_list(dir_path, pattern="*.py", recursive=args.recursive)
    if args.format == "md":
        header = "Other helpful scripts (generated):\n"
        body = header + "\n".join(items) + "\n"
    else:
        body = "\n".join(items) + "\n"

    if args.write:
        out_path = Path(args.write)
        out_path.write_text(body, encoding="utf-8")
        print(f"Wrote summary to: {out_path}")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
