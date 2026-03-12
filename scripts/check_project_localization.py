#!/usr/bin/env python3
"""Check Mods/TIProjectTemplate.json entries against localization file.

Usage:
  python3 scripts/check_project_localization.py
  python3 scripts/check_project_localization.py --json path/to/TIProjectTemplate.json --en path/to/TIProjectTemplate.en

Prints missing localization keys to stdout and exits with code 1 if any missing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Iterable, List, Set, Tuple


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_data_names(obj) -> List[str]:
    names: Set[str] = set()
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and "dataName" in item:
                names.add(item["dataName"])
    elif isinstance(obj, dict):
        # common patterns
        if "projects" in obj and isinstance(obj["projects"], list):
            for item in obj["projects"]:
                if isinstance(item, dict) and "dataName" in item:
                    names.add(item["dataName"])
        elif "dataName" in obj:
            names.add(obj["dataName"])
        else:
            # maybe keyed by name -> dict
            for v in obj.values():
                if isinstance(v, dict) and "dataName" in v:
                    names.add(v["dataName"])
    return sorted(names)


def load_en_keys(path: str) -> Set[str]:
    keys: Set[str] = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key = line.split("=", 1)[0].strip()
                if key:
                    keys.add(key)
    return keys


def find_missing(data_names: Iterable[str], keys: Set[str]) -> List[Tuple[str, List[str]]]:
    missing = []
    for name in data_names:
        display = f"TIProjectTemplate.displayName.{name}"
        summary = f"TIProjectTemplate.summary.{name}"
        miss = []
        if display not in keys:
            miss.append(display)
        if summary not in keys:
            miss.append(summary)
        if miss:
            missing.append((name, miss))
    return missing


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Check project localization entries")
    p.add_argument(
        "--json",
        default=os.path.join("Mods", "TIProjectTemplate.json"),
        help="Path to TIProjectTemplate.json",
    )
    p.add_argument(
        "--en",
        default=os.path.join("Mods", "Localization", "en", "TIProjectTemplate.en"),
        help="Path to TIProjectTemplate.en",
    )
    args = p.parse_args(argv)

    if not os.path.exists(args.json):
        print(f"JSON file not found: {args.json}", file=sys.stderr)
        return 2
    if not os.path.exists(args.en):
        print(f"EN file not found: {args.en}", file=sys.stderr)
        return 2

    try:
        data = load_json(args.json)
    except Exception as e:
        print(f"Failed to parse JSON {args.json}: {e}", file=sys.stderr)
        return 2

    data_names = extract_data_names(data)
    if not data_names:
        print("No dataName entries found in the JSON.")
        return 0

    keys = load_en_keys(args.en)
    missing = find_missing(data_names, keys)

    if missing:
        for name, miss_keys in missing:
            for k in miss_keys:
                print(f"Missing: {k}")
        return 1

    print("All dataName entries have displayName and summary localization entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
