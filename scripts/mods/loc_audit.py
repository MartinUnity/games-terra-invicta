#!/usr/bin/env python3
"""Cross-reference mod template files against localization entries.

Finds:
- Orphan localization: entry in .en file but no matching dataName in .json
- Missing localization: dataName in .json but no matching key in .en
- Incomplete pairs: e.g., displayName exists but summary does not

Usage:
    python3 scripts/mods/loc_audit.py [--mods-dir PATH] [--apply] [--delete]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

OMIT_FILES = {"TIRegionTemplate.json"}

# Per-template: which localization key suffixes are required
LOC_REQUIREMENTS: Dict[str, List[str]] = {
    "TIProjectTemplate": ["displayName", "summary"],
    "TIShipHullTemplate": ["displayName", "abbr"],
    "TITechTemplate": ["displayName", "summary", "quote", "description"],
    "TIEffectTemplate": ["description"],
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_loc_keys(path: Path) -> Dict[str, Set[str]]:
    """Load .en file, return {dataName: set_of_key_suffixes}."""
    entries: Dict[str, Set[str]] = {}
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8") as f:
        for _ln in f:
            line = _ln.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _val = line.split("=", 1)
            key = key.strip()
            # Parse key like "TIProjectTemplate.displayName.Project_X"
            parts = key.split(".")
            if len(parts) >= 3:
                suffix = parts[1]
                data_name = ".".join(parts[2:])
                entries.setdefault(data_name, set()).add(suffix)
    return entries


def audit_file(
    fp: Path,
    mods_dir: Path,
) -> List[Tuple[str, str, str]]:
    """Return list of (issue_type, dataName, detail) tuples."""
    base = fp.stem
    issues: List[Tuple[str, str, str]] = []

    # Load template dataNames
    try:
        obj = load_json(fp)
    except Exception as e:
        issues.append(("error", "", f"Failed to parse JSON: {e}"))
        return issues

    data_names: List[str] = []
    if isinstance(obj, list):
        for itm in obj:
            if isinstance(itm, dict) and itm.get("dataName"):
                data_names.append(itm["dataName"])
    elif isinstance(obj, dict):
        if obj.get("dataName"):
            data_names.append(obj["dataName"])

    template_names = set(data_names)

    # Load localization
    loc_file = mods_dir / "Localization" / "en" / f"{base}.en"
    loc_entries = load_loc_keys(loc_file)
    loc_names = set(loc_entries.keys())

    required_keys = LOC_REQUIREMENTS.get(base, ["displayName", "description"])

    # Orphan localization: in .en but not in .json
    for dn in sorted(loc_names - template_names):
        keys_present = ", ".join(sorted(loc_entries[dn]))
        issues.append(("orphan_loc", dn, f"loc keys: {keys_present}"))

    # Missing localization: in .json but not in .en at all
    for dn in sorted(template_names - loc_names):
        issues.append(("missing_loc", dn, f"no localization entries (need: {', '.join(required_keys)})"))

    # Partial localization: dataName exists but not all required keys
    for dn in sorted(template_names & loc_names):
        has = loc_entries[dn]
        for req in required_keys:
            if req not in has:
                issues.append(
                    ("partial_loc", dn, f"has {', '.join(sorted(has))}, missing: {req}")
                )
                break

    return issues


def delete_orphan_loc(
    fp: Path,
    mods_dir: Path,
    orphan_names: Set[str],
) -> int:
    """Remove orphan localization lines from .en file. Returns lines removed."""
    base = fp.stem
    loc_file = mods_dir / "Localization" / "en" / f"{base}.en"
    if not loc_file.exists():
        return 0

    lines = loc_file.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines = []
    removed = 0
    for line in lines:
        # Check if line is a key=value for an orphan dataName
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            parts = key.split(".")
            if len(parts) >= 3:
                dn = ".".join(parts[2:])
                if dn in orphan_names:
                    removed += 1
                    continue
        new_lines.append(line)

    if removed > 0:
        loc_file.write_text("".join(new_lines), encoding="utf-8")
    return removed


def main() -> int:
    p = argparse.ArgumentParser(description="Audit mod localization vs template files")
    p.add_argument("--mods-dir", type=Path, default=None, help="Path to Mods directory")
    p.add_argument("--apply", action="store_true", help="Apply deletions (dry-run by default)")
    p.add_argument(
        "--delete",
        action="store_true",
        help="Delete orphan localization entries (implies --apply)",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Show all issues including OK files")
    args = p.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    mods_dir = args.mods_dir or repo_root / "Mods"

    if not mods_dir.exists():
        print(f"Mods directory not found: {mods_dir}")
        return 2

    all_issues: List[Tuple[str, str, Tuple[str, str, str]]] = []
    # (file, issue_type, (issue_type, dataName, detail))

    for fp in sorted(mods_dir.glob("TI*.json")):
        if fp.name in OMIT_FILES:
            continue
        issues = audit_file(fp, mods_dir)
        if issues:
            for issue in issues:
                all_issues.append((fp.name, issue[0], issue))

    # Summary
    orphan_count = sum(1 for _, t, _ in all_issues if t == "orphan_loc")
    missing_count = sum(1 for _, t, _ in all_issues if t == "missing_loc")
    partial_count = sum(1 for _, t, _ in all_issues if t == "partial_loc")
    error_count = sum(1 for _, t, _ in all_issues if t == "error")

    print(f"Total issues: {len(all_issues)}")
    print(f"  Orphan localization (loc exists, no template): {orphan_count}")
    print(f"  Missing localization (template exists, no loc): {missing_count}")
    print(f"  Partial localization (incomplete keys): {partial_count}")
    if error_count:
        print(f"  Parse errors: {error_count}")

    if not all_issues:
        print("All templates match localization. Clean.")
        return 0

    # Group by file for display
    from collections import defaultdict
    by_file: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    for fname, _, issue in all_issues:
        by_file[fname].append(issue)

    for fname in sorted(by_file):
        print(f"\n{fname}:")
        for itype, dn, detail in by_file[fname]:
            label = {
                "orphan_loc": "ORPHAN",
                "missing_loc": "MISSING",
                "partial_loc": "PARTIAL",
                "error": "ERROR",
            }.get(itype, itype)
            print(f"  [{label}] {dn}: {detail}")

    # Apply deletions
    if args.delete or args.apply:
        print()
        print("=" * 60)
        print("Deleting orphan localization entries...")
        total_removed = 0
        for fname, issues_list in by_file.items():
            fp = mods_dir / fname
            orphan_set = {
                dn for itype, dn, detail in issues_list if itype == "orphan_loc"
            }
            if orphan_set:
                removed = delete_orphan_loc(fp, mods_dir, orphan_set)
                total_removed += removed
                print(f"  {fname}: removed {removed} lines ({len(orphan_set)} orphans)")

        print(f"\nTotal localization lines removed: {total_removed}")
        return 1

    return 1 if len(all_issues) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
