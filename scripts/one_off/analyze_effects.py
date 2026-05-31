#!/usr/bin/env python3
"""
Phase 2: Analyze distribution of effects across all projects in TIProjectTemplate.json.
Produces per-effect counts, cumulative percentages, and category totals.
"""

import json
import re
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
TEMPLATE_FILE = BASE / "Mods" / "TIProjectTemplate.json"
EFFECTS_FILE = BASE / "project_effects.txt"


def load_effects(path: Path) -> set[str]:
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def parse_value(effect: str) -> int:
    m = re.search(r"(\d+)$", effect)
    if not m:
        return 0
    num = int(m.group(1))
    # Trailing "1" (not "10") means 10%
    if num == 1:
        return 10
    return num


def parse_category(effect: str) -> str:
    # Strip "Effect_" prefix
    name = effect[len("Effect_"):]
    # Strip known suffixes to find the category word
    # e.g. "EconomyPriorityBonus05" -> "Economy"
    # e.g. "ControlPointMaintenanceBonus10" -> "ControlPointMaintenance"
    # e.g. "EconomyPriorityGlobalBonus10" -> "Economy"
    # e.g. "LifeExtension05" -> "LifeExtension"
    # e.g. "SpoilsPriorityGlobalBonus10" -> "Spoils"

    # Remove trailing digits
    name = re.sub(r"\d+$", "", name)
    # Remove known suffixes
    for suffix in ["PriorityBonus", "PriorityGlobalBonus", "Priority", "Bonus"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def main() -> None:
    tracked = load_effects(EFFECTS_FILE)

    with open(TEMPLATE_FILE, "r") as f:
        projects = json.load(f)

    # effect_name -> [count, cumulative_value]
    counts: dict[str, int] = defaultdict(int)
    cumul: dict[str, int] = defaultdict(int)

    for proj in projects:
        proj_effects = proj.get("effects", [])
        for eff in proj_effects:
            if eff in tracked:
                counts[eff] += 1
                cumul[eff] += parse_value(eff)

    if not counts:
        print("No tracked effects found in projects.")
        return

    # Per-effect table
    print(f"{'Effect':<55} {'Count':>5} | {'Total %':>7}")
    print("-" * 69)
    for eff in sorted(counts):
        print(f"{eff:<55} {counts[eff]:>5} | {cumul[eff]:>6}%")

    # Category totals
    cat_counts: dict[str, int] = defaultdict(int)
    cat_cumul: dict[str, int] = defaultdict(int)
    for eff in counts:
        cat = parse_category(eff)
        cat_counts[cat] += counts[eff]
        cat_cumul[cat] += cumul[eff]

    print()
    print(f"{'Category':<30} {'Projects':>8} | {'Total %':>7}")
    print("-" * 47)
    for cat in sorted(cat_counts):
        print(f"{cat:<30} {cat_counts[cat]:>8} | {cat_cumul[cat]:>6}%")

    grand_total = sum(cat_cumul.values())
    print(f"\nGrand total across all categories: {grand_total}%")


if __name__ == "__main__":
    main()
