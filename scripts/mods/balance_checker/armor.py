#!/usr/bin/env python3
"""Score armor by capability and flag prereq-cost outliers.

Scoring formula:
    score = log10(xRayHVL * baryonicHVL) * heatOfVaporization * specialtySum / density

Higher score means more capable armor.  Compares score against
total prereq research cost to find armor that is too easy/hard
to unlock relative to its performance.
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
    load_armor_templates,
    parse_num,
    total_prereq_cost,
)


def _score(xray_hvl: float, baryonic_hvl: float, heat_vap: float, specialties: list[dict], density: float) -> float:
    """Compute capability score for an armor.

    Uses log-scale for HVL because radiation hardness spans orders of magnitude.
    Heat of vaporization is thermal resilience (flat multiplier).
    Specialty sum captures resistance bonuses (excluding "None").
    Density is a mass penalty (higher density = heavier = more ship mass cost).
    """
    if xray_hvl <= 0 or baryonic_hvl <= 0 or density <= 0:
        return 0.0
    spec_sum = sum(s.get("value", 0) for s in specialties if s.get("armorSpecialty", "None") != "None")
    return math.log10(xray_hvl * baryonic_hvl) * heat_vap * spec_sum / density


def gather_armors() -> list[dict]:
    """Load all armor templates from both game and mod directories."""
    game = load_armor_templates(GAME_DIR, "GAME")
    mod = load_armor_templates(MODS_DIR, "MOD")
    all_armors = game + mod

    result = []
    for a in all_armors:
        xray = float(a.get("xRayHalfValue_cm", 0)) or 0.0
        baryonic = float(a.get("baryonicHalfValue_cm", 0)) or 0.0
        density = float(a.get("density_kgm3", 0)) or 0.0
        heat_vap = float(a.get("heatofVaporization_MJkg", 0)) or 0.0
        specialties = a.get("specialties", [])
        project = a.get("requiredProjectName", "")

        result.append({
            "name": a["dataName"],
            "xray_hvl": xray,
            "baryonic_hvl": baryonic,
            "density": density,
            "heat_vap": heat_vap,
            "specialties": specialties,
            "project": project,
            "source": a.get("_source", "UNKNOWN"),
            "score": _score(xray, baryonic, heat_vap, specialties, density),
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
    armors: list[dict], registry: dict[str, dict], flag_threshold: float = 2.0
) -> tuple[list[dict], dict]:
    """Attach prereq costs, compute trend line, flag outliers.

    Alien-only armors (name contains "Alien") are excluded from analysis.
    Armors without valid prereq cost (cost <= 0) are excluded from trend line.

    Args:
        armors: list of armor dicts with 'score' already computed.
        registry: merged project/tech registry for cost lookup.
        flag_threshold: standard deviations from trend to flag (default: 2.0).
    """
    # Attach prereq cost
    for a in armors:
        project = a.get("project", "")
        if project:
            a["prereq_cost"] = total_prereq_cost(project, registry)
        else:
            a["prereq_cost"] = 0

    # Filter: exclude Alien armors and armors with no valid cost
    valid = [
        a for a in armors
        if "Alien" not in a["name"] and a["score"] > 0 and a["prereq_cost"] > 0
    ]
    if not valid:
        return armors, {}

    xs = [a["score"] for a in valid]
    ys = [a["prereq_cost"] for a in valid]
    slope, intercept, r2 = linear_regression(xs, ys)

    # Compute residuals and std
    residuals = [a["prereq_cost"] - (slope * a["score"] + intercept) for a in valid]
    mean_r = sum(residuals) / len(residuals)
    std_r = (sum((r - mean_r) ** 2 for r in residuals) / len(residuals)) ** 0.5

    for a in valid:
        expected = slope * a["score"] + intercept
        residual = a["prereq_cost"] - expected
        z = residual / std_r if std_r > 0 else 0.0
        a["expected_cost"] = int(expected)
        a["residual"] = int(residual)
        a["z_score"] = round(z, 2)
        a["flagged"] = abs(z) >= flag_threshold

    regression = {
        "slope": slope,
        "intercept": intercept,
        "r2": round(r2, 4),
        "std_residual": int(std_r),
        "n": len(valid),
    }
    return armors, regression


def print_report(
    armors: list[dict], regression: dict | None, mod_only: bool = False
) -> None:
    """Print armor analysis report."""
    rows = [
        a for a in armors
        if "Alien" not in a["name"] and a["score"] > 0
    ]
    if mod_only:
        rows = [a for a in rows if a["source"] == "MOD"]

    rows.sort(key=lambda a: a["score"])

    if regression:
        print(
            f"Trend line: cost = {regression['slope']:.0f} * score + {regression['intercept']:.0f}  "
            f"(R²={regression['r2']}, σ={regression['std_residual']:,}, n={regression['n']})"
        )
        print()

    # Header
    print(
        f"{'Name':<35} {'Src':>4} {'Score':>10} {'Cost':>8} "
        f"{'Expected':>8} {'Resid':>7} {'Z':>5} "
        f"{'XrayHVL':>6} {'BaryHVL':>6} {'Density':>7} {'HeatVap':>7} {'SpecSum':>7}"
    )
    print("-" * 124)

    flagged: list[dict] = []
    for a in rows:
        cost = a.get("prereq_cost", 0)
        expected = a.get("expected_cost", 0)
        residual = a.get("residual", 0)
        z = a.get("z_score", 0.0)
        tag = " [!]" if a.get("flagged") else ""
        spec_sum = sum(s.get("value", 0) for s in a.get("specialties", []) if s.get("armorSpecialty", "None") != "None")
        print(
            f"{a['name']:<35} {a['source']:>4} {a['score']:>10.2f} "
            f"{cost:>8,} {expected:>8,} {residual:>+7,} "
            f"{z:>+5.2f} "
            f"{a['xray_hvl']:>6.1f} {a['baryonic_hvl']:>6.1f} "
            f"{a['density']:>7.0f} {a['heat_vap']:>7.1f} {spec_sum:>7.2f}{tag}"
        )
        if a.get("flagged"):
            flagged.append(a)

    # Summary
    print()
    print(f"Armors analyzed: {len(rows)}  |  Flagged outliers (|z|≥2.0): {len(flagged)}")
    if flagged:
        print()
        print("=== OUTLIERS ===")
        for a in flagged:
            direction = "UNDER-gated" if a["residual"] < 0 else "OVER-gated"
            project = a.get("project", "N/A")
            print(
                f"  {a['name']}  ({direction}, z={a['z_score']:+.2f})  "
                f"cost={a['prereq_cost']:,}  expected={a['expected_cost']:,}  "
                f"project={project}"
            )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score armor and flag prereq-cost outliers.")
    parser.add_argument(
        "--mod-only", action="store_true", help="Only analyze mod-added armor."
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
    args = parser.parse_args(argv)

    armors = gather_armors()
    registry = build_registry()
    armors, regression = analyze(armors, registry, flag_threshold=args.threshold)

    if args.out_json:
        output = armors
        if args.out_json is True:
            print(json.dumps(output, indent=2, default=str))
        else:
            with open(args.out_json, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, default=str)
            print(f"JSON written to {args.out_json}")
    else:
        print_report(armors, regression, mod_only=args.mod_only)


if __name__ == "__main__":
    main()
