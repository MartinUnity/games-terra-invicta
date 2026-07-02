#!/bin/bash
# Sync Mods/ to Terra Invicta's enabled mod directory.
# Usage:
#   ./sync_mods.sh           # sync files
#   ./sync_mods.sh --dry-run # show what would be synced without making changes

MODS_DIR="$HOME/src/games/terra-invicta/Mods"
DEST_DIR="$HOME/.local/share/Steam/steamapps/common/Terra Invicta/Mods/Enabled/Zethrok"

if [[ ! -d "$MODS_DIR" ]]; then
  echo "ERROR: Mods directory not found: $MODS_DIR" >&2
  exit 1
fi

if [[ ! -d "$DEST_DIR" ]]; then
  echo "Creating destination directory: $DEST_DIR"
  mkdir -p "$DEST_DIR"
fi

if [[ "${1:-}" == "--dry-run" ]]; then
  echo "Dry run - would sync:"
  echo "  $MODS_DIR/  ->  $DEST_DIR"
  echo
  rsync --dry-run -a --delete -v --exclude='*.bak*' "$MODS_DIR/" "$DEST_DIR"
  echo
  echo "Run without --dry-run to apply."
else
  echo "Syncing:"
  echo "  $MODS_DIR/  ->  $DEST_DIR"
  echo
  rsync -a --delete --exclude='*.bak*' "$MODS_DIR/" "$DEST_DIR"
  echo "Done."
fi
