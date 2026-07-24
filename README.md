# Terra Invicta Tools

Extract, visualize, and mod Terra Invicta savegame data.

> [!IMPORTANT]
> Uses an rsync action inside [The Workspace File](terra-invicta.code-workspace) to sync files to the game's Mods directory.

## Core Scripts

- `extraction.py` - Parse savegames into structured CSV/JSON datasets
- `show-data.py` - Streamlit app with interactive charts and filters
- `config.py` - Centralized workspace paths and data file constants
- `scripts/cleanup_saves.py` - Archive/tidy save games (keeps newest N per type)

## Script Organization

| File | Summary |
|------|---------|
| | **Root** |
| `extraction.py` | Parse savegames into structured CSV/JSON datasets |
| `show-data.py` | Streamlit app with interactive charts and filters |
| `config.py` | Centralized workspace paths and data file constants |
| | |
| | **scripts/cleanup_saves.py** |
| `scripts/cleanup_saves.py` | Archive and tidy save games (keeps newest N per type) |
| | |
| | **scripts/ai/** — AI project generation |
| `scripts/ai/worker.py` | Call local Ollama model to generate staged project candidates |
| `scripts/ai/swarm.py` | Swarm orchestrator for multiple Ollama models |
| `scripts/ai/runner.py` | Core run_cycle orchestration logic |
| `scripts/ai/helpers.py` | JSON extraction, model calls, staging, validation utilities |
| `scripts/ai/prompts.py` | Prompt building helpers |
| `scripts/ai/selection.py` | Template/effect selection logic |
| `scripts/ai/mining_leveler.py` | Mining bonus level suffix mapping |
| | |
| | **scripts/mods/** — Mod validation and utilities |
| `scripts/mods/validate.py` | Read-only validator for all mod JSON files (includes loc orphan check) |
| `scripts/mods/loc_audit.py` | Find orphan/missing/partial localization entries + placeholder validation. Supports `--delete`. |
| `scripts/mods/check_localization.py` | Validate mod entries against localization file |
| `scripts/mods/check_weapons.py` | Score weapons by capability, flag prereq-cost outliers |
| `scripts/mods/check_armor.py` | Score armor by capability, flag prereq-cost outliers |
| `scripts/mods/check_drives.py` | Score drives by capability, flag prereq-cost outliers |
| `scripts/mods/generate_weapon.py` | Generate weapon templates from damage/DPS parameters |
| `scripts/mods/scan_effects.py` | Count effect occurrences in project templates |
| `scripts/mods/update_descriptions.py` | Update project summaries via local Ollama model |
| `scripts/mods/fix_unlock_chance.py` | Fix max unlock chance values |
| `scripts/mods/prereq_cost.py` | Calculate total prereq cost for projects and suggest chains |
| | |
| | **scripts/tools/** |
| `scripts/tools/mining_bonus.sh` | Get full mining bonus data |
| `scripts/tools/project_list.sh` | Generate project list for AI worker |
| `scripts/tools/generate_outline.py` | Generate project outline documentation |
| | |
| | **scripts/one_off/** — Analysis |
| `scripts/one_off/analyze_all_effects.py` | All effects across every project, grouped by context, with value conversion |
| `scripts/one_off/analyze_effects.py` | Tracked priority effects only (from `project_effects.txt`) |
| `scripts/one_off/analyze_weapon_balance.py` | Correlate weapon DPS with research cost, mount slots, PD vulnerability |
| `scripts/one_off/analyze_heatsink_balance.py` | Compare heatsink capacity/mass ratio against base game |
| `scripts/one_off/analyze_radiator_balance.py` | Compare radiator power, temp, vulnerability against base game |
| `scripts/one_off/analyze_powerplant_balance.py` | Compare power plant output, efficiency, density against base game |
| | |
| | **scripts/one_off/** — Balancing (modify mod files) |
| `scripts/one_off/balance_effects.py` | Bump effect tiers below 400% into target range, adjust cost |
| `scripts/one_off/balance_prereqs.py` | Redistribute prerequisites for even game-progression spread |
| `scripts/one_off/update_research_costs.py` | Reduce cost for effect-matched projects, clamp outliers |
| | |
| | **scripts/one_off/** — Content generation |
| `scripts/one_off/generate_content.py` | AI-driven mod content: easy/middle/full tiers, `--dry-run` then `--apply` |
| `scripts/one_off/consolidate_mc_hl.py` | Consolidate MC mining and human lifespan projects |
| `scripts/one_off/consolidate_military.py` | Consolidate MilitaryPriority projects |
| `scripts/one_off/generate_funding_effects.py` | Generate SpaceDevPriority effects and ~40 projects |
| `scripts/one_off/reduce_effects.py` | Reduce overabundant effects (Pherocyte, HabResearch, MarketSales) |
| `scripts/one_off/validate_exotic_prereqs.py` | Verify exotic-material items have Exotics in prereq chain |

## Getting Started

### Install dependencies
```bash
python3 -m pip install -r requirements.txt
```

### Run all scripts
```bash
./runme.sh start|stop|restart|status
```

### Run individually
```bash
python3 extraction.py
streamlit run show-data.py
```

## AI Project Generation

Run the AI worker with your preferred model:

```bash
python3 scripts/ai/worker.py --once --print-output --generate-localization --model gemma3:12b --temperature 0.15 --loc-attempts 6 --auto-apply --count 1
```

### Temperature Guide

| Temperature | Outcome                           |
| ----------- | --------------------------------- |
| 0.0         | Deterministic, low creativity     |
| 0.1 - 0.3   | Conservative, safe variation      |
| 0.4 - 0.7   | Moderate creativity               |
| ~1.0+       | High randomness, unpredictable    |

Generally 12B+ parameter models produce usable results. Find local models with `ollama list`.

See `ai-worker/prompts.md` for prompt instructions and `ai-worker/llm-config.yml` for LLM settings.

## Adding Nations for Data Capture

### Automatic
Set in `extraction.py`:
```python
AUTO_PERSIST_MY_NATIONS = True
ALWAYS_OVERWRITE_MY_NATIONS = True
```

### Manual
Set above to `False`, then add nation names in `config.yml`:
```yaml
my_nations:
  - United Kingdom
  - Germany
  - Mauritius
```

## Helpful Commands

```bash
cat /home/martin/Games/TerraInvicta/templates/TITechTemplate.json | yq -r '.[] | .techCategory + "|" + .dataName + " - " + (.researchCost|tostring)' | grep -i "spaceScience" | sort -n -k 3
```
