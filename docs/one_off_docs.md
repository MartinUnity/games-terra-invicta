# Various one-off scripts for generating content, testing ideas, and other non-automated tasks. These are not intended for regular use and may be broken at any time.

## Balance game research based on what effects are used - categorzied into tiers and shifted around to be put in beginning or end of game.

```bash
# Step 1 — see current skew (no AI)
python3 scripts/one_off/balance_prereqs.py --analyze

# Step 2 — full dry-run with AI scoring (will take hours, fully resumable)
python3 scripts/one_off/balance_prereqs.py --dry-run

# Step 3 — once happy with the preview, apply
python3 scripts/one_off/balance_prereqs.py --apply
```

## Generating one-off content

```bash
# Easy — new projects reusing existing effects
python3 scripts/one_off/generate_content.py --tier easy --count 20 --dry-run
python3 scripts/one_off/generate_content.py --tier easy --count 20 --apply

# Middle — new tech gate + 2-4 child projects
python3 scripts/one_off/generate_content.py --tier middle --count 5 --apply
python3 scripts/one_off/generate_content.py --tier middle --count 3 --themes "alien biology" "quantum drives" "social media" --apply

# Full — new equipment + linking research project
python3 scripts/one_off/generate_content.py --tier full --type drive --count 3 --apply
python3 scripts/one_off/generate_content.py --tier full --type laser --count 2 --apply
# Supported types: laser gun magnetic drive powerplant missile particle plasma radiator heatsink armor hab
```