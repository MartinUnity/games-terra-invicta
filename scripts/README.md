# scripts/ README

This directory contains utility and development scripts used for data validation, content generation, and repository maintenance for the Terra Invicta project. Each entry below gives a short description, typical usage notes, and important behavior to be aware of.

- `ai_swarm.py`
  - Orchestrates batched AI interactions and parsing for generating or evaluating content.
  - Includes helper functions for prompting, JSON extraction, and retry logic.
  - Intended for experimentation and mass-processing; not a production service.
  - Outputs structured candidate artifacts for downstream review/staging.

- `ai_worker.py`
  - Prototype AI worker that calls local models (HTTP/CLI) to generate candidate project entries.
  - Handles staging, JSON extraction, schema validation, and optional auto-apply to Mods.
  - Uses refactored helpers under `scripts/utils` and supports dry-run and backup modes.
  - Designed to be run once or as a scheduled cycle; configurable via CLI flags.

- `check_project_localization.py`
  - Checks `TIProjectTemplate.json` (or a provided JSON) for `dataName` entries and verifies localization keys exist.
  - Loads English `.en` files and prints missing `displayName` / `summary` keys.
  - Exits non-zero when missing keys are found; useful as a CI or pre-merge check.

- `cleanup_saves.py`
  - Manage and archive Terra Invicta save files: keep newest N per type, move older to an archive, and prune archives.
  - Supports a dry-run mode, continuous loop mode, and verbose logging to `scripts/logs`.
  - Configurable via CLI for save/archive paths, retention counts, and intervals.
  - Safe-by-default: logs actions and timestamps; creates a timestamped logfile per run.

- `fix_max_unlock_chance.py`
  - Traverses a project/template JSON and fixes overly-large `factionAvailableChance` values.
  - Replaces values above threshold with randomized sensible defaults (or prints changes in dry-run).
  - Creates a `.bak` backup before writing changes when not in dry-run.
  - Useful for bulk data sanitization after imports or bad merges.

- `generate_scripts_summary.py`
  - Scans the `scripts/` directory and extracts one-line descriptions from module docstrings or leading comments.
  - Generates a Markdown (or plain text) list and can write to a file with `--write`.
  - Excludes internal helper folders and attempts to be conservative in extraction.
  - Helpful for keeping developer-facing summaries up to date.

- `generate_weapon.py`
  - Heuristic and utility functions for generating weapon snippets (guns, lasers) and computing stats.
  - Includes name-generation, example creation, and many domain-specific build/format helpers.
  - Large script intended for experimentation and producing JSON/snippets for the mod templates.
  - Not a library API — treat as a generation tool with many tunable parameters.

- `scan_effects.py`
  - Scans a `TIProjectTemplate.json` (or similar) starting at a marker and counts occurrences of `effects`.
  - Prints a frequency list and attempts to aggregate numeric effect values using an effects template file.
  - Has both JSON-parsing and regex fallback parsing to be robust to non-strict files.
  - Useful to find missing effects, context sums, and template mismatches.

- `update_project_description.py`
  - Uses an LLM (local service like Ollama) to generate concise/consistent project descriptions and summaries.
  - Contains advanced response parsing, NDJSON support, artifact stripping, and safety checks.
  - Provides backup semantics and safe-write helpers; handles batching and health-checks for the model.
  - Intended for controlled generation of human-facing descriptions — review results before applying.

- `validate_mods.py`
  - Validates mod/template JSONs against expected structure and reports issues (missing fields, suspicious values).
  - Prints a tabular summary of findings and can be used in CI to prevent regressions.
  - Performs best-effort checks and includes helpers to produce concise diagnostic messages.
  - Use this to catch structural problems before packaging or applying templates.

Notes
- Most scripts are safe to read and run locally, but several can modify repository files — prefer `--dry-run` and backups when available.
- Many utilities reference companion helpers under `scripts/utils/`; keep those modules available on the Python path when running the scripts.
- Use `python3` and the repository's virtual environment with required dependencies for the AI-related tools.