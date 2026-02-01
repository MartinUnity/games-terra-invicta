#!/usr/bin/env python3
"""Read-only validator for Mods/TI*.json files.

Checks:
- `Mods/TIProjectTemplate.json` entries must include `dataName`,
  `friendlyName`, `AI_techRole`, and `AI_criticalTech`.
- Other `Mods/TI*.json` files: each item must have `dataName` and `friendlyName`.
- If an item has `requiredProjectName`, it must match a `dataName`
  from `TIProjectTemplate.json`.

Usage: python scripts/validate_mods.py [--mods-dir PATH] [--templates PATH] [--table]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Files to omit from validation (names only)
OMIT_FILES = [
    "TIEffectTemplate.json",
    "TIRegionTemplate.json",
]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def gather_template_issues(templates: List[Dict]) -> Tuple[set, List[Tuple[str, str]]]:
    names = set()
    issues: List[Tuple[str, str]] = []
    for idx, entry in enumerate(templates):
        ctx = f"[{idx}]"
        if not isinstance(entry, dict):
            issues.append((str(idx), "entry is not an object"))
            continue

        dn = entry.get("dataName")
        fn = entry.get("friendlyName")

        if not dn:
            issues.append((ctx, "missing dataName"))
        else:
            names.add(dn)

        if not fn:
            issues.append((ctx, "missing friendlyName"))

        if "AI_techRole" not in entry:
            issues.append((ctx, "missing AI_techRole"))

        if "AI_criticalTech" not in entry:
            issues.append((ctx, "missing AI_criticalTech"))

    return names, issues


def check_file(
    fp: Path, template_names: set, game_names: set, mods_dir: Path, game_templates_dir: Path | None
) -> Tuple[List[str], int, int, int, int, int, int]:
    msgs: List[str] = []
    try:
        obj = load_json(fp)
    except Exception as e:
        msgs.append(f"invalid json: {e}")
        return msgs, 0, 0, 0, 0, 0, 0

    matched_local = 0
    matched_game = 0
    unmatched = 0
    loc_ok_local = 0
    loc_ok_game = 0
    loc_missing = 0

    def check_item(item: Any, ctx: str = "") -> None:
        nonlocal matched_local, matched_game, unmatched
        if not isinstance(item, dict):
            msgs.append(f"{ctx}item is not an object")
            return
        if "dataName" not in item:
            msgs.append(f"{ctx}missing dataName")
        if "friendlyName" not in item:
            msgs.append(f"{ctx}missing friendlyName")
        req = item.get("requiredProjectName")
        if req:
            if req in template_names:
                matched_local += 1
            elif req in game_names:
                matched_game += 1
            else:
                unmatched += 1
                msgs.append(f"{ctx}requiredProjectName '{req}' not found in TIProjectTemplate.json or game templates")

    if isinstance(obj, list):
        for idx, itm in enumerate(obj):
            check_item(itm, ctx=f"[{idx}] ")
    elif isinstance(obj, dict):
        check_item(obj)
    else:
        msgs.append("top-level JSON is neither object nor array")

    # localization checks
    base = fp.stem
    loc_file = mods_dir / "Localization" / "en" / f"{base}.en"
    loc_keys = set()
    if loc_file.exists():
        try:
            with loc_file.open("r", encoding="utf-8") as lf:
                for ln in lf:
                    ln = ln.strip()
                    if not ln or ln.startswith("#"):
                        continue
                    if "=" in ln:
                        k, _ = ln.split("=", 1)
                        loc_keys.add(k.strip())
        except Exception:
            pass

    # determine dataNames and check localization rules
    data_names: List[str] = []
    if isinstance(obj, list):
        for itm in obj:
            if isinstance(itm, dict) and itm.get("dataName"):
                data_names.append(itm.get("dataName"))
    elif isinstance(obj, dict):
        if obj.get("dataName"):
            data_names.append(obj.get("dataName"))

    # try to load a game-specific template file matching this filename (e.g. TIHabModuleTemplate.json)
    game_specific_names: set = set()
    if game_templates_dir:
        gs = game_templates_dir / fp.name
        if gs.exists():
            try:
                gobj = load_json(gs)
                if isinstance(gobj, list):
                    game_specific_names = {t.get("dataName") for t in gobj if isinstance(t, dict) and t.get("dataName")}
            except Exception:
                pass

    loc_missing_examples: List[str] = []
    for dn in data_names:
        # If the dataName exists in the game-specific template file, treat it as game-owned
        # and skip local localization checks (game files have localization).
        if dn in game_specific_names:
            loc_ok_game += 1
            continue
        # If the dataName exists in the general game TIProjectTemplate list, also consider it covered
        if dn in game_names:
            loc_ok_game += 1
            continue

        # rules per file base
        def has(key: str) -> bool:
            return f"{base}.{key}.{dn}" in loc_keys

        ok = False
        if base == "TIProjectTemplate":
            # must have both displayName and summary
            if has("displayName") and has("summary"):
                ok = True
        elif base == "TIShipHullTemplate":
            if has("displayName") and has("abbr"):
                ok = True
        elif base == "TITechTemplate":
            if has("displayName") and has("summary") and has("quote") and has("description"):
                ok = True
        else:
            # generic: either displayName or description required
            if has("displayName") or has("description"):
                ok = True

        if ok:
            loc_ok_local += 1
        else:
            # fallback: if the dataName exists in the game's template list, consider it covered by game
            if dn in game_names:
                loc_ok_game += 1
            else:
                loc_missing += 1
                if len(loc_missing_examples) < 8:
                    loc_missing_examples.append(dn)

    msgs.append(f"matched_local={matched_local}; matched_game={matched_game}; unmatched={unmatched}")
    msgs.append(f"loc_ok_local={loc_ok_local}; loc_ok_game={loc_ok_game}; loc_missing={loc_missing}")
    if loc_missing_examples:
        msgs.append("loc_missing_examples=" + ",".join(loc_missing_examples))
    return msgs, matched_local, matched_game, unmatched, loc_ok_local, loc_ok_game, loc_missing


def print_table(results: List[Tuple[str, bool, List[str]]]) -> None:
    # columns: file, status, messages
    col1 = max((len(r[0]) for r in results), default=10)
    col2 = 7
    header = f"{'File'.ljust(col1)}  {'Status'.ljust(col2)}  Messages"
    print(header)
    print("-" * (col1 + col2 + 12))
    for path, ok, msgs in results:
        status = "OK" if ok else "ERROR"
        msg = "; ".join(msgs) if msgs else ""
        print(f"{path.ljust(col1)}  {status.ljust(col2)}  {msg}")


def main() -> int:
    p = argparse.ArgumentParser(description="Validate Mods TI JSON files (read-only)")
    p.add_argument("--mods-dir", type=Path, default=None, help="Path to Mods directory")
    p.add_argument("--templates", type=Path, default=None, help="Path to TIProjectTemplate.json")
    p.add_argument("--game-templates", type=Path, default=None, help="Path to built-in game TIProjectTemplate.json")
    p.add_argument("--table", action="store_true", help="Show table-like summary")
    p.add_argument("--all", action="store_true", help="Show all files instead of only issues (default shows issues)")
    p.add_argument("--omit", type=str, default=None, help="Comma-separated filenames to omit from validation")
    p.add_argument(
        "--list-overrides", action="store_true", help="List dataNames that override game templates (local+game)"
    )
    p.add_argument(
        "--dump-overrides",
        action="store_true",
        help="Dump compact diff for local vs game overridden dataNames (default: show diff)",
    )
    p.add_argument(
        "--dump-overrides-full",
        action="store_true",
        help="Dump full local and game JSON objects for overridden dataNames",
    )
    args = p.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    mods_dir = args.mods_dir or (repo_root / "Mods")
    template_file = args.templates or (mods_dir / "TIProjectTemplate.json")

    if not mods_dir.exists():
        print(f"Mods directory not found: {mods_dir}")
        return 2

    if not template_file.exists():
        print(f"Template file not found: {template_file}")
        return 2

    try:
        templates = load_json(template_file)
    except Exception as e:
        print(f"Failed to load template file {template_file}: {e}")
        return 2

    if not isinstance(templates, list):
        print(f"Template file {template_file} top-level is not an array/list")
        return 2

    # Load built-in game templates (optional)
    default_game_template = Path.home() / "Games" / "TerraInvicta" / "templates" / "TIProjectTemplate.json"
    game_template_file = args.game_templates or default_game_template
    game_template_names: set = set()
    game_templates_dir: Path | None = None
    if game_template_file:
        if game_template_file.exists() and game_template_file.is_dir():
            game_templates_dir = game_template_file
        elif game_template_file.exists() and game_template_file.is_file():
            # if a specific file was given, treat its parent as the templates directory
            game_templates_dir = game_template_file.parent

    if game_template_file and game_template_file.exists() and game_template_file.is_file():
        try:
            game_templates = load_json(game_template_file)
            if isinstance(game_templates, list):
                game_template_names = {
                    t.get("dataName") for t in game_templates if isinstance(t, dict) and t.get("dataName")
                }
        except Exception:
            game_template_names = set()

    template_names, template_issues = gather_template_issues(templates)

    results: List[Tuple[str, bool, List[str]]] = []

    # Report template file summary
    results.append(
        (
            str(template_file.name),
            len(template_issues) == 0,
            [f"entries={len(templates)}"] + [m for _, m in template_issues],
        )
    )

    # Build omit set
    omit_set = set(OMIT_FILES)
    if args.omit:
        for name in args.omit.split(","):
            n = name.strip()
            if n:
                omit_set.add(n)

    # totals
    total_scanned = 0
    total_matched_local = 0
    total_matched_game = 0
    total_unmatched = 0
    total_loc_ok = 0
    total_loc_ok_game = 0
    total_loc_missing = 0

    # Check other TI*.json files
    for fp in sorted(mods_dir.glob("TI*.json")):
        if fp.resolve() == template_file.resolve():
            continue
        if fp.name in omit_set:
            results.append((str(fp.name), True, ["SKIPPED"]))
            continue
        msgs, ml, mg, mu, lok, lokg, lmissing = check_file(
            fp, template_names, game_template_names, mods_dir, game_templates_dir
        )

        # accumulate totals for scanned files
        total_scanned += 1
        total_matched_local += ml
        total_matched_game += mg
        total_unmatched += mu
        total_loc_ok += lok
        total_loc_ok_game += lokg
        total_loc_missing += lmissing

        # determine if file has issues: either real error messages or localization missing or unmatched requiredProjectName
        real_errors = [
            m
            for m in msgs
            if not (
                m.startswith("matched_local=")
                or m.startswith("matched_game=")
                or m.startswith("loc_ok_local=")
                or m.startswith("loc_ok_game=")
                or m.startswith("loc_missing=")
                or m.startswith("loc_missing_examples=")
                or m == "SKIPPED"
            )
        ]
        issue_present = len(real_errors) > 0 or lmissing > 0 or mu > 0
        results.append((str(fp.name), not issue_present, msgs))

    # Output (default: only show issues unless --all given)
    display_results = results if args.all else [r for r in results if not r[1]]

    if args.table:
        print_table(display_results)
    else:
        # concise listing (only issues by default)
        for path, ok, msgs in display_results:
            if ok:
                print(f"OK: {path}")
            else:
                print(f"ERROR: {path}")
                for m in msgs:
                    print(f"  - {m}")

    # one-line aggregated status
    print(
        f"TIProjectTemplate.json entries: {len(templates)}; scanned_files: {total_scanned}; matched_local: {total_matched_local}; matched_game: {total_matched_game}; unmatched: {total_unmatched}; loc_ok_local: {total_loc_ok}; loc_ok_game: {total_loc_ok_game}; loc_missing: {total_loc_missing}"
    )

    # Optionally list or dump overrides: where a local TI*.json contains the same dataName as the game's matching template file
    if (args.list_overrides or args.dump_overrides or args.dump_overrides_full) and game_templates_dir:
        for fp in sorted(mods_dir.glob("TI*.json")):
            if fp.resolve() == template_file.resolve():
                continue
            gs = game_templates_dir / fp.name
            if not gs.exists():
                continue
            try:
                local_obj = load_json(fp)
                game_obj = load_json(gs)
            except Exception:
                continue
            if not isinstance(local_obj, list) or not isinstance(game_obj, list):
                continue
            local_map = {o.get("dataName"): o for o in local_obj if isinstance(o, dict) and o.get("dataName")}
            game_map = {o.get("dataName"): o for o in game_obj if isinstance(o, dict) and o.get("dataName")}
            overlap = sorted(k for k in local_map.keys() & game_map.keys())
            if not overlap:
                continue
            if args.list_overrides:
                print(f"Overrides in {fp.name}: {', '.join(overlap)}")
            if args.dump_overrides or args.dump_overrides_full:
                for dn in overlap:
                    print(f"--- {fp.name} :: {dn} ---")
                    if args.dump_overrides_full:
                        print("-- LOCAL --")
                        print(json.dumps(local_map[dn], indent=2, ensure_ascii=False))
                        print("-- GAME  --")
                        print(json.dumps(game_map[dn], indent=2, ensure_ascii=False))
                    else:
                        # compact diff: added keys, removed keys, changed keys (show small preview)
                        lobj = local_map[dn]
                        gobj = game_map[dn]
                        lkeys = set(lobj.keys())
                        gkeys = set(gobj.keys())
                        added = sorted(list(lkeys - gkeys))
                        removed = sorted(list(gkeys - lkeys))
                        common = sorted(list(lkeys & gkeys))
                        changed = [k for k in common if lobj.get(k) != gobj.get(k)]
                        if added:
                            print("+ keys in local:", ", ".join(added))
                        if removed:
                            print("- keys in game:", ", ".join(removed))
                        if changed:
                            print("~ changed keys:")
                            for k in changed:
                                lv = json.dumps(lobj.get(k), ensure_ascii=False)
                                gv = json.dumps(gobj.get(k), ensure_ascii=False)

                                def trunc(s: str, n: int = 140) -> str:
                                    s = s.replace("\n", " ")
                                    return s if len(s) <= n else s[: n - 3] + "..."

                                print(f"  {k}: local={trunc(lv)} | game={trunc(gv)}")

    # exit code
    any_errors = any(not ok for _, ok, _ in results)
    return 0 if not any_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
