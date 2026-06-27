#!/usr/bin/env python3
"""Consolidate MCFreeSpaceMineNetwork and HumanLifespan projects.

MCFreeSpaceMineNetwork: 77 projects -> 24 projects, ~302 total
  - Keep 6 multi-effect MiningTechniques/Rush projects (28 value)
  - Keep 18 single-effect projects with upgraded effects (274 value)
  - Delete 53 single-effect projects

HumanLifespan: 42 projects -> 7 projects, 390 total
  - Delete 4 LifeExtension05 projects (only add 0.5 years each = 6 months)
  - Keep 7 LifeExtension10 projects with upgraded effects (390 total)
  - Delete 31 LifeExtension10 projects
"""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
EFFECTS_FILE = BASE / "Mods" / "TIEffectTemplate.json"
PROJECTS_FILE = BASE / "Mods" / "TIProjectTemplate.json"
LOCALIZATION_FILE = BASE / "Mods" / "Localization" / "en" / "TIProjectTemplate.en"
GAME_EFFECTS = BASE / "Game-ModsDir" / "TIEffectTemplate.json"

# === MC projects to KEEP (18 single-effect) ===
MC_KEEP = {
    "Project_Claimstrands": 12,
    "Project_Orbital_Harvest_Bounty": 12,
    "Project_Scatterseed_Protocol": 12,
    "Project_Miner_s_Bounty": 12,
    "Project_Scattershot_Deployment": 12,
    "Project_Celestial_Bounty_Harvest": 12,
    "Project_Stardust_Bloom": 15,
    "Project_Prospector_s_Claim": 15,
    "Project_Gravitic_Minefields": 15,
    "Project_Claim_Prospect": 15,
    "Project_Abundant_Harvest": 15,
    "Project_Asteroid_Abundance": 15,
    "Project_Minefield_Surveyor": 18,
    "Project_Celestial_Harvest": 18,
    "Project_Resource_Windfall": 18,
    "Project_Voidbloom": 18,
    "Project_Harvesting_Beacon": 20,
    "Project_Claim_Bounty": 20,
}

# === HL projects to KEEP (7) ===
HL_KEEP = {
    "Project_Vitae_Prolongation": 45,
    "Project_Longspan_Initiative": 55,
    "Project_Nebula_Forges": 55,
    "Project_Chronos_Bloom": 55,
    "Project_Sustained_Vitality": 60,
    "Project_Chrono_Vitality_Studies": 60,
    "Project_Genesis_Bloom": 60,
}


def load_effect_definitions():
    defs = {}
    for path in [GAME_EFFECTS, EFFECTS_FILE]:
        data = json.load(open(path))
        for eff in data:
            defs[eff["dataName"]] = eff
    return defs


def is_mc_project(proj, defs):
    for eff_name in proj.get("effects", []):
        eff_def = defs.get(eff_name, {})
        for c in eff_def.get("contexts", []):
            if c == "MCFreeSpaceMineNetwork":
                return True
    return False


def is_hl_project(proj, defs):
    for eff_name in proj.get("effects", []):
        eff_def = defs.get(eff_name, {})
        for c in eff_def.get("contexts", []):
            if c == "HumanLifespan":
                return True
    return False


def get_mc_effect(proj, defs):
    for eff_name in proj.get("effects", []):
        eff_def = defs.get(eff_name, {})
        for c in eff_def.get("contexts", []):
            if c == "MCFreeSpaceMineNetwork":
                return eff_name
    return None


def get_hl_effect(proj, defs):
    for eff_name in proj.get("effects", []):
        eff_def = defs.get(eff_name, {})
        for c in eff_def.get("contexts", []):
            if c == "HumanLifespan":
                return eff_name
    return None


