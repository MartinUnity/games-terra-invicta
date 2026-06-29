#!/usr/bin/env python3
"""Reduce overabundant effects: PherocyteResistance, HabResearchProduction, ResourceMarketSales.

PherocyteResistance: 29 projects -> 15, 30 total (was 58)
  - Delete 14 single-effect projects

HabResearchProduction: 35 projects -> 20, ~38% total (was ~53%)
  - Keep all 18 value=1.02 projects + 2 value=1.01 projects
  - Delete 15 value=1.01 projects

ResourceMarketSales: 23 projects -> 10, sum=16 (was 32)
  - Keep 6 value=2 projects + 4 value=1 projects
  - Delete 13 projects
"""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
PROJECTS_FILE = BASE / "Mods" / "TIProjectTemplate.json"
LOCALIZATION_FILE = BASE / "Mods" / "Localization" / "en" / "TIProjectTemplate.en"
GAME_EFFECTS = BASE / "Game-ModsDir" / "TIEffectTemplate.json"
EFFECTS_FILE = BASE / "Mods" / "TIEffectTemplate.json"

# === PherocyteResistance: keep first 15 ===
PR_KEEP = {
    "Project_Symbiotic_Shield",
    "Project_Neural_Resilience",
    "Project_Chitinous_Resilience",
    "Project_Neural_Symbiosis",
    "Project_Chitin_Shielding",
    "Project_Xeno_Adaptation",
    "Project_Chitinous_Adaptation",
    "Project_Chitinous_Shielding",
    "Project_Pherocyte_Shielding",
    "Project_Xeno_Shield",
    "Project_Hive_Resilience",
    "Project_Neural_Adaptation",
    "Project_Chitinous_Shield",
    "Project_Symbiotic_Shielding",
    "Project_Neural_Shielding",
}

# === HabResearchProduction: keep all 18 value=1.02 + 2 value=1.01 ===
HR_KEEP = {
    "Project_Cognitive_Cartography",
    "Project_Xeno_Cognition",
    "Project_XenoCognition",
    "Project_Cognitive_Horizons",
    "Project_Celestial_Observatory",
    "Project_Xeno_Synthesis",
    "Project_Cognitive_Frontier",
    "Project_Galactic_Knowledge_Harvest",
    "Project_Nebula_Knowledge_Mining",
    "Project_Galactic_Knowledge_Forge",
    "Project_Orbital_Telescope_Array",
    "Project_Galactic_Knowledge_Nexus",
    "Project_Nebula_Knowledge_Nexus",
    "Project_Celestial_Knowledge_Accelerator",
    "Project_Celestial_Alchemy",
    "Project_Celestial_Synergy",
    "Project_Quantum_Research_Initiative",
    "Project_Theoretical_Breakthroughs",
    "Project_Cosmic_Insight",
    "Project_Cognitive_Resonance",
}

# === ResourceMarketSales: 6 value=2 + 4 value=1 = 16 ===
RM_KEEP = {
    "Project_Nexus_Trade",
    "Project_Nexus_Exchange",
    "Project_Market_Nexus",
    "Project_Galactic_Market_Nexus",
    "Project_Market_Navigator",
    "Project_Cosmic_Market_Navigator",
    "Project_Trade_Nexus",
    "Project_Market_Consensus",
    "Project_Nexus_Commerce",
    "Project_Market_Pathways",
}


def load_effect_definitions():
    defs = {}
    for path in [GAME_EFFECTS, EFFECTS_FILE]:
        for eff in json.load(open(path)):
            defs[eff["dataName"]] = eff
    return defs


def get_context(proj, defs, context_name):
    for eff_name in proj.get("effects", []):
        eff_def = defs.get(eff_name, {})
        if context_name in eff_def.get("contexts", []):
            return eff_name
    return None


def main():
    defs = load_effect_definitions()
    projects = json.load(open(PROJECTS_FILE))

    delete_projects = set()

    # PherocyteResistance: delete single-effect not in keep list
    for proj in projects:
        if get_context(proj, defs, "PherocyteResistance"):
            if proj["dataName"] not in PR_KEEP and len(proj["effects"]) == 1:
                delete_projects.add(proj["dataName"])

    # HabResearchProduction: delete not in keep list
    for proj in projects:
        if get_context(proj, defs, "HabResearchProduction"):
            if proj["dataName"] not in HR_KEEP:
                delete_projects.add(proj["dataName"])

    # ResourceMarketSales: delete not in keep list
    for proj in projects:
        if get_context(proj, defs, "ResourceMarketSales"):
            if proj["dataName"] not in RM_KEEP:
                delete_projects.add(proj["dataName"])

    print(f"Projects to delete: {len(delete_projects)}")
    print(f"  PherocyteResistance kept: {len(PR_KEEP)}")
    print(f"  HabResearchProduction kept: {len(HR_KEEP)}")
    print(f"  ResourceMarketSales kept: {len(RM_KEEP)}")

    # Remove deleted projects
    original_count = len(projects)
    projects = [p for p in projects if p["dataName"] not in delete_projects]
    print(f"\nRemoved {original_count - len(projects)} projects, {len(projects)} remaining")

    # Clean up localization entries
    lines = open(LOCALIZATION_FILE, encoding="utf-8").readlines()
    new_lines = []
    removed_loc = 0
    for line in lines:
        skip = False
        for del_name in delete_projects:
            display_key = f"TIProjectTemplate.displayName.{del_name}"
            summary_key = f"TIProjectTemplate.summary.{del_name}"
            if line.startswith(display_key + "=") or line.startswith(summary_key + "="):
                skip = True
                removed_loc += 1
                break
        if not skip:
            new_lines.append(line)

    print(f"Removed {removed_loc} localization entries")

    # Write files
    json.dump(projects, open(PROJECTS_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    open(LOCALIZATION_FILE, "w", encoding="utf-8").writelines(new_lines)

    print(f"\nFiles written:")
    print(f"  {PROJECTS_FILE}")
    print(f"  {LOCALIZATION_FILE}")

    # Verification
    print("\n=== Verification ===")
    for ctx, keep_set in [
        ("PherocyteResistance", PR_KEEP),
        ("HabResearchProduction", HR_KEEP),
        ("ResourceMarketSales", RM_KEEP),
    ]:
        remaining = []
        for proj in projects:
            if get_context(proj, defs, ctx):
                eff_name = get_context(proj, defs, ctx)
                eff_def = defs.get(eff_name, {})
                remaining.append((proj["dataName"], eff_name, eff_def.get("value")))
        total = sum(v for _, _, v in remaining)
        print(f"  {ctx}: {len(remaining)} projects, total = {total}")


if __name__ == "__main__":
    main()
