# Scripts Overview

This directory contains various Python scripts for managing and developing the Terra Invicta project.

## Main AI Scripts

- **ai_swarm.py**: Manages AI agent communication and orchestration for generating project templates. This script handles the coordination between multiple AI workers, manages retries, and extracts JSON responses from AI models.

- **ai_worker.py**: Core AI worker that interfaces with local Ollama models to generate and validate new project templates. This script handles the actual generation process, including prompt building, model interaction, JSON extraction, and validation of generated candidates.

## Other Useful Scripts

- **check_project_localization.py**: Validates localization files for project templates
- **cleanup_saves.py**: Cleans up old save files and temporary data
- **fix_max_unlock_chance.py**: Adjusts max unlock chance values in project templates
- **generate_scripts_summary.py**: Creates a summary of all available scripts and their purposes
- **generate_weapon.py**: Generates weapon definitions and related data
- **scan_effects.py**: Scans and analyzes effect definitions in the project
- **update_project_description.py**: Updates project descriptions and metadata
- **validate_mods.py**: Validates mod files for correctness and consistency

These scripts are designed to automate various development tasks and maintain project consistency.