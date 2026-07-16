# AGENTS.md

## Build/Lint/Test Commands

### General

- **Build**: `pip install -e .` (Install package in editable mode)
- **Lint**: `flake8` (PEP8 compliance + type hints)
- **Test**: `pytest` (with pytest framework)

### Single Test
Run a specific test: `pytest --pyargs your.module.test_name`

### Post-Edit: Sync Mods

After modifying any file in `Mods/` (`.json` or `.en`), always run:
```bash
./sync_mods.sh
```
This rsyncs changes to the game's active mod directory.

## Code Style Guidelines

### Formatting
- Use 4 spaces for indentation
- 79 characters max line length
- Black for auto-formatting (run `black .`)
- Isort for import sorting (run `isort .`)

### Types
- Use Python 3.10+ type hints
- Prefer `@typing` packages over custom definitions
- Use `TypeGuard` for runtime type checking

### Imports
- Relative imports: `./utils/helper.py`
- Absolute imports: `package.submodule` (from root)
- Group imports by category:
  ```py
  from typing import List, Tuple, Optional
  import os
  import sys
  ```

### Naming
- Functions: snake_case (`fetch_user_data`)
- Classes: PascalCase (`UserService`)
- Files: snake_case (`user_utils.py`)
- Constants: UPPERCASE (`MAX_RETRIES`)

### Error Handling
- Use `try/except` for async operations
- Prefer `Result` pattern from `typing_extensions`
- Use `logging.error()` for unhandled exceptions

## Localization Format Specifiers

Terra Invicta uses `{N}` placeholders in `.en` localization files. The number determines how the value is formatted:

| Specifier | Meaning | Example (value=1.12) | Use For |
|-----------|---------|---------------------|---------|
| `{0}` | raw value | `1.12` | integers, counts |
| `{3}` | value to % (value × 100) | `112%` | Additive percentage effects (value=0.12 → `12%`) |
| `{4}` | value to % decrease | `-12%` | percentage decreases |
| `{8}` | value - 1 to % ((value-1) × 100) | `+12%` | Multiplicative percentage effects (value=1.12 → `+12%`) |
| `{18}` | inverse multiplicative % ((1/value - 1) × 100) | `176%` | T4S internal for Multiplicative with value < 1 (e.g., value=0.5 → `100%` increase) |
| `{9}` | nation displayName | `France` | nation names |
| `{1}` | 1st target displayName | `target name` | target names |
| `{2}` | 2nd target displayName | `target name` | secondary target names |
| `{5}` | nation with preposition | `in France` | nation locations |
| `{7}` | duration in months | `12` | time durations |

**Critical rule**: Multiplicative effects (e.g., `value: 1.12` for +12%) require `{8}`, not `{3}`. Using `{3}` displays `112%` instead of `+12%`.

Reference: `Game-ModsDir-Localization/TIEffectTemplate.en` (inline `// N: ...` comments)

## Cursor Rules (not found)

## Copilot Rules (not found)

