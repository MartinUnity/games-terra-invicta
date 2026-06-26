#!/usr/bin/env python3
"""
Analyze all effects across projects in TIProjectTemplate.json.

Loads effect definitions from both Mods/ and Game-ModsDir/ TIEffectTemplate.json,
scans every project, and groups effects by context with appropriate value display.

Usage:
    python3 scripts/one_off/analyze_all_effects.py          # all effects
    python3 scripts/one_off/analyze_all_effects.py --ctx EconomyPriority  # filter context
    python3 scripts/one_off/analyze_all_effects.py --raw     # raw values, no conversion
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
PROJECTS_FILE = BASE / "Mods" / "TIProjectTemplate.json"
MODS_EFFECTS = BASE / "Mods" / "TIEffectTemplate.json"
GAME_EFFECTS = BASE / "Game-ModsDir" / "TIEffectTemplate.json"

# Contexts that use raw integer values (not percentages)
RAW_VALUE_CONTEXTS = {
    "HumanLifespan",
    "PherocyteResistance",
    "MCFreeSpaceMineNetwork",
    "ResourceMarketSales",
    "ControlPointMaintenance",
    "AlienHateFromMCUsage",
    "GenericTransferEV_kps",
    "Mission_StealProject_Att",
}

# Contexts that are percentage-based (value is 0.xx = xx%)
PCT_ADDITIVE_CONTEXTS = {
    "EconomyPriority",
    "KnowledgePriority",
    "MilitaryPriority",
    "BuildArmyPriority",
    "WelfarePriority",
    "OppressionPriority",
    "GovernmentPriority",
    "EnvironmentPriority",
    "UnityPriority",
    "SpoilsPriority",
    "HabResearchProduction",
    "LaunchFacilitiesPriority",
    "ShipConstructionTime",
    "BuildSpaceDefensesPriority",
    "ShipOfficerPromotion",
    "TargetingComputerBonus",
    "AllRecruitStats",
    "MissionControlDisruption_PCT",
    "DamageReductionAgainstAllShips",
    "InterrogationBonus",
    "Combat_ShipRepairSpeed",
    "SpaceMiningBonus",
}


def load_effect_definitions() -> dict[str, dict]:
    defs = {}
    for path in [GAME_EFFECTS, MODS_EFFECTS]:
        data = json.load(open(path))
        for eff in data:
            defs[eff["dataName"]] = eff
    return defs


def display_value(effect: dict, raw: bool = False) -> tuple[float, str]:
    """Return (value, unit) for display. Handles different value scales."""
    op = effect.get("operation")
    val = effect.get("value")
    if val is None:
        return (0, "")

    if raw:
        return (val, "")

    contexts = effect.get("contexts", [])
    is_pct_ctx = any(c in PCT_ADDITIVE_CONTEXTS for c in contexts)
    is_raw_ctx = any(c in RAW_VALUE_CONTEXTS for c in contexts)

    if op == "Multiplicative":
        return ((val - 1.0) * 100, "%")
    if op == "Additive" and is_pct_ctx:
        return (val * 100, "%")
    if op == "Additive" and is_raw_ctx:
        return (val, "")
    if op in ("IncreaseToValue", "SetToFixedValue"):
        return (val, "")

    # Default: show as percentage if decimal, raw if integer
    if val < 1:
        return (val * 100, "%")
    return (val, "")


def main() -> None:
    raw_mode = "--raw" in sys.argv
    ctx_filter = None
    for i, arg in enumerate(sys.argv):
        if arg == "--ctx" and i + 1 < len(sys.argv):
            ctx_filter = sys.argv[i + 1]

    defs = load_effect_definitions()

    with open(PROJECTS_FILE) as f:
        projects = json.load(f)

    # Collect: effect_name -> count, effect_name -> sum_value
    counts: dict[str, int] = defaultdict(int)
    sums: dict[str, float] = defaultdict(float)
    units: dict[str, str] = {}

    for proj in projects:
        for eff_name in proj.get("effects", []):
            counts[eff_name] += 1
            eff_def = defs.get(eff_name)
            if eff_def:
                val, unit = display_value(eff_def, raw_mode)
                sums[eff_name] += val
                units[eff_name] = unit

    # Filter by context if requested
    if ctx_filter:
        relevant = set()
        for eff_name in counts:
            eff_def = defs.get(eff_name, {})
            for c in eff_def.get("contexts", []):
                if ctx_filter in c:
                    relevant.add(eff_name)
                    break
        counts = {k: v for k, v in counts.items() if k in relevant}
        sums = {k: v for k, v in sums.items() if k in relevant}

    # --- Per-effect table (numeric first, then non-numeric) ---
    numeric = sorted(
        (e for e in counts if sums.get(e, 0) != 0),
        key=lambda e: abs(sums[e]),
        reverse=True,
    )
    non_numeric = sorted(e for e in counts if sums.get(e, 0) == 0)

    if numeric:
        print(f"{'Effect':<55} {'Count':>5} | {'Sum':>9} | {'Avg':>8} | Context")
        print("-" * 90)
        for eff in numeric:
            s = sums[eff]
            c = counts[eff]
            avg = s / c if c else 0
            unit = units.get(eff, "")
            eff_def = defs.get(eff, {})
            ctxs = "+".join(eff_def.get("contexts", ["?"]))[:25]
            fmt = f"{s:>7.1f}" if unit == "%" else f"{s:>8.1f}"
            avg_fmt = f"{avg:>6.1f}" if unit == "%" else f"{avg:>7.1f}"
            print(f"{eff:<55} {c:>5} | {fmt}{unit:>1} | {avg_fmt}{unit:>1} | {ctxs}")

    # --- Context grouping (numeric) ---
    ctx_counts: dict[str, int] = defaultdict(int)
    ctx_sums: dict[str, float] = defaultdict(float)
    ctx_units: dict[str, str] = {}
    ctx_effects: dict[str, int] = defaultdict(int)

    for eff in numeric:
        s = sums[eff]
        c = counts[eff]
        unit = units.get(eff, "")
        eff_def = defs.get(eff, {})
        seen = set()
        for c_name in eff_def.get("contexts", []):
            if c_name not in seen:
                seen.add(c_name)
                ctx_counts[c_name] += c
                ctx_sums[c_name] += s
                ctx_units[c_name] = unit
                ctx_effects[c_name] += 1

    if ctx_sums:
        print()
        print(f"{'Context':<35} {'Projects':>8} | {'Effects':>7} | {'Total':>10}")
        print("-" * 67)
        for ctx in sorted(ctx_sums, key=lambda c: abs(ctx_sums[c]), reverse=True):
            s = ctx_sums[ctx]
            unit = ctx_units.get(ctx, "")
            fmt = f"{s:>.1f}" if unit == "%" else f"{s:>8.0f}"
            print(
                f"{ctx:<35} {ctx_counts[ctx]:>8} | {ctx_effects[ctx]:>7} "
                f"| {fmt:>9}{unit:>1}"
            )

    # --- Non-numeric effects ---
    if non_numeric:
        print()
        print(f"{'Effect (non-numeric)':<55} {'Count':>5}")
        print("-" * 61)
        for eff in non_numeric:
            eff_def = defs.get(eff, {})
            op = eff_def.get("operation", "?")
            print(f"{eff:<55} {counts[eff]:>5}  ({op})")


if __name__ == "__main__":
    main()
