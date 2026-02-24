# AI-worker

Where ai-worker runs
REPO_DIR="/home/martin/src/games/terra-invicta/ai-worker"

Create a new random project - start by running the script in $REPO_DIR/scripts/generate_project_list.sh

It will create a new project-dump in the structure of:

<CATEGORY>|<PROJECTNAME>|<RESEARCHCOST>

CATEGORY _must_ belong to one of the existing in the list.

Projectname must be created - and it must be unique.

Research cost the same.

For now, only create projects that can improve the game cost-areas; so that means we will create new projects that will improve the economy with X-%, knowledge by X-% etc.

We will not create new weapons, drives, habs or anything else - only improvements like ths above.

# TIEffects

First - pick an TIEffect.

A typical TIEffect looks like:

 {
   "dataName": "Effect_EconomyPriorityBonus02",
   "operation": "Additive",
   "value": 0.02,
   "effectTarget": "SourceFaction",
   "effectDuration": "permanent",
   "stackable": true,
   "duration_months": -1,
   "contexts": [
      "EconomyPriority"
   ]
},

These can be found in: /home/martin/Games/TerraInvicta/templates/TIEffectTemplate.json

Pick any random Effect to go with the new project - though it must have a specific context array value.

It can be any of:
- EconomyPriority
- MCFreeSpaceMineNetwork
- ControlPointMaintenance
- KnowledgePriority
- EconomyPriority
- MilitaryPriority
- UnityPriority
- SpoilsPriority
- SpaceMiningBonus
- ShipMagDamage
- ShipLaserDamage
- ShipConvMissileDamage
- ResourceMarketSales
- ParticleLaserDamage
- OppressionPriority
- HumanLifespan
- HabResearchProduction
- GovernmentPriority
- EnvironmentPriority
- BuildArmyPriority
- WelfarePriority
- PherocyteResistance
- MiningWaterBonus
- MiningVolatilesBonus
- MiningNoblesBonus
- MiningMetalsBonus
- MiningFissilesBonus
- ArmyDamageBonustoMegafauna

When picking one, find all the existing Effects with that type, and take note of their operation & value. Take the highest value and divide that by 50-75%.

Then take the resulting value and generate a random value between 10-80% of that.

Example if value = 0.2:

1. Divide by 50-75% (I'll randomly pick 65%)
   1. 0.2 * 0.65 = 0.130 (my new upper limit)
2. Pick a random number between 10-80% (I'll randomly pick 50%)
   1. 0.130 * 0.5 = 0.065 (my new value)

Keep the same "operation" type _always_

# Create a new Project

To create a new project, 2 things are required:

1. Add a new project to the Mods/TIProjectTemplate.json.
Example could be:
  {
    "dataName": "Project_CivicResourceStabilization_I",
    "friendlyName": "Civic Resource Stabilization I",
    "techCategory": "InformationScience",
    "AI_techRole": "None",
    "AI_criticalTech": false,
    "AI_projectRole": "None",
    "researchCost": 500,
    "prereqs": [
      "Project_Warships"
    ],
    "effects": [
      "Effect_EconomyPriorityBonus02",
    ],
    "oneTimeGlobally": false,
    "repeatable": false,
    "factionAvailableChance": 100,
    "initialUnlockChance": 10,
    "deltaUnlockChance": 10,
    "maxUnlockChance": 100,
    "resourcesGranted": []
  },

When creating this ensure that:
- prereqs is a project that already exists!
- Align researchCost roughly to what the project prereq is - but make it a little higher
- Keep factionAvailableChance & maxUnlockChance at 100, but add random numbers to deltaUnlockChance & initialUnlockChance

When done, create a localization entry for it under Mods/Localization/en/TIProjectTempalte.en

Ensure that the name added in this file maps to the "dataName" in the TIProjectTemplate.json file.

Example for the above entry could be something like:
TIProjectTemplate.displayName.Project_CivicResourceStabilization_I=Stabilization of Civic Resource Systems I
TIProjectTemplate.summary.Project_CivicResourceStabilization_I=Advanced techniques to stabilize and optimize civic resource systems.

