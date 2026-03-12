#!/usr/bin/env python3
"""Scan TIProjectTemplate.json starting at a marker and count effect occurrences.

Usage:
  python3 scripts/scan_effects.py --file Mods/TIProjectTemplate.json

The script finds the first occurrence of the marker:
  "dataName": "Project_Asteroid_Claim"
and scans from there to the end of the file for all "effects" arrays,
collects effect string values and prints counts.
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path


def parse_effects_template(path: Path):
    text = path.read_text(encoding="utf-8")
    # Try to parse as JSON first
    try:
        data = json.loads(text)
        mapping = {}
        if isinstance(data, list):
            for obj in data:
                name = obj.get("dataName")
                if not name:
                    continue
                contexts = obj.get("contexts")
                value = obj.get("value")
                mapping[name] = {"contexts": contexts, "value": value}
            return mapping
    except Exception:
        pass

    # Fallback: regex parse objects and extract fields
    mapping = {}
    obj_pattern = re.compile(r"\{(.*?)\}\s*,?", re.DOTALL)
    for m in obj_pattern.finditer(text):
        obj_text = m.group(1)
        dn = re.search(r'"dataName"\s*:\s*"([^"\\]*)"', obj_text)
        if not dn:
            continue
        name = dn.group(1)
        ctxm = re.search(r'"contexts"\s*:\s*\[\s*(.*?)\s*\]', obj_text, re.DOTALL)
        contexts = None
        if ctxm:
            inner = ctxm.group(1)
            contexts = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', inner)
        vm = re.search(r'"value"\s*:\s*([-+]?[0-9]*\.?[0-9]+)', obj_text)
        value = None
        if vm:
            sval = vm.group(1)
            try:
                if "." in sval:
                    value = float(sval)
                else:
                    value = int(sval)
            except Exception:
                value = None
        mapping[name] = {"contexts": contexts, "value": value}
    return mapping


def scan_effects(path: Path, marker: str, effects_template: Path):
    text = path.read_text(encoding="utf-8")
    idx = text.find(marker)
    if idx == -1:
        print(f"Marker not found: {marker}")
        return 2

    sub = text[idx:]

    # Find all occurrences of "effects": [ ... ] (non-greedy, DOTALL)
    pattern = re.compile(r'"effects"\s*:\s*\[\s*(.*?)\s*\]', re.DOTALL)
    counter = collections.Counter()

    for m in pattern.finditer(sub):
        inner = m.group(1)
        # capture all double-quoted strings inside the array
        items = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', inner)
        for it in items:
            counter[it] += 1

    if not counter:
        print("No effects found after marker.")
        return 0

    total = sum(counter.values())
    print(f"Found {len(counter)} unique effects, {total} total occurrences:\n")
    for name, cnt in counter.most_common():
        print(f"{cnt:4d}  {name}")

    # Parse effects template and aggregate by contexts
    if effects_template and effects_template.exists():
        mapping = parse_effects_template(effects_template)
        context_sums = collections.Counter()
        missing = []
        no_context = []
        no_value = []

        for name, cnt in counter.items():
            info = mapping.get(name)
            if not info:
                missing.append(name)
                continue
            contexts = info.get("contexts")
            value = info.get("value")
            if not contexts:
                no_context.append(name)
                continue
            if value is None:
                no_value.append(name)
                # treat as zero for sum
                continue
            for c in contexts:
                try:
                    context_sums[c] += value * cnt
                except Exception:
                    pass

        print("\nContext sums:")
        if context_sums:
            for ctx, s in context_sums.most_common():
                # print as int when whole number
                if isinstance(s, float) and s.is_integer():
                    s = int(s)
                print(f"{s:8}  {ctx}")
        else:
            print("(no context sums computed)")

        if missing:
            print(f"\nEffects not found in template: {len(missing)} (first 10): {missing[:10]}")
        if no_context:
            print(f"Effects with no contexts: {len(no_context)} (first 10): {no_context[:10]}")
        if no_value:
            print(f"Effects with contexts but no value: {len(no_value)} (first 10): {no_value[:10]}")

    else:
        print(f"\nEffects template file not found: {effects_template}")

    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Scan TIProjectTemplate.json for effects")
    p.add_argument(
        "--file",
        "-f",
        default="Mods/TIProjectTemplate.json",
        help="path to TIProjectTemplate.json (relative to workspace root)",
    )
    p.add_argument(
        "--marker", "-m", default='"dataName": "Project_Asteroid_Claim"', help="marker to start scanning from"
    )
    p.add_argument(
        "--effects-file",
        "-e",
        default="/home/martin/Games/TerraInvicta/templates/TIEffectTemplate.json",
        help="path to TIEffectTemplate.json",
    )
    args = p.parse_args(argv)

    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    effects_path = Path(args.effects_file)
    return scan_effects(path, args.marker, effects_path)


if __name__ == "__main__":
    raise SystemExit(main())
