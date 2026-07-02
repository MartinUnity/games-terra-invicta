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

## Cursor Rules (not found)

## Copilot Rules (not found)

