#!/usr/bin/env python3
"""Compare radiator balance: mod entries vs base game with cost correlation."""

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

    base_rads = load_json(os.path.join(BASE_TEMPLATES, "TIRadiatorTemplate.json"))
    mod_rads = load_json(os.path.join(MODS_DIR, "TIRadiatorTemplate.json"))

    rows = []
    for entry in base_rads:
        name = entry.get("dataName", "?")
        sp = entry.get("specificPower_2s_KWkg", 0)
        temp = entry.get("operatingTemp_K", 0)
        vuln = entry.get("vulnerability", 0)
        collector = entry.get("collector", False)
        rtype = entry.get("radiatorType", "?")
        proj = entry.get("requiredProjectName", "")
        cost = projects.get(proj, 0)
        rows.append({
            "name": name,
            "source": "base",
            "sp": sp,
            "temp": temp,
            "vuln": vuln,
            "collector": collector,
            "type": rtype,
            "proj": proj,
            "cost": cost,
            "sp_per_cost": round(sp / cost, 6) if cost else 0,
        })

    for entry in mod_rads:
        name = entry.get("dataName", "?")
        sp = entry.get("specificPower_2s_KWkg", 0)
        temp = entry.get("operatingTemp_K", 0)
        vuln = entry.get("vulnerability", 0)
        collector = entry.get("collector", False)
        rtype = entry.get("radiatorType", "?")
        proj = entry.get("requiredProjectName", "")
        cost = projects.get(proj, 0)
        rows.append({
            "name": name,
            "source": "mod",
            "sp": sp,
            "temp": temp,
            "vuln": vuln,
            "collector": collector,
            "type": rtype,
            "proj": proj,
            "cost": cost,
            "sp_per_cost": round(sp / cost, 6) if cost else 0,
        })

    rows.sort(key=lambda r: (r["cost"], r["name"]))

    # Base game stats for comparison
    base_sp = [r["sp"] for r in rows if r["source"] == "base"]
    base_sp_cost = [r["sp_per_cost"] for r in rows if r["source"] == "base" and r["cost"] > 0]
    avg_sp = sum(base_sp) / len(base_sp) if base_sp else 0
    avg_sp_cost = sum(base_sp_cost) / len(base_sp_cost) if base_sp_cost else 0

    print(f"BASE GAME AVERAGES: specificPower={avg_sp:.1f} KW/kg, sp/cost={avg_sp_cost:.6f}")
    print()

    hdr = (
        f"{'Radiator':<32} {'Src':>4} {'KW/kg':>6} {'TempK':>5} "
        f"{'Vuln':>4} {'Coll':>4} {'Type':<8} {'Cost':>8} {'SP/Cost':>10}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        coll = "Y" if r["collector"] else "-"
        flag = ""
        if r["source"] == "mod":
            if r["sp"] > avg_sp * 1.5:
                flag = " <--over (power)"
            elif r["sp"] < avg_sp * 0.5:
                flag = " <--under (power)"
            if r["cost"] > 0 and r["sp_per_cost"] > avg_sp_cost * 1.5:
                flag = " <--over (cost)"
        print(
            f"{r['name']:<32} {r['source']:>4} {r['sp']:>6.1f} {r['temp']:>5} "
            f"{r['vuln']:>4} {coll:>4} {r['type']:<8} {r['cost']:>8,} "
            f"{r['sp_per_cost']:>10.6f}{flag}"
        )

    # Vulnerability breakdown
    print("\nVULNERABILITY TIERS:")
    for tier in [1, 2, 3, 5, 10, 20, 30]:
        tier_rads = [r for r in rows if r["vuln"] == tier]
        if tier_rads:
            names = ", ".join(f"{r['name']}[{r['source']}]" for r in tier_rads)
            print(f"  vuln={tier}: {names}")

    # Top by specific power
    print("\nTOP 5 BY SPECIFIC POWER (KW/kg):")
    by_sp = sorted(rows, key=lambda r: r["sp"], reverse=True)
    for i, r in enumerate(by_sp[:5], 1):
        tag = "[MOD]" if r["source"] == "mod" else "[base]"
        print(f"  {i:>2}. {r['name']:<32} {r['sp']:>6.1f} KW/kg  {tag}  (vuln={r['vuln']})")

    # Top by specific power per cost
    print("\nTOP 5 BY SPECIFIC POWER/COST:")
    by_cost = sorted([r for r in rows if r["cost"] > 0], key=lambda r: r["sp_per_cost"], reverse=True)
    for i, r in enumerate(by_cost[:5], 1):
        tag = "[MOD]" if r["source"] == "mod" else "[base]"
        print(f"  {i:>2}. {r['name']:<32} {r['sp_per_cost']:>10.6f}  {tag}")


if __name__ == "__main__":
    main()
