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
