#!/usr/bin/env python3
"""
Scans TIProjectTemplate.json for projects whose effects match update_effects.txt.
If researchCost >= 5000, reduces it to a random value in [500, 4000].
"""

import json
import random
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
EFFECTS_FILE = BASE / "update_effects.txt"
TEMPLATE_FILE = BASE / "Mods" / "TIProjectTemplate.json"

COST_MIN = 500
COST_MAX = 4000
COST_THRESHOLD = 5000

OUTLIER_THRESHOLD = 500_000
OUTLIER_MIN = 150_000
OUTLIER_MAX = 450_000


def load_effects(path: Path) -> set[str]:
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def main() -> None:
    effects = load_effects(EFFECTS_FILE)
    print(f"Effects to match: {effects}")

    with open(TEMPLATE_FILE, "r") as f:
        projects = json.load(f)

    random.seed(42)  # Reproducible results
    changed: list[tuple[str, int, int]] = []

    for proj in projects:
        proj_effects = proj.get("effects", [])
        if effects.intersection(proj_effects):
            old_cost = proj.get("researchCost", 0)
            if old_cost >= COST_THRESHOLD:
                new_cost = random.randint(COST_MIN, COST_MAX)
                proj["researchCost"] = new_cost
                name = proj.get("dataName", proj.get("friendlyName", "?"))
                changed.append((name, old_cost, new_cost))
                matched = effects.intersection(proj_effects)
                print(f"  {name}: {old_cost} -> {new_cost}  (matched {matched})")

    print(f"\nTotal effect-matched changes: {len(changed)}")

    random.seed(99)
    outlier_changed: list[tuple[str, int, int]] = []
    for proj in projects:
        old_cost = proj.get("researchCost", 0)
        if old_cost >= OUTLIER_THRESHOLD:
            new_cost = random.randint(OUTLIER_MIN, OUTLIER_MAX)
            proj["researchCost"] = new_cost
            name = proj.get("dataName", proj.get("friendlyName", "?"))
            outlier_changed.append((name, old_cost, new_cost))
            print(f"  OUTLIER {name}: {old_cost} -> {new_cost}")

    print(f"\nTotal outlier fixes: {len(outlier_changed)}")
    answer = input("Apply changes to TIProjectTemplate.json? [y/N] ")
    if answer.lower() != "y":
        print("Aborted.")
        return

    with open(TEMPLATE_FILE, "w") as f:
        json.dump(projects, f, indent=2)

    print(f"Wrote {len(changed) + len(outlier_changed)} changes to {TEMPLATE_FILE}")


if __name__ == "__main__":
    main()
