#!/usr/bin/env python3
"""Cleanup Terra Invicta savefiles.

Usage examples:
  # dry-run once
  python3 scripts/cleanup_saves.py --dry-run --once

  # run continuously every 5 minutes
  python3 scripts/cleanup_saves.py

This script will:
 - keep the newest N saves per save-type in `terra-invicta-save/Saves/` (default 5)
 - move older saves into `archive/savegames/<type>/`
 - keep at most M saves per type in the archive (default 50) and delete oldest beyond that
"""
import argparse
import datetime
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAVE_DIR = ROOT / "terra-invicta-save" / "Saves"
DEFAULT_ARCHIVE = ROOT / "archive" / "savegames"
LOG_DIR = ROOT / "scripts" / "logs"

SAVE_RE = re.compile(r"^([A-Za-z]+)save(\d+?)_(\d{4}-\d{1,2}-\d{1,2})\.gz$")


def find_save_files(base_dir: Path):
    files = []
    if not base_dir.exists():
        return files
    for p in base_dir.iterdir():
        if not p.is_file():
            continue
        m = SAVE_RE.match(p.name)
        if m:
            save_type = m.group(1)
            files.append((save_type, p))
    return files


def ensure_dir(p: Path, dry_run: bool = False):
    if dry_run:
        return
    p.mkdir(parents=True, exist_ok=True)


def move_file(src: Path, dst: Path, dry_run: bool = False):
    ensure_dir(dst.parent, dry_run=dry_run)
    if dry_run:
        return True
    try:
        shutil.move(str(src), str(dst))
        logging.info(f"Moved {src} -> {dst}")
        return True
    except Exception as e:
        logging.error(f"ERROR moving {src} -> {dst}: {e}")
        return False


def prune_archive(arch_dir: Path, save_type: str, max_keep: int, dry_run: bool = False):
    deleted = 0
    target = arch_dir / save_type
    if not target.exists():
        return deleted
    files = sorted([p for p in target.iterdir() if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=False)
    # files sorted oldest->newest; delete oldest while len > max_keep
    while len(files) > max_keep:
        oldest = files.pop(0)
        if dry_run:
            deleted += 1
        else:
            try:
                oldest.unlink()
                logging.info(f"Deleted archived: {oldest}")
                deleted += 1
            except Exception as e:
                logging.error(f"ERROR deleting {oldest}: {e}")
    return deleted


def process_once(save_dir: Path, archive_dir: Path, keep: int, max_archive: int, dry_run: bool = False):
    files = find_save_files(save_dir)
    by_type = {}
    for t, p in files:
        by_type.setdefault(t, []).append(p)

    total_moved = 0
    total_deleted = 0

    for t, plist in by_type.items():
        # sort by modification time descending (newest first)
        plist_sorted = sorted(plist, key=lambda p: p.stat().st_mtime, reverse=True)
        keep_set = set(plist_sorted[:keep])
        to_archive = [p for p in plist_sorted[keep:]]
        if to_archive and not dry_run:
            logging.info(f"Type {t}: keeping {len(keep_set)} newest, archiving {len(to_archive)} files")
        for p in to_archive:
            dest = archive_dir / t / p.name
            ok = move_file(p, dest, dry_run=dry_run)
            if ok:
                total_moved += 1
        # prune archive if necessary
        deleted = prune_archive(archive_dir, t, max_archive, dry_run=dry_run)
        total_deleted += deleted

    # summary output (concise) with timestamp on the left
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if dry_run:
        print(f"{now} DRY: Would move {total_moved} files into archive, delete {total_deleted} files from archive")
    # else:
    # print(f"{now} Moved {total_moved} files into archive, deleted {total_deleted} files from archive")
    if not dry_run and (total_moved > 0 or total_deleted > 0):
        print(f"{now} Moved {total_moved} files into archive, deleted {total_deleted} files from archive")
        logging.info(f"Summary: moved={total_moved} deleted={total_deleted}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cleanup Terra Invicta savefiles")
    parser.add_argument("--save-dir", default=str(SAVE_DIR), help="Path to Saves directory")
    parser.add_argument("--archive-dir", default=str(DEFAULT_ARCHIVE), help="Where to move archived saves")
    parser.add_argument("--keep", type=int, default=5, help="How many latest saves to keep in place per type")
    parser.add_argument("--max-archive", type=int, default=50, help="Max saves to keep in archive per type")
    parser.add_argument("--dry-run", action="store_true", help="Don't move or delete, just print actions")
    parser.add_argument("--interval", type=int, default=300, help="Loop interval in seconds when running continuously")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    save_dir = Path(args.save_dir)
    archive_dir = Path(args.archive_dir)

    # ensure log directory exists and configure logging to a timestamped file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"cleanup_{now}.log"
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        filename=str(log_file),
        level=level,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    # if not verbose, keep console output minimal (we print summary explicitly)
    if args.dry_run:
        print("DRY RUN: no files will be moved or deleted")

    if args.once:
        process_once(save_dir, archive_dir, args.keep, args.max_archive, dry_run=args.dry_run)
        return 0

    try:
        while True:
            process_once(save_dir, archive_dir, args.keep, args.max_archive, dry_run=args.dry_run)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Interrupted, exiting")
        return 0


if __name__ == "__main__":
    sys.exit(main())
