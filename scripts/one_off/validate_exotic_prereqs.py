#!/usr/bin/env python3
"""Validate that all items using exotics have Project_Exotics (or inheritor) in their prereq chain.

Scans all template files in Mods/ for items with exotics > 0 in weightedBuildMaterials,
then traces the prerequisite chain of each item's requiredProjectName through both
our mod's projects/tech and the base game's projects/tech.

Reports any item whose project lacks Project_Exotics in its prerequisite chain.

By default only checks OUR mod items. Use --include-game to also scan base game items
(these will mostly be false-positives: alien items are gated by objectives, not prereqs).
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
MODS_DIR = ROOT / "Mods"
GAME_MODS_DIR = ROOT / "Game-ModsDir"

# Template files containing weightedBuildMaterials with exotics
TEMPLATE_FILES = [
    "TIDriveTemplate.json",
    "TIGunTemplate.json",
    "TIMagneticGunTemplate.json",
    "TIMissileTemplate.json",
    "TILaserWeaponTemplate.json",
    "TIParticleWeaponTemplate.json",
    "TIPlasmaWeaponTemplate.json",
    "TIShipArmorTemplate.json",
    "TIShipHullTemplate.json",
    "TIRadiatorTemplate.json",
    "TIHeatSinkTemplate.json",
    "TIHabModuleTemplate.json",
    "TIPowerPlantTemplate.json",
    "TIBatteryTemplate.json",
    "TIUtilityModuleTemplate.json",
]

# The root exotic-tech that must appear somewhere in the prereq chain
ROOT_EXOTIC_PREREQ = "Project_Exotics"


def load_json(path: Path) -> Any:
    """Load and return JSON from path."""
    with open(path) as f:
        return json.load(f)


def build_tech_map(mods_dir: Path, game_mods_dir: Path) -> dict[str, list[str]]:
    """Build map of all project/tech dataName -> prereqs from our mod + base game.

    Loads base game first, then mod on top, so mod entries override base game.
    """
    tech_map: dict[str, list[str]] = {}

    for source_dir in (game_mods_dir, mods_dir):
        if not source_dir.exists():
            continue
        for fname in ("TIProjectTemplate.json", "TITechTemplate.json"):
            fpath = source_dir / fname
            if not fpath.exists():
                continue
            try:
                entries = load_json(fpath)
            except (json.JSONDecodeError, FileNotFoundError):
                continue
            for entry in entries:
                dn = entry.get("dataName", "")
                prereqs = entry.get("prereqs", [])
                if dn:
                    tech_map[dn] = prereqs

    return tech_map


def get_all_prereqs(
    proj_name: str,
    tech_map: dict[str, list[str]],
    visited: set[str] | None = None,
) -> set[str]:
    """Recursively collect all prerequisites (direct + inherited) for a project."""
    if visited is None:
        visited = set()
    if proj_name in visited:
        return set()
    visited.add(proj_name)
    prereqs = tech_map.get(proj_name, [])
    all_prereqs = set(prereqs)
    for pr in prereqs:
        all_prereqs |= get_all_prereqs(pr, tech_map, visited)
    return all_prereqs


def find_exotic_items(
    mods_dir: Path,
    game_mods_dir: Path,
    include_game: bool = False,
) -> list[dict[str, Any]]:
    """Find all items in template files that use exotics > 0."""
    exotic_items: list[dict[str, Any]] = []
    dirs_to_scan = [mods_dir]
    if include_game:
        dirs_to_scan.append(game_mods_dir)

    for source_dir in dirs_to_scan:
        if not source_dir.exists():
            continue
        for fname in TEMPLATE_FILES:
            fpath = source_dir / fname
            if not fpath.exists():
                continue
            try:
                entries = load_json(fpath)
            except (json.JSONDecodeError, FileNotFoundError):
                continue
            for entry in entries:
                materials = entry.get("weightedBuildMaterials", {})
                if not isinstance(materials, dict):
                    continue
                exotic_val = materials.get("exotics", 0)
                if exotic_val > 0:
                    exotic_items.append({
                        "source": "mod" if source_dir == mods_dir else "game",
                        "file": fname,
                        "name": entry.get("dataName", entry.get("friendlyName", "?")),
                        "exotics": exotic_val,
                        "requiredProject": entry.get("requiredProjectName", "N/A"),
                    })

    return exotic_items


def check_exotic_prereqs(
    items: list[dict[str, Any]],
    tech_map: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Check each exotic item's project for valid exotic prereq chain.

    Returns list of items that FAIL the check.
    """
    failures: list[dict[str, Any]] = []

    for item in items:
        proj = item["requiredProject"]
        if proj == "N/A":
            failures.append({**item, "reason": "No requiredProjectName set"})
            continue

        all_prereqs = get_all_prereqs(proj, tech_map)
        has_root = ROOT_EXOTIC_PREREQ in all_prereqs

        if not has_root:
            failures.append({
                **item,
                "reason": f"Missing {ROOT_EXOTIC_PREREQ} in prereq chain",
                "all_prereqs": sorted(all_prereqs),
                "direct_prereqs": tech_map.get(proj, []),
            })

    return failures


def print_report(failures: list[dict[str, Any]], total: int) -> int:
    """Print the validation report. Return exit code."""
    if not failures:
        print(
            f"OK - all {total} items using exotics have valid prereq chain "
            f"to {ROOT_EXOTIC_PREREQ}."
        )
        return 0

    print(
        f"FAIL - {len(failures)}/{total} items using exotics are missing "
        f"{ROOT_EXOTIC_PREREQ} in prereq chain:\n"
    )

    # Group by required project
    by_project: dict[str, list[dict[str, Any]]] = {}
    for f in failures:
        proj = f["requiredProject"]
        by_project.setdefault(proj, []).append(f)

    for proj, items in sorted(by_project.items()):
        first = items[0]
        print(f"  Project: {proj}  [{first['source']}/{first['file']}]")
        print(f"    Reason: {first['reason']}")
        if "direct_prereqs" in first:
            print(f"    Direct prereqs: {first['direct_prereqs']}")
        print(f"    Items ({len(items)}):")
        for item in items:
            print(f"      - {item['name']} (exotics={item['exotics']})")
        print()

    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate exotic material prerequisites in mod templates."
    )
    parser.add_argument(
        "--include-game",
        action="store_true",
        help="Also scan base game items (usually false positives - gated by objectives)",
    )
    args = parser.parse_args()

    tech_map = build_tech_map(MODS_DIR, GAME_MODS_DIR)
    items = find_exotic_items(MODS_DIR, GAME_MODS_DIR, include_game=args.include_game)
    failures = check_exotic_prereqs(items, tech_map)
    return print_report(failures, len(items))


if __name__ == "__main__":
    sys.exit(main())
