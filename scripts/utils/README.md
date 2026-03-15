# scripts/utils/ README

This directory contains helper modules used by the Terra Invicta project scripts.
Each module provides specific functionality to support data processing, AI interactions,
and repository maintenance tasks.

- `ai_prompts.py`
  - Contains helper functions for building prompts for AI model interactions.
  - Includes functions to generate fill prompts (for friendly names) and localization prompts.
  - Provides both strict and simplified prompt formats to aid JSON extraction from models.

- `ai_runner.py`
  - Implements the core logic for running AI generation cycles.
  - Handles template selection, cost estimation, and candidate generation with retries.
  - Manages staging, validation, and backup operations for generated candidates.

- `ai_selection.py`
  - Contains functions for selecting appropriate project templates and effects.
  - Implements logic to match templates with effect whitelists and handle prerequisites.
  - Provides fallback mechanisms when specific requirements cannot be met.

- `ai_worker_helpers.py`
  - Offers a collection of utility functions for AI worker operations.
  - Includes JSON extraction, model calling (HTTP/CLI), validation, and file management helpers.
  - Contains functions for loading templates, collecting effects, and managing staging directories.

- `mining_leveler.py`
  - Provides functionality to map research costs to mining bonus level suffixes (_lvl1.._lvl6).
  - Centralizes the thresholds used for determining appropriate level suffixes.
  - Includes functions to determine levels based on cost and apply suffixes to effect names.
