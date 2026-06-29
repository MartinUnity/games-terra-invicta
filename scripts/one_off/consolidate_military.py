#!/usr/bin/env python3
"""Consolidate MilitaryPriority: 68 projects -> 40, 340% -> 400%.

15 x 5% + 10 x 10% + 15 x 15% = 400%, 40 projects.
Creates Effect_MilitaryPriorityBonus10 and Effect_MilitaryPriorityBonus15.
"""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
EFFECTS_FILE = BASE / "Mods" / "TIEffectTemplate.json"
PROJECTS_FILE = BASE / "Mods" / "TIProjectTemplate.json"
LOCALIZATION_FILE = BASE / "Mods" / "Localization" / "en" / "TIProjectTemplate.en"
GAME_EFFECTS = BASE / "Game-ModsDir" / "TIEffectTemplate.json"


def load_effect_definitions():
    defs = {}
    for path in [GAME_EFFECTS, EFFECTS_FILE]:
        data = json.load(open(path))
        for eff in data:
            defs[eff["dataName"]] = eff
    return defs


def main():
    defs = load_effect_definitions()
    effects_data = json.load(open(EFFECTS_FILE))
    projects = json.load(open(PROJECTS_FILE))

    # Get all MilitaryPriority projects sorted by cost
    mil = []
    for proj in projects:
        for eff_name in proj.get("effects", []):
            eff_def = defs.get(eff_name, {})
            if "MilitaryPriority" in eff_def.get("contexts", []):
                mil.append(proj)
                break
    mil.sort(key=lambda x: x["researchCost"])
    n = len(mil)

    # Select 40: first 15 (lowest cost), then every other from 15 onward to fill remaining 25
    keep_indices = list(range(15))
    for i in range(15, n, 2):
        if len(keep_indices) >= 40:
            break
        keep_indices.append(i)

    # Trim/extend to exactly 40
    keep_indices = keep_indices[:40]

    # Assign tiers: first 15 -> 5%, next 10 -> 10%, last 15 -> 15%
    tier_map = {}
    for pos, idx in enumerate(keep_indices):
        if pos < 15:
            tier = 5
        elif pos < 25:
            tier = 10
        else:
            tier = 15
        tier_map[mil[idx]["dataName"]] = tier

    delete_projects = set(p["dataName"] for p in mil if p["dataName"] not in tier_map)

    print(f"Keep: {len(tier_map)}, Delete: {len(delete_projects)}")
    count_5 = sum(1 for v in tier_map.values() if v == 5)
    count_10 = sum(1 for v in tier_map.values() if v == 10)
    count_15 = sum(1 for v in tier_map.values() if v == 15)
    print(f"  5%: {count_5}, 10%: {count_10}, 15%: {count_15}")
    print(f"  Total: {count_5*5 + count_10*10 + count_15*15}%")

    # === Step 1: Add new effect definitions ===
    new_effects = []
    for val in [10, 15]:
        new_effects.append({
            "dataName": f"Effect_MilitaryPriorityBonus{val:02d}",
            "operation": "Additive",
            "value": val / 100.0,
            "effectTarget": "SourceFaction",
            "effectDuration": "permanent",
            "stackable": True,
            "duration_months": -1,
            "contexts": ["MilitaryPriority"],
        })
    effects_data.extend(new_effects)
    print(f"\nAdded {len(new_effects)} new effect definitions")

    # === Step 2: Update kept projects ===
    for proj in projects:
        name = proj["dataName"]
        if name in tier_map:
            new_val = tier_map[name]
            new_eff = f"Effect_MilitaryPriorityBonus{new_val:02d}"
            old_eff = "Effect_MilitaryPriorityBonus05"
            proj["effects"] = [e for e in proj["effects"] if e != old_eff]
            proj["effects"].append(new_eff)

    # === Step 3: Remove deleted projects ===
    original_count = len(projects)
    projects = [p for p in projects if p["dataName"] not in delete_projects]
    print(f"Removed {original_count - len(projects)} projects, {len(projects)} remaining")

    # === Step 4: Clean up localization ===
    lines = open(LOCALIZATION_FILE, encoding="utf-8").readlines()
    new_lines = []
    removed_loc = 0
    for line in lines:
        skip = False
        for del_name in delete_projects:
            display_key = f"TIProjectTemplate.displayName.{del_name}"
            summary_key = f"TIProjectTemplate.summary.{del_name}"
            if line.startswith(display_key + "=") or line.startswith(summary_key + "="):
                removed_loc += 1
                skip = True
                break
        if not skip:
            new_lines.append(line)

    print(f"Removed {removed_loc} localization entries")

    # === Step 5: Write files ===
    json.dump(effects_data, open(EFFECTS_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(projects, open(PROJECTS_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    open(LOCALIZATION_FILE, "w", encoding="utf-8").writelines(new_lines)

    print(f"\nDone. MilitaryPriority: {len(tier_map)} projects, {count_5*5 + count_10*10 + count_15*15}%")


if __name__ == "__main__":
    main()
