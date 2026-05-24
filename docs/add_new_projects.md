# Instructions

Your job is to add new projects to the game. Each project has a unique `dataName` and various attributes that define its properties and requirements. Below is an example of how to add a new project called "25mm Light Rapid Autocannon".

  {
    "dataName": "Project_25mmAutocannon",
    "friendlyName": "25mm Light Rapid Autocannon",
    "description": "A secret prototype recovered from the archives. Unlocks a light rapid 25mm autocannon.",
    "techCategory": "MilitaryScience",
    "AI_techRole": "None",
    "AI_criticalTech": false,
    "AI_projectRole": "None",
    "researchCost": 500,
    "prereqs": [
      "Project_Warships",
      "PrinciplesofSpaceWarfare"
    ],
    "oneTimeGlobally": false,
    "repeatable": false,
    "factionAvailableChance": 100,
    "initialUnlockChance": 10,
    "deltaUnlockChance": 10,
    "maxUnlockChance": 100,
    "resourcesGranted": []
  },
  
## JSON line breakdown

- `dataName`: A unique identifier for the project, used in code and references. This will be used as key for the next set of data described in the next section.
- `friendlyName`: The name displayed to players in the game.
- `description`: A brief description of the project and its benefits.
- `techCategory`: The category of technology this project belongs to (e.g., MilitaryScience).
- `AI_techRole`: The role this project plays in AI decision-making (e.g., None, Core, Support).
- `AI_criticalTech`: A boolean indicating if this project is critical for AI strategies.
- `AI_projectRole`: The role this project plays in AI project selection (e.g., None, Core, Support).
- `researchCost`: The amount of research points required to complete the project.
- `prereqs`: An array of `dataName`s for projects that must be completed before this project can be researched.
- `oneTimeGlobally`: A boolean indicating if this project can only be completed once across the entire game.
- `repeatable`: A boolean indicating if this project can be researched multiple times.
- `factionAvailableChance`: The percentage chance that this project is available to a faction when they can choose from projects.
- `initialUnlockChance`: The percentage chance that this project is available at the start of the game.
- `deltaUnlockChance`: The percentage increase in unlock chance for this project each time a project is completed.
- `maxUnlockChance`: The maximum percentage chance that this project can be unlocked.
- `resourcesGranted`: An array of resources that are granted to the player upon completion of the project (empty in this example).
