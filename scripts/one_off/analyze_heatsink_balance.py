#!/usr/bin/env python3
"""Compare heat sink balance: mod entries vs base game with cost correlation."""

import json
import os

SCRIPT_DIR = os.path.dirname(__file__)
MODS_DIR = os.path.join(SCRIPT_DIR, "..", "..", "Mods")
BASE_TEMPLATES = os.path.join(os.path.expanduser("~"), "Games", "TerraInvicta", "templates")

PROJECT_FILE = os.path.join(MODS_DIR, "TIProjectTemplate.json")


def load_json(path):
    with open(path) as f:
        return json.load(f)


def main():
    projects = {}
    with open(PROJECT_FILE) as f:
        for entry in load_json(PROJECT_FILE):
            projects[entry["dataName"]] = entry.get("researchCost", 0)

    base_sinks = load_json(os.path.join(BASE_TEMPLATES, "TIHeatSinkTemplate.json"))
    mod_sinks = load_json(os.path.join(MODS_DIR, "TIHeatSinkTemplate.json"))

    rows = []
    for entry in base_sinks:
        name = entry.get("dataName", "?")
        cap = entry.get("heatCapacity_GJ", 0)
        mass = entry.get("mass_tons", 1)
        proj = entry.get("requiredProjectName", "")
        cost = projects.get(proj, 0)
        rows.append({
            "name": name,
            "source": "base",
            "cap": cap,
            "mass": mass,
            "cap_per_ton": round(cap / mass, 2) if mass else 0,
            "proj": proj,
            "cost": cost,
            "cost_eff": round(cap / cost, 4) if cost else 0,
            "cap_per_cost": round(cap / cost, 2) if cost else 0,
        })

    for entry in mod_sinks:
        name = entry.get("dataName", "?")
        cap = entry.get("heatCapacity_GJ", 0)
        mass = entry.get("mass_tons", 1)
        proj = entry.get("requiredProjectName", "")
        cost = projects.get(proj, 0)
        rows.append({
            "name": name,
            "source": "mod",
            "cap": cap,
            "mass": mass,
            "cap_per_ton": round(cap / mass, 2) if mass else 0,
            "proj": proj,
            "cost": cost,
            "cost_eff": round(cap / cost, 4) if cost else 0,
            "cap_per_cost": round(cap / cost, 2) if cost else 0,
        })

    rows.sort(key=lambda r: (r["cost"], r["name"]))

    # Base game stats for comparison
    base_cap_per_ton = [r["cap_per_ton"] for r in rows if r["source"] == "base"]
    base_cap_per_cost = [r["cap_per_cost"] for r in rows if r["source"] == "base" and r["cost"] > 0]
    avg_cap_ton = sum(base_cap_per_ton) / len(base_cap_per_ton) if base_cap_per_ton else 0
    avg_cap_cost = sum(base_cap_per_cost) / len(base_cap_per_cost) if base_cap_per_cost else 0

    print(f"BASE GAME AVERAGES: cap/ton={avg_cap_ton:.2f}, cap/cost={avg_cap_cost:.4f}")
    print()

    hdr = (
        f"{'Heat Sink':<32} {'Src':>4} {'Cap(GJ)':>8} {'Mass':>6} "
        f"{'Cap/Ton':>8} {'Cost':>8} {'Cap/Cost':>9}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        flag = ""
        if r["source"] == "mod":
            if r["cap_per_ton"] > avg_cap_ton * 1.5:
                flag = " <--over (mass)"
            elif r["cap_per_ton"] < avg_cap_ton * 0.5:
                flag = " <--under (mass)"
            if r["cost"] > 0 and r["cap_per_cost"] > avg_cap_cost * 1.5:
                flag = " <--over (cost)"
        print(
            f"{r['name']:<32} {r['source']:>4} {r['cap']:>8} {r['mass']:>6} "
            f"{r['cap_per_ton']:>8.2f} {r['cost']:>8,} {r['cap_per_cost']:>9.4f}{flag}"
        )

    # Top by capacity per ton
    print("\nTOP 5 BY CAPACITY/TON:")
    by_ton = sorted(rows, key=lambda r: r["cap_per_ton"], reverse=True)
    for i, r in enumerate(by_ton[:5], 1):
        tag = "[MOD]" if r["source"] == "mod" else "[base]"
        print(f"  {i:>2}. {r['name']:<32} {r['cap_per_ton']:>7.2f} GJ/ton  {tag}")

    # Top by capacity per cost
    print("\nTOP 5 BY CAPACITY/COST:")
    by_cost = sorted([r for r in rows if r["cost"] > 0], key=lambda r: r["cap_per_cost"], reverse=True)
    for i, r in enumerate(by_cost[:5], 1):
        tag = "[MOD]" if r["source"] == "mod" else "[base]"
        print(f"  {i:>2}. {r['name']:<32} {r['cap_per_cost']:>7.4f} GJ/cost  {tag}")


if __name__ == "__main__":
    main()
