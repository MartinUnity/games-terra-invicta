# ai-worker

This repository contains a small prototype worker that generates candidate projects/techs for Terra Invicta using a local Ollama model.

Quick start

- Install simple Python deps: `pip install -r ai-worker/requirements.txt`.
- Try a single dry-run cycle:

```bash
python3 scripts/ai_worker.py --once --dry-run
```

Files
- `ai-worker/config.yml`: default configuration.
- `ai-worker/prompt_templates.md`: prompt + schema templates used to instruct the model.
- `ai-worker/staging/`: where generated candidate JSON and patches are written.
- `scripts/ai_worker.py`: prototype worker that calls Ollama CLI, validates minimal fields, and writes staged output.

Notes
- By default the worker runs in `dry_run` mode and will only produce a JSON candidate in the staging directory. It will not modify `Mods/`.
- You should review generated candidates before applying them to the live `Mods/` directory. The script supports an `--auto-apply` flag in future iterations but defaults to caution.
