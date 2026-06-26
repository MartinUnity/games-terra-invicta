#!/usr/bin/env python3
"""Score drives by capability and flag prereq-cost outliers.

Scoring formula:
    score = log10(EV_kps) * log10(thrust_N) * efficiency

Higher score means more capable drive.  Compares score against
total prereq research cost to find drives that are too easy/hard
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
    load_drive_templates,
    parse_num,
    total_prereq_cost,
)


def _score(ev: float, thrust: float, efficiency: float) -> float:
    """Compute capability score for a drive.

    Uses log-scale because EV and thrust span 4-5 orders of magnitude.
    Efficiency is applied as a flat multiplier.
    """
    if ev <= 0 or thrust <= 0:
        return 0.0
    return math.log10(ev) * math.log10(thrust) * efficiency


def gather_x1_drives() -> list[dict]:
    """Load all x1 drives from both game and mod directories."""
    game = load_drive_templates(GAME_DIR, "GAME")
    mod = load_drive_templates(MODS_DIR, "MOD")
    all_drives = game + mod
    x1_drives = [d for d in all_drives if d.get("thrusters") == 1]
    result = []
    for d in x1_drives:
        ev = float(d.get("EV_kps", 0)) or 0.0
        thrust = float(d.get("thrust_N", 0)) or 0.0
        eff = float(d.get("efficiency", 0)) or 0.0
        power = parse_num(d.get("req power", 0))
        project = d.get("requiredProjectName", "")
        result.append({
            "name": d["dataName"],
            "ev": ev,
            "thrust": thrust,
            "efficiency": eff,
            "power_mw": power,
            "project": project,
            "classification": d.get("driveClassification", ""),
            "source": d.get("_source", "UNKNOWN"),
            "score": _score(ev, thrust, eff),
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
    drives: list[dict], registry: dict[str, dict], flag_threshold: float = 2.0
) -> tuple[list[dict], dict]:
    """Attach prereq costs, compute trend line, flag outliers.

    Alien-only drives (name contains "Alien") are excluded from analysis.
    Drives without valid prereq cost (cost <= 0) are excluded from trend line.

    Args:
        drives: list of drive dicts with 'score' already computed.
        registry: merged project/tech registry for cost lookup.
        flag_threshold: standard deviations from trend to flag (default: 2.0).
    """
    # Attach prereq cost
    for d in drives:
        project = d.get("project", "")
        if project:
            d["prereq_cost"] = total_prereq_cost(project, registry)
        else:
            d["prereq_cost"] = 0

    # Filter: exclude Alien drives and drives with no valid cost
    valid = [
        d for d in drives
        if "Alien" not in d["name"] and d["score"] > 0 and d["prereq_cost"] > 0
    ]
    if not valid:
        return drives, {}

    xs = [d["score"] for d in valid]
    ys = [d["prereq_cost"] for d in valid]
    a, b, r2 = linear_regression(xs, ys)

    # Compute residuals and std
    residuals = [d["prereq_cost"] - (a * d["score"] + b) for d in valid]
    mean_r = sum(residuals) / len(residuals)
    std_r = (sum((r - mean_r) ** 2 for r in residuals) / len(residuals)) ** 0.5

    for d in valid:
        expected = a * d["score"] + b
        residual = d["prereq_cost"] - expected
        z = residual / std_r if std_r > 0 else 0.0
        d["expected_cost"] = int(expected)
        d["residual"] = int(residual)
        d["z_score"] = round(z, 2)
        d["flagged"] = abs(z) >= flag_threshold

    regression = {
        "slope": a,
        "intercept": b,
        "r2": round(r2, 4),
        "std_residual": int(std_r),
        "n": len(valid),
    }
    return drives, regression


def print_report(
    drives: list[dict], regression: dict | None, mod_only: bool = False
) -> None:
    """Print drive analysis report."""
    rows = [
        d for d in drives
        if "Alien" not in d["name"] and d["score"] > 0
    ]
    if mod_only:
        rows = [d for d in rows if d["source"] == "MOD"]

    rows.sort(key=lambda d: d["score"])

    if regression:
        print(
            f"Trend line: cost = {regression['slope']:.0f} * score + {regression['intercept']:.0f}  "
            f"(R²={regression['r2']}, σ={regression['std_residual']:,}, n={regression['n']})"
        )
        print()

    # Header
    print(
        f"{'Name':<45} {'Src':>4} {'Score':>7} {'Cost':>8} "
        f"{'Expected':>8} {'Resid':>7} {'Z':>5} {'EV':>6} {'Thrust':>10} {'Eff':>5}"
    )
    print("-" * 108)

    flagged: list[dict] = []
    for d in rows:
        cost = d.get("prereq_cost", 0)
        expected = d.get("expected_cost", 0)
        residual = d.get("residual", 0)
        z = d.get("z_score", 0.0)
        tag = " [!]" if d.get("flagged") else ""
        print(
            f"{d['name']:<45} {d['source']:>4} {d['score']:>7.2f} "
            f"{cost:>8,} {expected:>8,} {residual:>+7,} "
            f"{z:>+5.2f} {d['ev']:>6.0f} {d['thrust']:>10,.0f} "
            f"{d['efficiency']:>5.3f}{tag}"
        )
        if d.get("flagged"):
            flagged.append(d)

    # Summary
    print()
    print(f"Drives analyzed: {len(rows)}  |  Flagged outliers (|z|≥2.0): {len(flagged)}")
    if flagged:
        print()
        print("=== OUTLIERS ===")
        for d in flagged:
            direction = "UNDER-gated" if d["residual"] < 0 else "OVER-gated"
            project = d.get("project", "N/A")
            print(
                f"  {d['name']}  ({direction}, z={d['z_score']:+.2f})  "
                f"cost={d['prereq_cost']:,}  expected={d['expected_cost']:,}  "
                f"project={project}"
            )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score drives and flag prereq-cost outliers.")
    parser.add_argument(
        "--mod-only", action="store_true", help="Only analyze mod-added drives."
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

    drives = gather_x1_drives()
    registry = build_registry()
    drives, regression = analyze(drives, registry, flag_threshold=args.threshold)

    if args.out_json:
        output = drives
        if args.out_json is True:
            print(json.dumps(output, indent=2, default=str))
        else:
            with open(args.out_json, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, default=str)
            print(f"JSON written to {args.out_json}")
    else:
        print_report(drives, regression, mod_only=args.mod_only)


if __name__ == "__main__":
    main()