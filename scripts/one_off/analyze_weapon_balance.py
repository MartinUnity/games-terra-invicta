#!/usr/bin/env python3
"""Correlate weapon DPS with research cost and mount slot usage."""

import json
import re
import os

MODS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "Mods")

PROJECT_FILE = os.path.join(MODS_DIR, "TIProjectTemplate.json")

WEAPON_FILES = [
    ("TIGunTemplate.json", "guns"),
    ("TIMagneticGunTemplate.json", "mags"),
    ("TIMissileTemplate.json", "missiles"),
    ("TILaserWeaponTemplate.json", "lasers"),
    ("TIParticleWeaponTemplate.json", "particles"),
    ("TIPlasmaWeaponTemplate.json", "plasma"),
]

MOUNT_MODIFIER = {
    "OneHull": 1,
    "TwoHullHoriz": 2,
    "TwoHull": 2,
    "FourHull": 4,
    "OneNose": 2,
    "TwoNose": 4,
    "TwoNoseVert": 4,
    "ThreeNoseAngle": 3,
}

SKIP_MOUNTS = {"T3BaseDefense"}


def parse_dps(comment_dps: str) -> float:
    m = re.search(r"([\d.]+)\s*MJ/s", comment_dps)
    return float(m.group(1)) if m else 0.0


def cycle_time(entry: dict) -> float:
    salvo = entry.get("salvo_shots", 1)
    cooldown = entry.get("cooldown_s", 1)
    intra = entry.get("intraSalvoCooldown_s", 0)
    return cooldown + intra * (salvo - 1)


def calc_gun_dps(entry: dict) -> float:
    """Magnetic guns: 0.5 * m * v^2 * salvo / cycle_time."""
    mass = entry.get("warheadMass_kg", 0)
    velocity = entry.get("muzzleVelocity_kps", 0)
    if not mass or not velocity:
        return 0.0
    ct = cycle_time(entry)
    if ct <= 0:
        return 0.0
    salvo = entry.get("salvo_shots", 1)
    return 0.5 * mass * velocity ** 2 * (salvo / ct)


def calc_missile_dps(entry: dict) -> float:
    """Missiles: flatDamage_MJ * salvo / cycle_time."""
    dmg = entry.get("flatDamage_MJ", 0)
    if not dmg:
        return 0.0
    ct = cycle_time(entry)
    if ct <= 0:
        return 0.0
    salvo = entry.get("salvo_shots", 1)
    return dmg * (salvo / ct)


def calc_laser_dps(entry: dict) -> float:
    """Lasers: shotPower_MJ / cooldown_s (efficiency is targeting, not damage)."""
    power = entry.get("shotPower_MJ", 0)
    cd = entry.get("cooldown_s", 1)
    if not power or not cd:
        return 0.0
    return power / cd


def calc_particle_dps(entry: dict) -> float:
    """Particles: shotPower_MJ * salvo / cycle_time (fractions sum to 1.0)."""
    power = entry.get("shotPower_MJ", 0)
    if not power:
        return 0.0
    ct = cycle_time(entry)
    if ct <= 0:
        return 0.0
    salvo = entry.get("salvo_shots", 1)
    return power * (salvo / ct)


def calc_plasma_dps(entry: dict) -> float:
    """Plasma: expectedDamage_MJ / cooldown_s."""
    dmg = entry.get("expectedDamage_MJ", 0)
    cd = entry.get("cooldown_s", 1)
    if not dmg or not cd:
        return 0.0
    return dmg / cd


DPS_CALCULATORS = {
    "guns": calc_gun_dps,
    "mags": calc_gun_dps,
    "missiles": calc_missile_dps,
    "lasers": calc_laser_dps,
    "particles": calc_particle_dps,
    "plasma": calc_plasma_dps,
}


