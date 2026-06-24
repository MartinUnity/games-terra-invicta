#!/usr/bin/env python3
"""Score weapons by capability and flag prereq-cost outliers.

Scoring formula:
    score = log10(MJ) * log10(DPS) * efficiency

Higher score means more capable weapon.  Compares score against
total prereq research cost to find weapons that are too easy/hard
to unlock relative to their performance.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from . import (
    GAME_DIR,
    MODS_DIR,
    build_registry,
    parse_num,
    total_prereq_cost,
)


def _rps_from_timing(cooldown: float, salvo: int, intra: float) -> float:
    if salvo <= 0:
        return 0.0
    cycle = cooldown + intra * (salvo - 1)
    if cycle <= 0:
        return float("inf")
    return salvo / cycle


def _score(mj: float, dps: float, efficiency: float) -> float:
    """Compute capability score for a weapon.

    Uses log-scale because MJ and DPS span orders of magnitude.
    Efficiency is applied as a flat multiplier.
    """
    if mj <= 0 or dps <= 0:
        return 0.0
    return math.log10(mj) * math.log10(dps) * efficiency


def _compute_energy(entry: dict, wtype: str) -> float:
    """Compute energy in MJ for a weapon entry.

    For energy weapons (laser, particle): uses shotPower_MJ.
    For plasma weapons: uses expectedDamage_MJ.
    For kinetic weapons (gun, magnetic): uses damage_MJ or computes from
    warheadMass_kg and muzzleVelocity_kps.
    """
    if "damage_MJ" in entry and entry["damage_MJ"]:
        return float(entry["damage_MJ"])
    if "shotPower_MJ" in entry and entry["shotPower_MJ"]:
        return float(entry["shotPower_MJ"])
    if "expectedDamage_MJ" in entry and entry["expectedDamage_MJ"]:
        return float(entry["expectedDamage_MJ"])

    warhead = entry.get("warheadMass_kg")
    muzzle = entry.get("muzzleVelocity_kps")
    if warhead and muzzle:
        return 0.5 * float(warhead) * (float(muzzle) ** 2)

    return 0.0


def _compute_dps(energy_mj: float, entry: dict, wtype: str) -> float:
    """Compute DPS for a weapon entry.

    For energy weapons: DPS = energy / cooldown.
    For kinetic weapons: DPS = damage_in_game * rps.
    For plasma: DPS = energy * rps (since energy is damage_MJ for plasma).
    """
    cooldown = parse_num(entry.get("cooldown_s", entry.get("cooldown", 0)))
    if cooldown <= 0:
        return 0.0

    damage_in_game = energy_mj / 20.0

    if wtype in ("gun", "magnetic"):
        salvo = int(entry.get("salvo_shots", entry.get("salvo", 1)))
        intra = parse_num(entry.get("intraSalvoCooldown_s", entry.get("intra", 0)))
        rps = _rps_from_timing(cooldown, salvo, intra)
    else:
        rps = 1.0 / cooldown

    return damage_in_game * rps


def _detect_type(filepath: Path) -> str:
    """Detect weapon type from filename."""
    name = filepath.name.lower()
    if "gun" in name and "magnetic" not in name:
        return "gun"
    if "magnetic" in name:
        return "magnetic"
    if "laser" in name:
        return "laser"
    if "particle" in name:
        return "particle"
    if "plasma" in name:
        return "plasma"
    return "unknown"


def load_weapon_templates(directory: Path, source: str) -> list[dict]:
    """Load all weapon templates from a directory."""
    weapons: list[dict] = []
    for fp in directory.glob("*WeaponTemplate.json"):
        wtype = _detect_type(fp)
        try:
            with fp.open("r", encoding="utf-8") as f:
                items = json.load(f)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "dataName" in item:
                        item["_source"] = source
                        item["_type"] = wtype
                        weapons.append(item)
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return weapons


def gather_weapons() -> list[dict]:
    """Load all weapon templates from both game and mod directories."""
    game = load_weapon_templates(GAME_DIR, "GAME")
    mod = load_weapon_templates(MODS_DIR, "MOD")
    all_weapons = game + mod

    result = []
    for w in all_weapons:
        wtype = w.get("_type", "unknown")
        energy_mj = _compute_energy(w, wtype)
        dps = _compute_dps(energy_mj, w, wtype)
        efficiency = float(w.get("efficiency", 0)) or 0.0
        project = w.get("requiredProjectName", "")
        friendly = w.get("friendlyName", w.get("displayName", ""))

        result.append({
            "name": w["dataName"],
            "friendly": friendly,
            "type": wtype,
            "energy_mj": round(energy_mj, 2),
            "dps": round(dps, 4),
            "efficiency": efficiency,
            "project": project,
            "source": w.get("_source", "UNKNOWN"),
            "score": _score(energy_mj, dps, efficiency),
        })
    return result


def linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Simple linear regression: y = a*x + b.  Returns (a, b, r²)."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, 0.0, 0.0
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    # r²
    mean_y = sy / n
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (a * x + b)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot else 0.0
    return a, b, r2


def analyze(
    weapons: list[dict], registry: dict[str, dict], flag_threshold: float = 2.0
) -> tuple[list[dict], dict]:
    """Attach prereq costs, compute per-type trend lines, flag outliers.

    Alien-only weapons (name contains "Alien") are excluded from analysis.
    Weapons without valid prereq cost (cost <= 0) are excluded from trend line.

    Performs regression separately per weapon type to avoid mixing
    fundamentally different cost/performance curves.

    Args:
        weapons: list of weapon dicts with 'score' already computed.
        registry: merged project/tech registry for cost lookup.
        flag_threshold: standard deviations from trend to flag (default: 2.0).
    """
    # Attach prereq cost
    for w in weapons:
        project = w.get("project", "")
        if project:
            w["prereq_cost"] = total_prereq_cost(project, registry)
        else:
            w["prereq_cost"] = 0

    # Group by type
    from collections import defaultdict
    by_type: dict[str, list[dict]] = defaultdict(list)
    for w in weapons:
        if "Alien" not in w["name"] and w["score"] > 0 and w["prereq_cost"] > 0:
            by_type[w["type"]].append(w)

    # Per-type regression
    type_regressions: dict[str, dict] = {}
    all_valid = []
    for wtype, group in by_type.items():
        if len(group) < 3:
            continue
        xs = [w["score"] for w in group]
        ys = [w["prereq_cost"] for w in group]
        a, b, r2 = linear_regression(xs, ys)

        # Compute residuals and std
        residuals = [w["prereq_cost"] - (a * w["score"] + b) for w in group]
        mean_r = sum(residuals) / len(residuals)
        std_r = (sum((r - mean_r) ** 2 for r in residuals) / len(residuals)) ** 0.5

        for w in group:
            expected = a * w["score"] + b
            residual = w["prereq_cost"] - expected
            z = residual / std_r if std_r > 0 else 0.0
            w["expected_cost"] = int(expected)
            w["residual"] = int(residual)
            w["z_score"] = round(z, 2)
            w["flagged"] = abs(z) >= flag_threshold
            w["regression_type"] = wtype

        type_regressions[wtype] = {
            "slope": a,
            "intercept": b,
            "r2": round(r2, 4),
            "std_residual": int(std_r),
            "n": len(group),
        }
        all_valid.extend(group)

    if not type_regressions:
        return weapons, {}

    # Aggregate regression summary
    total_n = sum(r["n"] for r in type_regressions.values())
    avg_r2 = sum(r["r2"] for r in type_regressions.values()) / len(type_regressions)
    avg_std = sum(r["std_residual"] for r in type_regressions.values()) / len(type_regressions)

    regression = {
        "type_regressions": type_regressions,
        "total_n": total_n,
        "avg_r2": round(avg_r2, 4),
        "avg_std_residual": int(avg_std),
    }
    return weapons, regression


def print_report(
    weapons: list[dict], regression: dict | None, mod_only: bool = False,
    filter_type: str | None = None
) -> None:
    """Print weapon analysis report."""
    rows = [
        w for w in weapons
        if "Alien" not in w["name"] and w["score"] > 0
    ]
    if mod_only:
        rows = [w for w in rows if w["source"] == "MOD"]
    if filter_type:
        rows = [w for w in rows if w["type"] == filter_type]

    rows.sort(key=lambda w: (w.get("regression_type", "unknown"), w["score"]))

    if regression and "type_regressions" in regression:
        for wtype, reg in sorted(regression["type_regressions"].items()):
            if filter_type and wtype != filter_type:
                continue
            print(
                f"  [{wtype}] cost = {reg['slope']:.0f} * score + {reg['intercept']:.0f}  "
                f"(R²={reg['r2']}, σ={reg['std_residual']:,}, n={reg['n']})"
            )
        print(f"  Overall: {regression['total_n']} weapons, avg R²={regression['avg_r2']}")
        print()
    elif regression:
        print(
            f"Trend line: cost = {regression['slope']:.0f} * score + {regression['intercept']:.0f}  "
            f"(R²={regression['r2']}, σ={regression['std_residual']:,}, n={regression['n']})"
        )
        print()

    # Header
    print(
        f"{'Name':<40} {'Src':>4} {'Type':>8} {'Score':>7} {'Cost':>8} "
        f"{'Expected':>8} {'Resid':>7} {'Z':>5} {'MJ':>8} {'DPS':>6} {'Eff':>5}"
    )
    print("-" * 114)

    flagged: list[dict] = []
    for w in rows:
        cost = w.get("prereq_cost", 0)
        expected = w.get("expected_cost", 0)
        residual = w.get("residual", 0)
        z = w.get("z_score", 0.0)
        tag = " [!]" if w.get("flagged") else ""
        print(
            f"{w['name']:<40} {w['source']:>4} {w['type']:>8} {w['score']:>7.2f} "
            f"{cost:>8,} {expected:>8,} {residual:>+7,} "
            f"{z:>+5.2f} {w['energy_mj']:>8.2f} {w['dps']:>6.4f} "
            f"{w['efficiency']:>5.3f}{tag}"
        )
        if w.get("flagged"):
            flagged.append(w)

    # Summary
    print()
    print(f"Weapons analyzed: {len(rows)}  |  Flagged outliers (|z|≥2.0): {len(flagged)}")
    if flagged:
        print()
        print("=== OUTLIERS ===")
        for w in flagged:
            direction = "UNDER-gated" if w["residual"] < 0 else "OVER-gated"
            project = w.get("project", "N/A")
            print(
                f"  {w['name']}  ({direction}, z={w['z_score']:+.2f})  "
                f"cost={w['prereq_cost']:,}  expected={w['expected_cost']:,}  "
                f"project={project}"
            )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score weapons and flag prereq-cost outliers.")
    parser.add_argument(
        "--mod-only", action="store_true", help="Only analyze mod-added weapons."
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=2.0,
        help="Z-score threshold for flagging outliers (default: 2.0).",
    )
    parser.add_argument(
        "--json", dest="out_json", nargs="?", const=True, default=None,
        help="Output raw data as JSON (to stdout or file).",
    )
    parser.add_argument(
        "--type", dest="filter_type", type=str, default=None,
        help="Only analyze weapons of this type (gun, magnetic, laser, particle, plasma).",
    )
    args = parser.parse_args(argv)

    weapons = gather_weapons()
    registry = build_registry()
    weapons, regression = analyze(weapons, registry, flag_threshold=args.threshold)

    if args.out_json:
        output = weapons
        if args.out_json is True:
            print(json.dumps(output, indent=2, default=str))
        else:
            with open(args.out_json, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, default=str)
            print(f"JSON written to {args.out_json}")
    else:
        print_report(weapons, regression, mod_only=args.mod_only, filter_type=args.filter_type)


if __name__ == "__main__":
    main()
