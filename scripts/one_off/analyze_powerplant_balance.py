#!/usr/bin/env python3
"""Compare power plant balance: mod entries vs base game with cost correlation."""

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

    base_plants = load_json(os.path.join(BASE_TEMPLATES, "TIPowerPlantTemplate.json"))
    mod_plants = load_json(os.path.join(MODS_DIR, "TIPowerPlantTemplate.json"))

    rows = []
    for entry in base_plants:
        name = entry.get("dataName", "?")
        max_out = entry.get("maxOutput_GW", 0)
        sp_tgw = entry.get("specificPower_tGW", 0)
        eff = entry.get("efficiency", 0)
        crew = entry.get("crew", 0)
        pclass = entry.get("powerPlantClass", "?")
        proj = entry.get("requiredProjectName", "")
        cost = projects.get(proj, 0)
        rows.append({
            "name": name,
            "source": "base",
            "max_out": max_out,
            "sp_tgw": sp_tgw,
            "eff": eff,
            "crew": crew,
            "class": pclass,
            "proj": proj,
            "cost": cost,
            "out_per_cost": round(max_out / cost, 4) if cost else 0,
            "eff_adj": round(eff * max_out / cost, 4) if cost else 0,
        })

    for entry in mod_plants:
        name = entry.get("dataName", "?")
        max_out = entry.get("maxOutput_GW", 0)
        sp_tgw = entry.get("specificPower_tGW", 0)
        eff = entry.get("efficiency", 0)
        crew = entry.get("crew", 0)
        pclass = entry.get("powerPlantClass", "?")
        proj = entry.get("requiredProjectName", "")
        cost = projects.get(proj, 0)
        rows.append({
            "name": name,
            "source": "mod",
            "max_out": max_out,
            "sp_tgw": sp_tgw,
            "eff": eff,
            "crew": crew,
            "class": pclass,
            "proj": proj,
            "cost": cost,
            "out_per_cost": round(max_out / cost, 4) if cost else 0,
            "eff_adj": round(eff * max_out / cost, 4) if cost else 0,
        })

    rows.sort(key=lambda r: (r["cost"], r["name"]))

    # Base game stats for comparison
    base_eff = [r["eff"] for r in rows if r["source"] == "base"]
    base_out_cost = [r["out_per_cost"] for r in rows if r["source"] == "base" and r["cost"] > 0]
    avg_eff = sum(base_eff) / len(base_eff) if base_eff else 0
    avg_out_cost = sum(base_out_cost) / len(base_out_cost) if base_out_cost else 0

    print(f"BASE GAME AVERAGES: efficiency={avg_eff:.3f}, output/cost={avg_out_cost:.4f}")
    print()

    hdr = (
        f"{'Power Plant':<40} {'Src':>4} {'MaxGW':>10} {'SP(tGW)':>8} "
        f"{'Eff':>5} {'Crew':>4} {'Class':<24} {'Cost':>8} {'Out/Cost':>9}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        flag = ""
        if r["source"] == "mod":
            if r["eff"] > avg_eff * 1.1:
                flag = f" <--over (eff={r['eff']:.3f} vs {avg_eff:.3f})"
            if r["cost"] > 0 and r["out_per_cost"] > avg_out_cost * 2:
                flag = " <--over (cost)"
            if r["cost"] > 0 and r["out_per_cost"] < avg_out_cost * 0.3:
                flag = " <--under (cost)"
        print(
            f"{r['name']:<40} {r['source']:>4} {r['max_out']:>10,.1f} {r['sp_tgw']:>8.4f} "
            f"{r['eff']:>5.3f} {r['crew']:>4} {r['class']:<24} {r['cost']:>8,} "
            f"{r['out_per_cost']:>9.4f}{flag}"
        )

    # Power class breakdown
    print("\nPOWER PLANT CLASSES (mod vs base comparison):")
    classes = {}
    for r in rows:
        classes.setdefault(r["class"], {"base": [], "mod": []})
        classes[r["class"]][r["source"]].append(r)

    for cls, data in sorted(classes.items()):
        print(f"\n  {cls}:")
        for src in ("base", "mod"):
            items = data[src]
            if not items:
                continue
            effs = [i["eff"] for i in items]
            outs = [i["max_out"] for i in items]
            print(
                f"    [{src.upper()}] count={len(items)}, "
                f"eff=[{min(effs):.3f}-{max(effs):.3f}], "
                f"output=[{min(outs):.1f}-{max(outs):.1f}] GW"
            )

    # Top by output per cost
    print("\nTOP 10 BY OUTPUT/COST:")
    by_cost = sorted([r for r in rows if r["cost"] > 0], key=lambda r: r["out_per_cost"], reverse=True)
    for i, r in enumerate(by_cost[:10], 1):
        tag = "[MOD]" if r["source"] == "mod" else "[base]"
        print(
            f"  {i:>2}. {r['name']:<40} {r['out_per_cost']:>9.4f} out/cost  {tag}  "
            f"(GW={r['max_out']:,.1f}, eff={r['eff']:.3f})"
        )

    # Top by efficiency-adjusted output/cost
    print("\nTOP 10 BY EFFICIENCY-ADJUSTED OUTPUT/COST:")
    by_adj = sorted([r for r in rows if r["cost"] > 0], key=lambda r: r["eff_adj"], reverse=True)
    for i, r in enumerate(by_adj[:10], 1):
        tag = "[MOD]" if r["source"] == "mod" else "[base]"
        print(
            f"  {i:>2}. {r['name']:<40} {r['eff_adj']:>9.4f} adj  {tag}  "
            f"(GW={r['max_out']:,.1f}, eff={r['eff']:.3f})"
        )

    # Mod plants that share class with base plants
    print("\nMOD PLANTS COMPARED TO BASE GAME (same class):")
    for r in [x for x in rows if x["source"] == "mod"]:
        same_class = [x for x in rows if x["source"] == "base" and x["class"] == r["class"]]
        if same_class:
            best_base = max(same_class, key=lambda x: x["max_out"])
            worst_base = min(same_class, key=lambda x: x["max_out"])
            print(
                f"  {r['name']:<40} GW={r['max_out']:>10,.1f} eff={r['eff']:.3f} | "
                f"base range: [{worst_base['max_out']:,.1f} - {best_base['max_out']:,.1f}] GW"
            )


if __name__ == "__main__":
    main()