def main() -> None:
    projects: dict[str, int] = {}
    with open(PROJECT_FILE) as f:
        for entry in json.load(f):
            projects[entry["dataName"]] = entry.get("researchCost", 0)

    project_weapons: dict[str, list[str]] = {}
    rows: list[dict] = []
    skipped: list[str] = []

    for filename, source in WEAPON_FILES:
        path = os.path.join(MODS_DIR, filename)
        if not os.path.exists(path):
            continue
        calc = DPS_CALCULATORS.get(source)
        with open(path) as f:
            entries = json.load(f)
        for entry in entries:
            name = entry.get("dataName", "?")
            mount = entry.get("mount", "Unknown")
            if mount in SKIP_MOUNTS:
                skipped.append(f"{name} ({source}): skip mount {mount}")
                continue
            proj = entry.get("requiredProjectName", "")
            project_weapons.setdefault(proj, []).append(name)

            dps_raw = entry.get("_comment_dps")
            if dps_raw:
                dps = parse_dps(dps_raw)
                dps_source = "comment"
            elif calc:
                dps = round(calc(entry), 2)
                dps_source = "calc" if dps > 0 else None
                if dps_source is None:
                    skipped.append(f"{name} ({source}): no DPS")
                    continue
            else:
                skipped.append(f"{name} ({source}): no calculator")
                continue

            cost = projects.get(proj, 0)
            mod = MOUNT_MODIFIER.get(mount, 1)
            dps_per_slot = dps / mod
            cost_eff = dps / cost if cost else 0.0

            pd_targetable = entry.get("isPointDefenseTargetable", False)
            can_defend = entry.get("defenseMode", False)

            rows.append({
                "name": name,
                "mount": mount,
                "mod": mod,
                "dps": dps,
                "dps_per_slot": dps_per_slot,
                "cost": cost,
                "cost_eff": cost_eff,
                "proj": proj,
                "dps_source": dps_source,
                "source": source,
                "pd_targetable": pd_targetable,
                "can_defend": can_defend,
            })

    rows.sort(key=lambda r: (r["cost"], r["name"]))

    if skipped:
        print("SKIPPED:")
        for s in skipped:
            print(f"  - {s}")
        print()

    shared = {p: ws for p, ws in project_weapons.items() if len(ws) > 1}
    if shared:
        print("SHARED PROJECTS (multiple weapons, single research cost):")
        for proj, ws in sorted(shared.items()):
            cost = projects.get(proj, "?")
            print(f"  {proj} (cost={cost}): {', '.join(ws)}")
        print()

    # PD-vulnerability penalty: projectiles that can be shot down are worth less
    PD_PENALTY = 0.5  # conservative estimate in a big brawl
    for r in rows:
        if r["pd_targetable"]:
            r["eff_adj"] = r["cost_eff"] * PD_PENALTY
        else:
            r["eff_adj"] = r["cost_eff"]

    # Count defense-capable weapons
    defense_count = sum(1 for r in rows if r["can_defend"])

    # Table
    hdr = (
        f"{'Weapon':<42} {'Mount':<16} {'PD':>2} {'D':>1} {'DPS':>8} "
        f"{'DPS/slot':>8} {'Cost':>8} {'DPS/cost':>9} {'Adj':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        pd = "Y" if r["pd_targetable"] else "-"
        d = "Y" if r["can_defend"] else "-"
        flag = " <--" if r["cost_eff"] > 0.04 else ""
        flag_adj = " <--adj" if r["eff_adj"] > 0.04 else ""
        print(
            f"{r['name']:<42} {r['mount']:<16} {pd:>2} {d:>1} {r['dps']:>8.2f} "
            f"{r['dps_per_slot']:>8.2f} {r['cost']:>8,} "
            f"{r['cost_eff']:>9.4f} {r['eff_adj']:>7.4f}{flag}{flag_adj}"
        )

    print(f"\n  {defense_count} weapons have defenseMode=true (can shoot down incoming projectiles)")

    # Top ADJUSTED DPS/cost (accounts for PD vulnerability)
    print("\nTOP 10 BY ADJUSTED DPS/COST (PD-vulnerability penalized):")
    by_adj = sorted(rows, key=lambda r: r["eff_adj"], reverse=True)
    for i, r in enumerate(by_adj[:10], 1):
        pd_tag = "[PD-vuln]" if r["pd_targetable"] else "[safe]"
        print(
            f"  {i:>2}. {r['name']:<42}  {r['eff_adj']:>7.4f} adj dps/cost  {pd_tag:<10}  "
            f"(raw={r['cost_eff']:.4f}, DPS={r['dps']:.1f}, cost={r['cost']:,})"
        )

    # Top raw DPS/cost for reference
    print("\nTOP 10 BY RAW DPS/COST (no PD penalty):")
    by_eff = sorted(rows, key=lambda r: r["cost_eff"], reverse=True)
    for i, r in enumerate(by_eff[:10], 1):
        pd_tag = "[PD-vuln]" if r["pd_targetable"] else "[safe]"
        print(
            f"  {i:>2}. {r['name']:<42}  {r['cost_eff']:>7.4f} dps/cost  {pd_tag:<10}  "
            f"(DPS={r['dps']:.1f}, cost={r['cost']:,})"
        )

    # Top DPS/slot
    print("\nTOP 10 BY DPS/SLOT (slot efficiency):")
    by_slot = sorted(rows, key=lambda r: r["dps_per_slot"], reverse=True)
    for i, r in enumerate(by_slot[:10], 1):
        pd_tag = "[PD-vuln]" if r["pd_targetable"] else "[safe]"
        print(
            f"  {i:>2}. {r['name']:<42}  {r['dps_per_slot']:>7.1f} dps/slot  "
            f"{pd_tag:<10} (mount={r['mount']}, cost={r['cost']:,})"
        )


if __name__ == "__main__":
    main()
