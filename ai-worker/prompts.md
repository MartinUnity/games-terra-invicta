```markdown
# Prompt templates and schema

This file supplies the base prompt fragments the worker will combine with `ai-worker/requirements.md` when asking the LLM to produce a candidate project.

Model output requirements (script expects JSON):

- The model MUST return a single TOP-LEVEL JSON object representing a new project. The object MUST include all these keys: `dataName`, `friendlyName`, `techCategory`, `researchCost`, `prereqs`, `oneTimeGlobally`, `repeatable`, `factionAvailableChance`, `initialUnlockChance`, `deltaUnlockChance`, `maxUnlockChance`, `resourcesGranted`, and `effects`.
- `effects` MUST be an array containing one or more existing effect IDs (strings) that exactly match entries in `/home/martin/Games/TerraInvicta/templates/TIEffectTemplate.json`. Do NOT invent new effect IDs or full effect objects.

The worker will validate the result against a JSON Schema. If the model cannot return a full project object that includes a valid `effects` array mapping to existing effect IDs, it must return a JSON object with a single `error` key explaining the problem, e.g. `{ "error": "explanation" }`.
To make the required shape explicit, include this example JSON in the prompt and return a complete object following the same structure (you should vary values, names, and choose an appropriate `contexts` value):

```json
{
  "dataName": "Project_Example_I",
  "friendlyName": "Example Project I",
  "techCategory": "InformationScience",
  "AI_techRole": "None",
  "AI_criticalTech": false,
  "AI_projectRole": "None",
  "researchCost": 500,
  "prereqs": ["Project_Warships"],
  "oneTimeGlobally": false,
  "repeatable": false,
  "factionAvailableChance": 100,
  "initialUnlockChance": 10,
  "deltaUnlockChance": 10,
  "maxUnlockChance": 100,
  "resourcesGranted": [],
  "effects": ["Effect_EconomyPriorityBonus02"]
}
```

Prompt instruction text (the worker will append `ai-worker/requirements.md` for context):

"Return only a single JSON object and nothing else. The object must match the example structure above and include a valid `effects` array (map to existing effect IDs) or `TIEffect` object. Compute `TIEffect.value` according to the rules in `ai-worker/requirements.md` (derive an upper limit from existing effects then choose a smaller value). Use realistic and consistent values for `researchCost` and `prereqs`. If you cannot produce a full valid project object, return `{ \"error\": \"reason\" }`."

IMPORTANT: To ensure strict formatting, wrap your JSON response exactly between the tags `<json>` and `</json>` with no additional text before, after, or between the tags. Example:

<json>{ ... }</json>

If you do not follow this exact wrapper format, the worker will consider the output invalid.

Use and adapt this template to tune behaviour and model instructions.

```
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

