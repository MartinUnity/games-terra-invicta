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

### AI Project Generation (`scripts/ai/`)
- `worker.py` - AI worker that calls a local Ollama model to generate staged project candidates
- `swarm.py` - Swarm orchestrator for multiple Ollama models
- `runner.py` - Core run_cycle orchestration logic
- `helpers.py` - JSON extraction, model calls, staging, validation utilities
- `prompts.py` - Prompt building helpers
- `selection.py` - Template/effect selection logic
- `mining_leveler.py` - Mining bonus level suffix mapping

### Mod Utilities (`scripts/mods/`)
- `check_localization.py` - Validate mod entries against localization file
- `fix_unlock_chance.py` - Fix max unlock chance values
- `generate_weapon.py` - Generate weapon templates from damage/DPS parameters
- `scan_effects.py` - Count effect occurrences in project templates
- `update_descriptions.py` - Update project summaries via local Ollama model
- `validate.py` - Read-only validator for mod JSON files (includes localization orphan check via `loc_audit.py`)
- `loc_audit.py` - Cross-reference templates vs localization: find orphan/missing/partial entries. Supports `--delete` to zap orphan localization lines.

### Tools (`scripts/tools/`)
- `mining_bonus.sh` - Get full mining bonus data
- `project_list.sh` - Generate project list for AI worker
- `generate_outline.py` - Generate project outline documentation

### One-Off Scripts (`scripts/one_off/`)

#### Analysis (read-only, no side effects)
- `analyze_weapon_balance.py` — Correlate weapon DPS with research cost, mount slots, and PD vulnerability. Reads all weapon template files plus project research costs. Use to find over/under-powered weapons.
- `analyze_heatsink_balance.py` — Compare heat sink capacity/mass ratio against base game entries. Key metric: `heatCapacity_GJ / mass_tons`. Mod entries flagged if capacity/ton is >150% or <50% of base game average.
- `analyze_radiator_balance.py` — Compare radiator specific power, operating temp, vulnerability, and collector status against base game. Key metrics: `specificPower_2s_KWkg`, `operatingTemp_K`, `vulnerability`. Includes vulnerability tier breakdown.
- `analyze_powerplant_balance.py` — Compare power plant output, efficiency, and power density against base game. Key metrics: `maxOutput_GW`, `efficiency`, `specificPower_tGW`. Shows per-class comparison between mod and base entries.
- `analyze_all_effects.py` — Analyze **all** effects across every project, grouped by context with value conversion (percentages, raw, multiplicative). Supports `--ctx <context>` filter and `--raw` mode. Use to see what effect totals look like before balancing.
- `analyze_effects.py` — Narrower analysis of tracked priority effects only (from `project_effects.txt`). Use for quick checks on the effect categories you're actively balancing.

#### Balancing (modify mod files, prompts before writing)
- `balance_effects.py` — Bump effect tiers for categories below 400% total into the 400–700% target range. Increases research cost proportionally. Tracks effects from `project_effects.txt`.
- `balance_prereqs.py` — Redistribute project prerequisites for even game-progression spread. Uses AI value scoring (1–10) and cumulative research cost as placement signal. Modes: `--analyze`, `--dry-run`, `--apply`. Results cached in `.balance_cache.json`.
- `update_research_costs.py` — Reduce research cost for effect-matched projects (from `update_effects.txt`) and clamp extreme outliers.

#### Content generation (AI-driven, modify mod files)
- `generate_content.py` — Generate mod content in three tiers: `easy` (reuse existing effects), `middle` (new tech + child projects), `full` (new equipment + project). Supports `--type heatsink`, `--type radiator`, `--type laser`, `--type drive`, etc. Results cached in `.generate_cache.json`. Use `--dry-run` first, then `--apply`.

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
