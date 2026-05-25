#!/usr/bin/env python3
import argparse
import json
import random
import sys
from pathlib import Path

DRY_RUN = False


def walk_and_fix(obj, changes):
    if isinstance(obj, dict):
        if "factionAvailableChance" in obj:
            try:
                val = obj["factionAvailableChance"]
            except Exception:
                val = None
            if isinstance(val, (int, float)) and val >= 100:
                newv = random.randint(40, 100)
                data_name = obj.get("dataName") or obj.get("DataName") or "<unknown>"
                changes.append((data_name, int(val), newv))
                if not DRY_RUN:
                    obj["factionAvailableChance"] = newv
        for k, v in obj.items():
            walk_and_fix(v, changes)
    elif isinstance(obj, list):
        for item in obj:
            walk_and_fix(item, changes)


def main():
    p = argparse.ArgumentParser(description="Fix factionAvailableChance >=100 to random 20-100")
    p.add_argument("--dry-run", action="store_true", help="Print changes without modifying file")
    p.add_argument("file", help="Path to TIProjectTemplate.json")
    p.add_argument("--start-dataName", dest="start", help="dataName to start from (inclusive)")
    args = p.parse_args()
    global DRY_RUN
    DRY_RUN = args.dry_run

    path = Path(args.file)
    if not path.exists():
        print("File not found:", path)
        sys.exit(2)

    data = json.loads(path.read_text())
    changes = []

    if isinstance(data, list) and args.start:
        start_idx = None
        for i, item in enumerate(data):
            if isinstance(item, dict) and item.get("dataName") == args.start:
                start_idx = i
                break
        if start_idx is None:
            print(f'start dataName "{args.start}" not found in top-level list; no changes made')
            sys.exit(1)
        for item in data[start_idx:]:
            walk_and_fix(item, changes)
    else:
        # fallback: walk whole structure
        walk_and_fix(data, changes)

    if changes:
        bak = path.with_suffix(path.suffix + ".bak")
        if not DRY_RUN:
            path.rename(bak)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n")
        print(f"Updated {len(changes)} entries. Backup saved to {bak}")
        for dn, old, new in changes[:50]:
            print(f"{dn}: {old} -> {new}")
        if len(changes) > 50:
            print("...and", len(changes) - 50, "more")
    else:
        print("No entries needed changing.")


if __name__ == "__main__":
    main()
