# cleanup_saves.py

Small helper to keep Terra Invicta save folders tidy.

Location
- Script: `scripts/cleanup_saves.py`
- Saves directory (by default): `terra-invicta-save/Saves/`
- Archive directory (by default): `archive/savegames/`

What it does
- Keeps the newest N saves per save-type in the Saves directory (default: 5).
- Moves older saves into `archive/savegames/<type>/`.
- Keeps at most M saves per type in the archive (default: 50) and deletes the oldest beyond that.

Quick usage
- Dry-run once (verify actions):
```bash
python3 scripts/cleanup_saves.py --dry-run --once
```

- Run once (perform moves/deletes):
```bash
python3 scripts/cleanup_saves.py --once
```

- Run continuously every 5 minutes (default):
```bash
python3 scripts/cleanup_saves.py
```

Configuration
- Command-line flags:
  - `--keep`: how many latest saves to keep in place per type (default 5)
  - `--max-archive`: max saves to keep per type in archive (default 50)
  - `--save-dir` / `--archive-dir`: override paths

Notes
- Recommended workflow: run a dry-run first to confirm behavior, then run `--once` before starting a long play session.
- The script is safe to run manually and is idempotent: repeated runs will only move/delete according to the configured policy.
- If you later want automatic scheduling, you can add a cron entry or a systemd timer; ask me and I can provide examples.
