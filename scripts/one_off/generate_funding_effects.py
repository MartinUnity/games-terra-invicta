#!/usr/bin/env python3
"""
Generate SpaceDevPriority effects and ~40 projects to reach ~400 total.

Target mix (40 projects, 398% total):
  - 4 projects with Bonus02 (2%)  = 8%
  - 10 projects with Bonus05 (5%) = 50%
  - 14 projects with Bonus10 (10%) = 140%
  - 8 projects with Bonus15 (15%) = 120%
  - 4 projects with Bonus20 (20%) = 80%
  Grand total: 398% (~400 target)

Distribution per tech category (10 each):
  SocialScience:    2x02 + 3x05 + 4x10 + 1x15 = 71%
  InformationScience: 1x02 + 2x05 + 4x10 + 2x15 + 1x20 = 104%
  SpaceScience:     1x02 + 2x05 + 4x10 + 2x15 + 1x20 = 104%
  Materials:        0x02 + 3x05 + 2x10 + 3x15 + 1x20 = 108%
  Grand total: 398%
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
EFFECTS_FILE = BASE / "Mods" / "TIEffectTemplate.json"
PROJECTS_FILE = BASE / "Mods" / "TIProjectTemplate.json"
EFFECTS_LOC = BASE / "Mods" / "Localization" / "en" / "TIEffectTemplate.en"
PROJECTS_LOC = BASE / "Mods" / "Localization" / "en" / "TIProjectTemplate.en"

NEW_EFFECTS = [
    {"dataName": "Effect_SpaceDevPriorityBonus02", "operation": "Additive",
     "value": 0.02, "effectTarget": "SourceFaction",
     "effectDuration": "permanent", "stackable": True,
     "duration_months": -1, "contexts": ["SpaceDevPriority"]},
    {"dataName": "Effect_SpaceDevPriorityBonus05", "operation": "Additive",
     "value": 0.05, "effectTarget": "SourceFaction",
     "effectDuration": "permanent", "stackable": True,
     "duration_months": -1, "contexts": ["SpaceDevPriority"]},
    {"dataName": "Effect_SpaceDevPriorityBonus10", "operation": "Additive",
     "value": 0.1, "effectTarget": "SourceFaction",
     "effectDuration": "permanent", "stackable": True,
     "duration_months": -1, "contexts": ["SpaceDevPriority"]},
    {"dataName": "Effect_SpaceDevPriorityBonus15", "operation": "Additive",
     "value": 0.15, "effectTarget": "SourceFaction",
     "effectDuration": "permanent", "stackable": True,
     "duration_months": -1, "contexts": ["SpaceDevPriority"]},
    {"dataName": "Effect_SpaceDevPriorityBonus20", "operation": "Additive",
     "value": 0.2, "effectTarget": "SourceFaction",
     "effectDuration": "permanent", "stackable": True,
     "duration_months": -1, "contexts": ["SpaceDevPriority"]},
]

# (dataName, friendlyName, techCategory, researchCost, prereqs, effect, displayName, description)
NEW_PROJECTS = [
    # === SocialScience: Budget allocation, civic investment (10 projects) ===
    # 2x02 + 3x05 + 4x10 + 1x15 = 4+15+40+15 = 74% -> actually 74, let me use:
    # 2x02 + 3x05 + 4x10 + 1x15 = 4+15+40+15 = 74%
    ("Project_BudgetReform_Initiative", "Budget Reform Initiative", "SocialScience",
     3000, ["Project_CivilianFusionReactors"], "Effect_SpaceDevPriorityBonus02",
      "Budget Reform Initiative",
      "Initial steps toward rationalizing government spending on space development through streamlined procurement."),
    ("Project_Investment_Optimization_I", "Investment Optimization I", "SocialScience",
     4000, ["Project_AlgorithmicEconomicManagement"], "Effect_SpaceDevPriorityBonus02",
      "Investment Optimization I",
      "Basic financial models improve the allocation of national investment points toward space infrastructure."),
    ("Project_Civic_Space_Pledge", "Civic Space Pledge", "SocialScience",
     7000, ["Project_BudgetReform_Initiative", "Project_MediaLiteracyTraining"],
     "Effect_SpaceDevPriorityBonus05",
      "Civic Space Pledge",
      "Public awareness campaigns build grassroots support for increased space development funding."),
    ("Project_Space_Dev_Fund_I", "Space Development Fund I", "SocialScience",
     8000, ["Project_Investment_Optimization_I", "Project_CivicResourceStabilization_I"],
     "Effect_SpaceDevPriorityBonus05",
      "Space Development Fund I",
      "Establishes a dedicated fund for space development projects, ensuring consistent budget allocation."),
    ("Project_Space_Economy_Framework", "Space Economy Framework", "SocialScience",
     8500, ["Project_Civic_Space_Pledge", "Project_CivilianQuantumComputing"],
     "Effect_SpaceDevPriorityBonus05",
      "Space Economy Framework",
      "A comprehensive economic framework that prioritizes long-term space investment over short-term gains."),
    ("Project_National_Space_Trust", "National Space Trust", "SocialScience",
     12000, ["Project_Space_Dev_Fund_I", "Project_Space_Economy_Framework"],
     "Effect_SpaceDevPriorityBonus10",
      "National Space Trust",
      "Creates a sovereign wealth fund dedicated to financing space development, pooling resources from multiple streams."),
    ("Project_Strategic_Investment_Body", "Strategic Investment Body", "SocialScience",
     13000, ["Project_National_Space_Trust", "Project_Space_Economy_Framework"],
     "Effect_SpaceDevPriorityBonus10",
      "Strategic Investment Body",
      "An independent agency evaluates and allocates national investment toward the most productive space projects."),
    ("Project_Space_Dev_Corporatization", "Space Development Corporatization", "SocialScience",
     15000, ["Project_Strategic_Investment_Body", "Project_National_Space_Trust"],
     "Effect_SpaceDevPriorityBonus10",
      "Space Development Corporatization",
      "Transfers space development funding to semi-autonomous entities that operate with private sector efficiency."),
    ("Project_Global_Space_Economy", "Global Space Economy", "SocialScience",
     17000, ["Project_Space_Dev_Corporatization", "Project_Strategic_Investment_Body"],
     "Effect_SpaceDevPriorityBonus10",
      "Global Space Economy",
      "Integrates space development into the national economic model, creating self-sustaining funding loops."),
    ("Project_Cosmic_Dividend_Plan", "Cosmic Dividend Plan", "SocialScience",
     22000, ["Project_Global_Space_Economy", "Project_Space_Dev_Corporatization"],
     "Effect_SpaceDevPriorityBonus15",
      "Cosmic Dividend Plan",
      "Channels orbital resource revenues directly back into further space development, creating exponential growth."),

    # === InformationScience: Data-driven allocation (10 projects) ===
    # 1x02 + 2x05 + 4x10 + 2x15 + 1x20 = 2+10+40+30+20 = 102%
    ("Project_AI_Budget_Analysis", "AI Budget Analysis", "InformationScience",
     4000, ["Project_AugmentedLearning"], "Effect_SpaceDevPriorityBonus02",
      "AI Budget Analysis",
      "Artificial intelligence models analyze budget data to identify optimal funding allocations for space programs."),
    ("Project_Predictive_Space_Planning", "Predictive Space Planning", "InformationScience",
     7500, ["Project_AI_Budget_Analysis", "Project_CivilianPhotonicComputing"],
     "Effect_SpaceDevPriorityBonus05",
      "Predictive Space Planning",
      "Predictive algorithms forecast the economic impact of space investments, enabling efficient fund distribution."),
    ("Project_Digital_Fiscal_Oversight", "Digital Fiscal Oversight", "InformationScience",
     8000, ["Project_Predictive_Space_Planning"], "Effect_SpaceDevPriorityBonus05",
      "Digital Fiscal Oversight",
      "Real-time digital monitoring of space budgets reduces waste and redirects funds to high-priority projects."),
    ("Project_Blockchain_Space_Treasury", "Blockchain Space Treasury", "InformationScience",
     12000, ["Project_Digital_Fiscal_Oversight"], "Effect_SpaceDevPriorityBonus10",
      "Blockchain Space Treasury",
      "Distributed ledger technology creates transparent, tamper-proof tracking of space development funds."),
    ("Project_Quantum_Economic_Modeling", "Quantum Economic Modeling", "InformationScience",
     13000, ["Project_Blockchain_Space_Treasury", "Project_CivilianQuantumComputing"],
     "Effect_SpaceDevPriorityBonus10",
      "Quantum Economic Modeling",
      "Quantum computing enables simulation of millions of economic scenarios for optimal space investment strategy."),
    ("Project_Automated_Fund_Routing", "Automated Fund Routing", "InformationScience",
     14000, ["Project_Quantum_Economic_Modeling", "Project_Blockchain_Space_Treasury"],
     "Effect_SpaceDevPriorityBonus10",
      "Automated Fund Routing",
      "AI-driven systems dynamically reroute space development funds based on real-time project performance."),
    ("Project_Singularity_Budget_Ops", "Singularity Budget Operations", "InformationScience",
     15000, ["Project_Automated_Fund_Routing", "Project_Quantum_Economic_Modeling"],
     "Effect_SpaceDevPriorityBonus10",
      "Singularity Budget Operations",
      "Self-improving AI systems manage space development budgets with superhuman efficiency."),
    ("Project_Neural_Economic_Grid", "Neural Economic Grid", "InformationScience",
     18000, ["Project_Singularity_Budget_Ops", "Project_Blockchain_Space_Treasury"],
     "Effect_SpaceDevPriorityBonus15",
      "Neural Economic Grid",
      "A neural-network-based economic grid that autonomously optimizes space funding across all sectors."),
    ("Project_Orbital_Resource_AI", "Orbital Resource AI Director", "InformationScience",
     20000, ["Project_Neural_Economic_Grid", "Project_Singularity_Budget_Ops"],
     "Effect_SpaceDevPriorityBonus15",
      "Orbital Resource AI Director",
      "An autonomous AI director allocates orbital resource extraction budgets with perfect efficiency."),
    ("Project_Omega_Investment_Protocol", "Omega Investment Protocol", "InformationScience",
     25000, ["Project_Orbital_Resource_AI", "Project_Neural_Economic_Grid"],
     "Effect_SpaceDevPriorityBonus20",
      "Omega Investment Protocol",
      "The ultimate AI-driven investment protocol achieving near-perfect capital allocation for space development."),

    # === SpaceScience: Space infrastructure funding (10 projects) ===
    # 1x02 + 2x05 + 4x10 + 2x15 + 1x20 = 2+10+40+30+20 = 102%
    ("Project_Space_Infrastructure_Grant", "Space Infrastructure Grant Program", "SpaceScience",
     4500, ["Project_SpaceHotel"], "Effect_SpaceDevPriorityBonus02",
      "Space Infrastructure Grant Program",
      "A grant program targeted at early-stage space infrastructure, providing seed funding for orbital development."),
    ("Project_Orbital_Financial_Hub", "Orbital Financial Hub", "SpaceScience",
     7500, ["Project_Space_Infrastructure_Grant"], "Effect_SpaceDevPriorityBonus05",
      "Orbital Financial Hub",
      "Establishes a financial services hub in low Earth orbit to streamline space development funding."),
    ("Project_Lunar_Investment_Corridor", "Lunar Investment Corridor", "SpaceScience",
     8000, ["Project_Orbital_Financial_Hub"], "Effect_SpaceDevPriorityBonus05",
      "Lunar Investment Corridor",
      "Creates a dedicated funding corridor between Earth and lunar facilities, accelerating capital flow."),
    ("Project_Mars_Dev_Capital", "Mars Development Capital", "SpaceScience",
     12000, ["Project_Lunar_Investment_Corridor"], "Effect_SpaceDevPriorityBonus10",
      "Mars Development Capital",
      "Channels national investment into long-term Mars development infrastructure and interplanetary projects."),
    ("Project_Asteroid_Financing_Initiative", "Asteroid Financing Initiative", "SpaceScience",
     13000, ["Project_Mars_Dev_Capital"], "Effect_SpaceDevPriorityBonus10",
      "Asteroid Financing Initiative",
      "Specialized financial instruments and venture capital models designed to fund asteroid mining operations."),
    ("Project_Deep_Space_Budget_Expansion", "Deep Space Budget Expansion", "SpaceScience",
     14000, ["Project_Asteroid_Financing_Initiative", "Project_Mars_Dev_Capital"],
     "Effect_SpaceDevPriorityBonus10",
      "Deep Space Budget Expansion",
      "Expands the national space budget to encompass deep space operations, funding missions beyond Mars."),
    ("Project_Cislunar_Economy", "Cislunar Economy Program", "SpaceScience",
     15000, ["Project_Deep_Space_Budget_Expansion", "Project_Lunar_Investment_Corridor"],
     "Effect_SpaceDevPriorityBonus10",
      "Cislunar Economy Program",
      "Creates a self-sustaining economic zone between Earth and Moon, generating revenue for space development."),
    ("Project_Helio_Orbital_Trade", "Helio-Orbital Trade Network", "SpaceScience",
     18000, ["Project_Cislunar_Economy", "Project_Asteroid_Financing_Initiative"],
     "Effect_SpaceDevPriorityBonus15",
      "Helio-Orbital Trade Network",
      "Establishes interplanetary trade routes with dedicated funding mechanisms, creating new revenue streams."),
    ("Project_Oort_Cloud_Fund", "Oort Cloud Development Fund", "SpaceScience",
     20000, ["Project_Helio_Orbital_Trade", "Project_Cislunar_Economy"],
     "Effect_SpaceDevPriorityBonus15",
      "Oort Cloud Development Fund",
      "A long-term development fund targeting the outer solar system, leveraging inner system returns."),
    ("Project_Starlight_Investment_Plan", "Starlight Investment Plan", "SpaceScience",
     25000, ["Project_Oort_Cloud_Fund", "Project_Helio_Orbital_Trade"],
     "Effect_SpaceDevPriorityBonus20",
      "Starlight Investment Plan",
      "The most ambitious space funding program, allocating vast resources to interstellar preparation."),

    # === Materials: Resource-backed funding (10 projects) ===
    # 1x02 + 3x05 + 2x10 + 3x15 + 1x20 = 2+15+20+45+20 = 102%
    # Wait, I need 0x02 + 3x05 + 2x10 + 3x15 + 1x20 = 0+15+20+45+20 = 100%
    # Hmm, that's 9 projects. Let me redo:
    # 0x02 + 3x05 + 3x10 + 2x15 + 1x20 = 0+15+30+30+20 = 95% for 9
    # Need 10 projects: 0x02 + 4x05 + 2x10 + 3x15 + 1x20 = 0+20+20+45+20 = 105%
    ("Project_Space_Mining_Venture_Cap", "Space Mining Venture Capital", "Materials",
     7000, ["Project_Space_Infrastructure_Grant"], "Effect_SpaceDevPriorityBonus05",
      "Space Mining Venture Capital",
      "Dedicated venture capital funds that invest in high-risk, high-reward space mining operations."),
    ("Project_Resource_Backed_Bonds", "Resource-Backed Space Bonds", "Materials",
     7500, ["Project_Space_Mining_Venture_Cap"], "Effect_SpaceDevPriorityBonus05",
      "Resource-Backed Space Bonds",
      "Government bonds backed by future space resource extraction revenues create a new funding source."),
    ("Project_Orbital_Refinery_Equity", "Orbital Refinery Equity Program", "Materials",
     8000, ["Project_Resource_Backed_Bonds"], "Effect_SpaceDevPriorityBonus05",
      "Orbital Refinery Equity Program",
      "An equity-sharing program distributing ownership of orbital refineries to channel private capital."),
    ("Project_Rare_Earth_Space_Fund", "Rare Earth Space Fund", "Materials",
     8500, ["Project_Orbital_Refinery_Equity"], "Effect_SpaceDevPriorityBonus05",
      "Rare Earth Space Fund",
      "Leverages profits from rare earth extraction to create a revolving fund for new development projects."),
    ("Project_Titanium_Economic_Initiative", "Titanium Economic Initiative", "Materials",
     12000, ["Project_Rare_Earth_Space_Fund"], "Effect_SpaceDevPriorityBonus10",
      "Titanium Economic Initiative",
      "Establishes a titanium-based economy using space-extracted metals as collateral for development loans."),
    ("Project_Helium3_Market_Stabilization", "Helium-3 Market Stabilization", "Materials",
     13000, ["Project_Titanium_Economic_Initiative"], "Effect_SpaceDevPriorityBonus10",
      "Helium-3 Market Stabilization",
      "Stabilizes helium-3 markets through strategic reserves, ensuring steady revenue for space programs."),
    ("Project_Noble_Metal_Space_Standard", "Noble Metal Space Standard", "Materials",
     16000, ["Project_Helium3_Market_Stabilization", "Project_Titanium_Economic_Initiative"],
     "Effect_SpaceDevPriorityBonus15",
      "Noble Metal Space Standard",
      "Adopts a precious metal standard for space development currency, backed by asteroid-mined reserves."),
    ("Project_Resource_Collateral_Framework", "Resource Collateral Framework", "Materials",
     18000, ["Project_Noble_Metal_Space_Standard", "Project_Rare_Earth_Space_Fund"],
     "Effect_SpaceDevPriorityBonus15",
      "Resource Collateral Framework",
      "Creates a universal collateral system using space resources as loan backing, unlocking massive capital."),
    ("Project_Planetary_Mining_Trust", "Planetary Mining Trust", "Materials",
     20000, ["Project_Resource_Collateral_Framework", "Project_Noble_Metal_Space_Standard"],
     "Effect_SpaceDevPriorityBonus15",
      "Planetary Mining Trust",
      "Establishes a planetary-scale mining trust pooling resource revenues from all celestial bodies."),
    ("Project_Interstellar_Resource_Reserve", "Interstellar Resource Reserve", "Materials",
     25000, ["Project_Planetary_Mining_Trust", "Project_Resource_Collateral_Framework"],
     "Effect_SpaceDevPriorityBonus20",
      "Interstellar Resource Reserve",
      "The ultimate resource-backed funding mechanism, leveraging the entire solar system's mineral wealth."),
]

EFFECT_LOC_LINES = [
    "TIEffectTemplate.description.Effect_SpaceDevPriorityBonus02=-National Investment Points we direct to Space Development funding priorities are increased by {3}",
    "TIEffectTemplate.description.Effect_SpaceDevPriorityBonus05=-National Investment Points we direct to Space Development funding priorities are increased by {3}",
    "TIEffectTemplate.description.Effect_SpaceDevPriorityBonus10=-National Investment Points we direct to Space Development funding priorities are increased by {3}",
    "TIEffectTemplate.description.Effect_SpaceDevPriorityBonus15=-National Investment Points we direct to Space Development funding priorities are increased by {3}",
    "TIEffectTemplate.description.Effect_SpaceDevPriorityBonus20=-National Investment Points we direct to Space Development funding priorities are increased by {3}",
]


def add_effects():
    with open(EFFECTS_FILE) as f:
        effects = json.load(f)
    for new_eff in NEW_EFFECTS:
        effects.append(new_eff)
    with open(EFFECTS_FILE, "w") as f:
        json.dump(effects, f, indent=2)
    print(f"Added {len(NEW_EFFECTS)} effects to {EFFECTS_FILE}")


def add_projects():
    with open(PROJECTS_FILE) as f:
        projects = json.load(f)
    for proj_data in NEW_PROJECTS:
        (data_name, friendly_name, tech_cat, research_cost,
         prereqs, effect, display_name, description) = proj_data
        project = {
            "dataName": data_name,
            "friendlyName": friendly_name,
            "techCategory": tech_cat,
            "AI_techRole": "None",
            "AI_criticalTech": False,
            "AI_projectRole": "SpaceResources",
            "researchCost": research_cost,
            "prereqs": prereqs,
            "effects": [effect],
            "oneTimeGlobally": False,
            "repeatable": False,
            "factionAvailableChance": 100,
            "initialUnlockChance": 10,
            "deltaUnlockChance": 5,
            "maxUnlockChance": 100,
            "resourcesGranted": []
        }
        projects.append(project)
    with open(PROJECTS_FILE, "w") as f:
        json.dump(projects, f, indent=2)
    print(f"Added {len(NEW_PROJECTS)} projects to {PROJECTS_FILE}")


def add_effect_localization():
    with open(EFFECTS_LOC, "a") as f:
        f.write("\n\n")
        for line in EFFECT_LOC_LINES:
            f.write(line + "\n")
    print(f"Added effect localization to {EFFECTS_LOC}")


def add_project_localization():
    with open(PROJECTS_LOC, "a") as f:
        f.write("\n\n# === SpaceDevPriority Funding Projects ===\n")
        for proj_data in NEW_PROJECTS:
            (data_name, friendly_name, tech_cat, research_cost,
             prereqs, effect, display_name, description) = proj_data
            f.write(f"TIProjectTemplate.displayName.{data_name}={display_name}\n")
            f.write(f"TIProjectTemplate.description.{data_name}={description}\n")
    print(f"Added project localization to {PROJECTS_LOC}")


def print_summary():
    from collections import Counter
    tier_counts = Counter()
    cat_counts = Counter()
    total = 0
    for proj_data in NEW_PROJECTS:
        effect = proj_data[5]
        cat_counts[proj_data[2]] += 1
        if "02" in effect:
            tier_counts["2%"] += 1
            total += 2
        elif "05" in effect:
            tier_counts["5%"] += 1
            total += 5
        elif "10" in effect:
            tier_counts["10%"] += 1
            total += 10
        elif "15" in effect:
            tier_counts["15%"] += 1
            total += 15
        elif "20" in effect:
            tier_counts["20%"] += 1
            total += 20

    print(f"\n=== Summary ===")
    print(f"Total projects: {len(NEW_PROJECTS)}")
    print(f"Total effects: {len(NEW_EFFECTS)}")
    print(f"\nEffect tier distribution:")
    for tier, count in sorted(tier_counts.items()):
        pct = int(tier.rstrip('%'))
        print(f"  {tier}: {count} projects ({count * pct}% contribution)")
    print(f"\nGrand total: {total}%")
    print(f"\nProjects per tech category:")
    for cat, count in sorted(cat_counts.items()):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    print_summary()
    add_effects()
    add_projects()
    add_effect_localization()
    add_project_localization()
    print("\nDone! Run sync_mods.sh and validate with scripts.")
