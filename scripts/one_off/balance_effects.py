#!/usr/bin/env python3
"""
Phase 2b: Balance effect category totals into the 400-700% range.

For categories below 400%, bumps effects to the next available tier.
Each point increase raises researchCost by random(5%, 15%) per point.
"""

import json
import random
import re
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
TEMPLATE_FILE = BASE / "Mods" / "TIProjectTemplate.json"
EFFECTS_FILE = BASE / "project_effects.txt"

TARGET_MIN = 400
TARGET_MAX = 700
TARGET_MID = (TARGET_MIN + TARGET_MAX) // 2  # 550

SKIP_CATEGORIES = {"ControlPointMaintenance", "Spoils"}

PCT_MIN = 5
PCT_MAX = 15


def load_effects(path: Path) -> set[str]:
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def parse_value(effect: str) -> int:
    m = re.search(r"(\d+)$", effect)
    if not m:
        return 0
    num = int(m.group(1))
    return 10 if num == 1 else num


def parse_category(effect: str) -> str:
    name = effect[len("Effect_"):]
    name = re.sub(r"\d+$", "", name)
    for suffix in ["PriorityBonus", "PriorityGlobalBonus", "Priority", "Bonus"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def build_tier_ladder(tracked: set[str]) -> dict[str, list[str]]:
    """Build ordered tier ladder per category, e.g. Economy: [02, 05, 1, GlobalBonus10]."""
    cats: dict[str, list[str]] = defaultdict(list)
    for eff in sorted(tracked, key=lambda e: parse_value(e)):
        cats[parse_category(eff)].append(eff)
    return cats


def next_tier(current_effect: str, ladder: dict[str, list[str]]) -> str | None:
    cat = parse_category(current_effect)
    ladder_list = ladder.get(cat, [])
    for i, eff in enumerate(ladder_list):
        if eff == current_effect and i + 1 < len(ladder_list):
            return ladder_list[i + 1]
    return None


def main() -> None:
    tracked = load_effects(EFFECTS_FILE)
    ladders = build_tier_ladder(tracked)

    with open(TEMPLATE_FILE, "r") as f:
        projects = json.load(f)

    # Current state
    cat_cumul: dict[str, int] = defaultdict(int)
    project_effects: list[tuple[int, str]] = []  # (project_idx, effect_name)
    for idx, proj in enumerate(projects):
        for eff in proj.get("effects", []):
            if eff in tracked:
                cat_cumul[parse_category(eff)] += parse_value(eff)
                project_effects.append((idx, eff))

    print(f"{'Category':<25} {'Current %':>9}  Status")
    print("-" * 45)
    for cat in sorted(cat_cumul):
        total = cat_cumul[cat]
        status = "OK" if TARGET_MIN <= total <= TARGET_MAX else f"{'LOW' if total < TARGET_MIN else 'HIGH'}"
        print(f"{cat:<25} {total:>9}%  {status}")

    before_totals = dict(cat_cumul)

    # Determine per-category deficit
    deficits: dict[str, int] = {}
    for cat in cat_cumul:
        if cat not in SKIP_CATEGORIES and cat_cumul[cat] < TARGET_MIN:
            deficits[cat] = TARGET_MIN - cat_cumul[cat]

    if not deficits:
        print("\nAll categories within target range. Nothing to do.")
        return

    # Find upgradeable projects per category
    random.seed(77)
    changes: list[tuple[str, str, str, int, int, int]] = []
    # (dataName, old_effect, new_effect, points_gained, old_cost, new_cost)

    for cat, deficit in sorted(deficits.items()):
        ladder_list = ladders.get(cat, [])
        if len(ladder_list) < 2:
            print(f"\n  {cat}: deficit {deficit}%, but only 1 tier available. Skipping.")
            continue

        # Collect candidates: projects with non-max tier effects in this category
        candidates = []
        for idx, eff in project_effects:
            if parse_category(eff) == cat:
                nxt = next_tier(eff, ladders)
                if nxt:
                    gain = parse_value(nxt) - parse_value(eff)
                    candidates.append((idx, eff, nxt, gain))

        random.shuffle(candidates)

        gained = 0
        for idx, old_eff, new_eff, gain in candidates:
            if gained >= deficit:
                break
            proj = projects[idx]
            old_cost = proj["researchCost"]
            pct_increase = random.randint(PCT_MIN, PCT_MAX) * gain
            new_cost = round(old_cost * (1 + pct_increase / 100))
            proj["researchCost"] = new_cost

            # Replace effect
            effects_list = proj["effects"]
            for j, e in enumerate(effects_list):
                if e == old_eff:
                    effects_list[j] = new_eff
                    break

            name = proj.get("dataName", proj.get("friendlyName", "?"))
            changes.append((name, old_eff, new_eff, gain, old_cost, new_cost))
            gained += gain
            print(f"  {name}: {old_eff} -> {new_eff} (+{gain}%), cost {old_cost} -> {new_cost}")

        remaining = deficit - gained
        print(f"  {cat}: gained {gained}% (remaining deficit: {remaining}%)")

    # Updated totals
    print(f"\n{'Category':<25} {'Before':>8} {'After':>8}  {'Delta':>7}")
    print("-" * 56)

    # Recompute from modified projects
    after: dict[str, int] = defaultdict(int)
    for proj in projects:
        for eff in proj.get("effects", []):
            if eff in tracked:
                after[parse_category(eff)] += parse_value(eff)

    for cat in sorted(set(list(before_totals.keys()) + list(after.keys()))):
        b = before_totals.get(cat, 0)
        a = after.get(cat, 0)
        print(f"{cat:<25} {b:>7}% {a:>7}%  {a - b:>+6}%")

    print(f"\nTotal changes: {len(changes)}")
    answer = input("Apply changes? [y/N] ")
    if answer.lower() != "y":
        print("Aborted.")
        return

    with open(TEMPLATE_FILE, "w") as f:
        json.dump(projects, f, indent=2)
    print(f"Wrote {len(changes)} changes to {TEMPLATE_FILE}")


if __name__ == "__main__":
    main()
