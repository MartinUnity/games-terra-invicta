# AI Update Guidelines

Purpose: Describe how an automated process (or AI) can regenerate and update `docs/Projects_Outline.md` from source data.

Steps:

1. Parse `Mods/TIProjectTemplate.json` to extract all project entries (array of objects).
2. Index by `dataName` and capture `friendlyName`, `researchCost`, `prereqs`, and `effects`.
3. Scan all JSON files in `Mods/` (excluding `TIProjectTemplate.json`) for `requiredProjectName` to map mod -> project dependencies.
4. Produce a mermaid `graph LR` with:
   - nodes for each `dataName` labeled by `friendlyName`
   - edges `prereq --> project` for each prereq
   - nodes for mod files and edges `mod --> project` for references
5. For each project, list `researchCost`, `prereqs`, `effects`, and referencing mod file paths.

Formatting rules:

- Use `friendlyName` as section headings and include `dataName` in the heading.
- Keep the mermaid graph near the top for quick visual navigation.
- Use relative paths for mod references (e.g., `Mods/TIGunTemplate.json`).

Automation tips:

- If a `requiredProjectName` points to a missing project, create a placeholder node labeled with the raw identifier.
- Preserve ordering by `friendlyName` or `dataName` for readability.
- Run in the repository root to keep relative paths consistent.

Regeneration command (example):

```bash
python3 -c "<script to parse and write docs/Projects_Outline.md>"
```

If you want, hook this into CI to regenerate docs on changes to `Mods/`.

Regeneration script
-------------------

A helper script `docs/generate_projects_outline.py` was added to automate regenerating `docs/Projects_Outline.md`.

Run it from the repository root:

```bash
python3 docs/generate_projects_outline.py
```

What the script does:

- Parses `Mods/TIProjectTemplate.json` and indexes projects by `dataName`.
- Scans all `Mods/*.json` for `requiredProjectName` references and links mods to projects.
- Generates a mermaid `graph LR` with nodes for projects (including `researchCost`) and edges from `project --> prereq` so projects are shown on the left and their requirements to the right.
- Colors nodes by `techCategory` and writes the final `docs/Projects_Outline.md`.

Tips for automation:

- Add a CI job or pre-commit hook that runs the script and commits the updated `docs/Projects_Outline.md` when `Mods/` changes.
- If you want different colors or node styling, edit `PALETTE` or the `classDef` generation inside `docs/generate_projects_outline.py`.