def main():
    defs = load_effect_definitions()
    effects_data = json.load(open(EFFECTS_FILE))
    projects = json.load(open(PROJECTS_FILE))

    # Identify projects to delete
    delete_projects = set()

    # MC: delete single-effect projects not in keep list
    mc_multi = []
    for proj in projects:
        if is_mc_project(proj, defs):
            if proj["dataName"] in MC_KEEP:
                pass  # keep
            elif len(proj["effects"]) > 1:
                mc_multi.append(proj["dataName"])  # keep multi-effect
            else:
                delete_projects.add(proj["dataName"])

    # HL: delete all projects not in keep list
    for proj in projects:
        if is_hl_project(proj, defs):
            if proj["dataName"] not in HL_KEEP:
                delete_projects.add(proj["dataName"])

    print(f"Projects to delete: {len(delete_projects)}")
    print(f"MC multi-effect kept: {len(mc_multi)}")
    print(f"MC single-effect kept: {len(MC_KEEP)}")
    print(f"HL kept: {len(HL_KEEP)}")

    # === Step 1: Add new effect definitions ===
    mc_effect_values = {v: f"Effect_SpaceMineFreebies{v}" for v in [12, 15, 18, 20]}
    hl_effect_values = {v: f"Effect_LifeExtension{v}" for v in [45, 55, 60]}

    new_effects = []
    for val, name in mc_effect_values.items():
        new_effects.append({
            "dataName": name,
            "operation": "Additive",
            "value": val,
            "effectTarget": "SourceFaction",
            "effectDuration": "permanent",
            "stackable": True,
            "duration_months": -1,
            "contexts": ["MCFreeSpaceMineNetwork"],
        })

    for val, name in hl_effect_values.items():
        new_effects.append({
            "dataName": name,
            "operation": "Additive",
            "value": val,
            "effectTarget": "SourceFaction",
            "effectDuration": "permanent",
            "stackable": True,
            "duration_months": -1,
            "contexts": ["HumanLifespan"],
        })

    effects_data.extend(new_effects)
    print(f"\nAdded {len(new_effects)} new effect definitions")

    # === Step 2: Update kept projects with new effects ===
    for proj in projects:
        name = proj["dataName"]

        if name in MC_KEEP:
            new_val = MC_KEEP[name]
            new_eff = f"Effect_SpaceMineFreebies{new_val}"
            old_eff = get_mc_effect(proj, defs)
            proj["effects"] = [
                e for e in proj["effects"] if e != old_eff
            ]
            proj["effects"].append(new_eff)
            print(f"  MC update: {name}: {old_eff} -> {new_eff}")

        elif name in HL_KEEP:
            new_val = HL_KEEP[name]
            new_eff = f"Effect_LifeExtension{new_val}"
            old_eff = get_hl_effect(proj, defs)
            proj["effects"] = [
                e for e in proj["effects"] if e != old_eff
            ]
            proj["effects"].append(new_eff)
            print(f"  HL update: {name}: {old_eff} -> {new_eff}")

    # === Step 3: Remove deleted projects ===
    original_count = len(projects)
    projects = [p for p in projects if p["dataName"] not in delete_projects]
    print(f"\nRemoved {original_count - len(projects)} projects, {len(projects)} remaining")

    # === Step 4: Clean up localization entries ===
    lines = open(LOCALIZATION_FILE, encoding="utf-8").readlines()
    new_lines = []
    removed_loc = 0
    skip = False
    for line in lines:
        if skip:
            if "=" in line and not line.strip().startswith("#"):
                skip = False
            removed_loc += 1
            continue

        for del_name in delete_projects:
            display_key = f"TIProjectTemplate.displayName.{del_name}"
            summary_key = f"TIProjectTemplate.summary.{del_name}"
            if line.startswith(display_key + "=") or line.startswith(summary_key + "="):
                removed_loc += 1
                break
        else:
            new_lines.append(line)

    print(f"Removed {removed_loc} localization entries")

    # === Step 5: Write files ===
    json.dump(effects_data, open(EFFECTS_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(projects, open(PROJECTS_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    open(LOCALIZATION_FILE, "w", encoding="utf-8").writelines(new_lines)

    print(f"\nFiles written:")
    print(f"  {EFFECTS_FILE}")
    print(f"  {PROJECTS_FILE}")
    print(f"  {LOCALIZATION_FILE}")

    # === Step 6: Verify totals ===
    print("\n=== Verification ===")
    mc_total = sum(MC_KEEP.values()) + 28  # 6 multi-effect
    hl_total = sum(HL_KEEP.values())
    print(f"MCFreeSpaceMineNetwork: {len(MC_KEEP) + len(mc_multi)} projects, total = {mc_total}")
    print(f"HumanLifespan: {len(HL_KEEP)} projects, total = {hl_total}")


if __name__ == "__main__":
    main()
