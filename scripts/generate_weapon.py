#!/usr/bin/env python3
"""Generate weapon template snippets from desired damage/DPS parameters.

Supports types: gun, magnetic (same fields), laser/particle/plasma (beam weapons).

Usage examples:
  python scripts/generate_weapon.py --type gun --damage 4.5 --warheadMass 40 --salvo 2 --cooldown 6 --intra 0.5
  python scripts/generate_weapon.py --type laser --damage 5 --shotPower_MJ 100
  python scripts/generate_weapon.py --type gun --random 10

The script prints JSON snippets to stdout.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from typing import Any, Dict, List, Optional


def rps_from_timing(cooldown: float, salvo: int, intra: float) -> float:
    if salvo <= 0:
        return 0.0
    cycle = cooldown + intra * (salvo - 1)
    if cycle <= 0:
        return float("inf")
    return salvo / cycle


def energy_from_damage(damage_in_game: float) -> float:
    # game damage = energy_MJ / 20
    return damage_in_game * 20.0


def compute_muzzle_for_energy(energy_mj: float, warhead_kg: float) -> float:
    # E = 0.5 * m * v^2  => v = sqrt(2E/m)
    if warhead_kg <= 0:
        raise ValueError("warhead mass must be > 0")
    return math.sqrt(2.0 * energy_mj / warhead_kg)


def compute_warhead_for_energy(energy_mj: float, muzzle_kps: float) -> float:
    if muzzle_kps <= 0:
        raise ValueError("muzzle velocity must be > 0")
    return 2.0 * energy_mj / (muzzle_kps * muzzle_kps)


def make_gun_snippet(
    data_name: str,
    friendly: str,
    damage_in_game: Optional[float],
    dps: Optional[float],
    cooldown: float,
    salvo: int,
    intra: float,
    ammo_mass: Optional[float],
    warhead_mass: Optional[float],
    muzzle_kps: Optional[float],
    propellant_fraction: float = 0.4,
) -> Dict[str, Any]:
    # Determine per-shot damage required
    if dps is not None:
        rps = rps_from_timing(cooldown, salvo, intra)
        if rps == 0:
            raise ValueError("computed RPS is zero -- check timing/salvo values")
        per_shot_damage = dps / rps
        damage_in_game = per_shot_damage
    if damage_in_game is None:
        raise ValueError("either damage or dps must be provided for gun type")

    energy_mj = energy_from_damage(damage_in_game)

    # If warhead and muzzle provided, just compute energy and echo
    if warhead_mass and muzzle_kps:
        computed_energy = 0.5 * warhead_mass * (muzzle_kps**2)
        # override energy_mj to match computed if user provided both
        energy_mj = computed_energy
    elif warhead_mass and not muzzle_kps:
        muzzle_kps = compute_muzzle_for_energy(energy_mj, warhead_mass)
    elif muzzle_kps and not warhead_mass:
        warhead_mass = compute_warhead_for_energy(energy_mj, muzzle_kps)
    else:
        # neither provided: try to use ammo_mass as container for both
        if ammo_mass and ammo_mass > 0:
            warhead_mass = ammo_mass * (1.0 - propellant_fraction)
            muzzle_kps = compute_muzzle_for_energy(energy_mj, warhead_mass)
        else:
            # sensible defaults
            warhead_mass = 40.0
            muzzle_kps = compute_muzzle_for_energy(energy_mj, warhead_mass)

    # compute energy and damage in-game (sanity)
    energy_mj = 0.5 * warhead_mass * (muzzle_kps**2)
    damage_calc = energy_mj / 20.0

    snippet = {
        "dataName": data_name,
        "friendlyName": friendly,
        "mount": "OneHull",
        "requiredProjectName": f"Project_{data_name}",
        "crew": 3,
        "attackMode": True,
        "defenseMode": False,
        "baseWeaponMass_tons": max(1, int((warhead_mass + (ammo_mass or warhead_mass)) / 100.0)),
        "cooldown_s": cooldown,
        "salvo_shots": salvo,
        "intraSalvoCooldown_s": intra,
        "efficiency": 1,
        "flatChipping": round(1.0 + (warhead_mass / 100.0), 3),
        "magazine": int(max(10, (ammo_mass or 100) * 5)),
        "ammoMass_kg": round(ammo_mass or (warhead_mass * (1.0 + propellant_fraction)), 2),
        "muzzleVelocity_kps": round(muzzle_kps, 6),
        "bombardmentValue": 1,
        "warheadMass_kg": round(warhead_mass, 3),
        "targetingRange_km": 900,
        "pivotRange_deg": 90,
        "isPointDefenseTargetable": False,
        "_comment_energy_MJ": round(energy_mj, 3),
        "_comment_damageInGame": round(damage_calc, 3),
    }
    return snippet


def make_laser_snippet(
    data_name: str,
    friendly: str,
    shot_power_mj: Optional[float],
    damage_in_game: Optional[float],
    cooldown: float,
    efficiency: float,
    wavelength_nm: float,
    mirror_cm: float,
    beam_quality: float,
    jitter: float,
    base_mass: float,
) -> Dict[str, Any]:
    if damage_in_game is not None and shot_power_mj is None:
        shot_power_mj = energy_from_damage(damage_in_game)
    if shot_power_mj is None:
        raise ValueError("Provide either shot_power_MJ or damage for laser type")

    snippet = {
        "dataName": data_name,
        "friendlyName": friendly,
        "mount": "OneHull",
        "baseWeaponMass_tons": base_mass,
        "cooldown_s": cooldown,
        "efficiency": efficiency,
        "shotPower_MJ": shot_power_mj,
        "wavelength_nm": wavelength_nm,
        "mirrorRadius_cm": mirror_cm,
        "beam_quality": beam_quality,
        "jitter_Rad": jitter,
        "bombardmentValue": 0.2,
        "targetingRange_km": 600,
        "pivotRange_deg": 180,
        "_comment_damageInGame": round(shot_power_mj / 20.0, 3),
    }
    return snippet


def random_gun_examples(n: int) -> List[Dict[str, Any]]:
    out = []
    for i in range(n):
        dmg = random.uniform(3.5, 8.5)  # target per-shot damageInGame
        cooldown = random.choice([4, 6, 8, 10])
        salvo = random.choice([1, 2, 3])
        intra = 0.25 if salvo > 1 else 0.0
        war = random.uniform(20, 80)
        ammo = war * random.uniform(1.2, 1.6)
        snip = make_gun_snippet(
            f"RandGun{i}",
            f"Random Gun {i}",
            dmg,
            None,
            cooldown,
            salvo,
            intra,
            ammo,
            war,
            None,
        )
        out.append(snip)
    return out


def generate_name_for(snippet: Dict[str, Any], wtype: str) -> str:
    # Small keyword pools by type
    prefixes = {
        "gun": ["Siege", "Thunder", "Iron", "Rupture", "Breaker", "Breach", "Mael", "Pound", "Rivet", "Anvil"],
        "magnetic": ["Gauss", "Rail", "Vector", "Magna", "Shock", "Pull", "Stride", "Impulse", "Prime", "Null"],
        "laser": ["Lumen", "Solar", "Photon", "Pulse", "Raster", "Aurora", "Prism", "Haze", "Quanta", "Beam"],
        "particle": ["Flux", "Ion", "Spatter", "Vortex", "Corona", "Ionize", "Cascade", "Fermion", "Quark", "Nova"],
        "plasma": ["Plasma", "Torch", "Helion", "Blaze", "Inferno", "Corona", "Cinder", "Scorch", "Flux", "Torch"],
    }
    middles = [
        "Breaker",
        "Cannon",
        "Emitter",
        "Array",
        "Driver",
        "Launcher",
        "Discharger",
        "Projector",
        "Launcher",
        "Core",
    ]
    suffixes = ["Mark I", "Mk II", "Prime", "Alpha", "Beta", "Omega", "Vanguard", "Aegis", "X", "V"]

    pref = random.choice(prefixes.get(wtype, prefixes["gun"]))

    # adjective from stats
    mass = snippet.get("baseWeaponMass_tons", 0)
    muzzle = snippet.get("muzzleVelocity_kps") or snippet.get("shotPower_MJ") or 0
    adjective = None
    if wtype in ("gun", "magnetic"):
        if mass >= 50 and muzzle < 2.5:
            adjective = random.choice(["Siegebreaker", "Slowstrike", "Colossus"])
        elif muzzle >= 3.0 and mass < 10:
            adjective = random.choice(["Swift", "Razor", "Rapid"])
        else:
            adjective = random.choice(["Heavy", "Longshot", "Thunder"])
    else:
        # beam types
        if snippet.get("shotPower_MJ", 0) >= 100:
            adjective = random.choice(["Auger", "Incisor", "Singularity"])
        else:
            adjective = random.choice(["Pulse", "Focus", "Prism"])

    mid = random.choice(middles)
    suff = random.choice(suffixes)

    # build variations
    patterns = [f"{pref} {mid}", f"{adjective} {mid}", f"{pref} {adjective}", f"{pref}-{adjective} {suff}"]
    name = random.choice(patterns)
    return name


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--type", choices=["gun", "magnetic", "laser", "particle", "plasma"], required=True)
    p.add_argument("--damage", type=float, help="desired per-shot damageInGame")
    p.add_argument("--dps", type=float, help="desired DPS (will compute per-shot damage)")
    p.add_argument("--cooldown", type=float, default=6.0)
    p.add_argument("--salvo", type=int, default=1)
    p.add_argument("--intra", type=float, default=0.0)
    p.add_argument("--ammoMass", type=float, help="ammo mass kg (includes propellant)")
    p.add_argument("--warheadMass", type=float, help="warhead mass kg")
    p.add_argument("--muzzleVelocity", type=float, help="muzzle velocity kps")
    p.add_argument("--propellantFraction", type=float, default=0.4)
    p.add_argument("--shotPower_MJ", type=float, help="shot energy for laser-type weapons")
    p.add_argument("--efficiency", type=float, default=1.0)
    p.add_argument("--wavelength_nm", type=float, default=810.0)
    p.add_argument("--mirror_cm", type=float, default=60.0)
    p.add_argument("--beam_quality", type=float, default=1.2)
    p.add_argument("--jitter", type=float, default=9e-8)
    p.add_argument("--base_mass", type=float, default=150.0)
    p.add_argument("--name", type=str, default="GeneratedWeapon")
    p.add_argument("--friendly", type=str, default=None)
    p.add_argument("--random", type=int, default=0, help="generate N random examples")
    p.add_argument("--output", choices=["json", "table"], default="json", help="output format for multiple examples")
    args = p.parse_args(argv)

    results: List[Dict[str, Any]] = []
    if args.random and args.type in ("gun", "magnetic"):
        results = random_gun_examples(args.random)
    else:
        friendly = args.friendly or args.name
        if args.type in ("gun", "magnetic"):
            try:
                snippet = make_gun_snippet(
                    args.name,
                    friendly,
                    args.damage,
                    args.dps,
                    args.cooldown,
                    args.salvo,
                    args.intra,
                    args.ammoMass,
                    args.warheadMass,
                    args.muzzleVelocity,
                    args.propellantFraction,
                )
                # generate a suggested name if none provided
                snippet_name = generate_name_for(snippet, args.type)
                if not args.friendly:
                    snippet["friendlyName"] = snippet_name
                else:
                    snippet["friendlyName"] = friendly
            except Exception as e:
                print("Error:", e, file=sys.stderr)
                return 2
            results = [snippet]
        else:
            try:
                snippet = make_laser_snippet(
                    args.name,
                    friendly,
                    args.shotPower_MJ,
                    args.damage,
                    args.cooldown,
                    args.efficiency,
                    args.wavelength_nm,
                    args.mirror_cm,
                    args.beam_quality,
                    args.jitter,
                    args.base_mass,
                )
            except Exception as e:
                print("Error:", e, file=sys.stderr)
                return 2
            results = [snippet]

    # print results
    def compute_stats(snip: Dict[str, Any], wtype: str) -> Dict[str, Any]:
        stats: Dict[str, Any] = {}
        if wtype in ("gun", "magnetic"):
            war = float(snip.get("warheadMass_kg", 0))
            mv = float(snip.get("muzzleVelocity_kps", 0))
            energy = 0.5 * war * (mv**2)
            dmg = energy / 20.0 if energy else 0.0
            rps = rps_from_timing(
                float(snip.get("cooldown_s", 0)),
                int(snip.get("salvo_shots", 1)),
                float(snip.get("intraSalvoCooldown_s", 0)),
            )
            dps = dmg * rps
            stats.update(
                {
                    "damageInGame": round(dmg, 3),
                    "energy_MJ": round(energy, 3),
                    "muzzle_kps": round(mv, 6),
                    "warhead_kg": round(war, 3),
                    "rps": round(rps, 3),
                    "dps": round(dps, 3),
                }
            )
        else:
            shot = float(snip.get("shotPower_MJ", 0))
            dmg = shot / 20.0 if shot else 0.0
            cooldown = float(snip.get("cooldown_s", 1))
            rps = 1.0 / cooldown if cooldown > 0 else 0.0
            dps = dmg * rps
            stats.update(
                {
                    "damageInGame": round(dmg, 3),
                    "shotPower_MJ": round(shot, 3),
                    "rps": round(rps, 3),
                    "dps": round(dps, 3),
                }
            )
        return stats

    if args.output == "table":
        # Build table rows
        rows: List[List[str]] = []
        if args.type in ("gun", "magnetic"):
            header = [
                "name",
                "dataName",
                "dmg",
                "dps",
                "rps",
                "warhead_kg",
                "muzzle_kps",
                "cooldown",
                "salvo",
                "magazine",
            ]
            for sn in results:
                stats = compute_stats(sn, args.type)
                rows.append(
                    [
                        sn.get("friendlyName", ""),
                        sn.get("dataName", ""),
                        f"{stats['damageInGame']}",
                        f"{stats['dps']}",
                        f"{stats['rps']}",
                        f"{stats.get('warhead_kg', '')}",
                        f"{stats.get('muzzle_kps', '')}",
                        f"{sn.get('cooldown_s', '')}",
                        f"{sn.get('salvo_shots', '')}",
                        f"{sn.get('magazine', '')}",
                    ]
                )
        else:
            header = ["name", "dataName", "dmg", "dps", "shot_MJ", "cooldown", "mass_tons"]
            for sn in results:
                stats = compute_stats(sn, args.type)
                rows.append(
                    [
                        sn.get("friendlyName", ""),
                        sn.get("dataName", ""),
                        f"{stats['damageInGame']}",
                        f"{stats['dps']}",
                        f"{stats.get('shotPower_MJ', '')}",
                        f"{sn.get('cooldown_s', '')}",
                        f"{sn.get('baseWeaponMass_tons', '')}",
                    ]
                )

        # column widths
        cols = [header] + rows
        widths = [max(len(str(r[i])) for r in cols) for i in range(len(header))]
        # print header using ' | ' separator
        sep = " | "
        hdr = sep.join(header[i].ljust(widths[i]) for i in range(len(header)))
        print(hdr)
        print("-" * (sum(widths) + len(sep) * (len(widths) - 1)))
        for r in rows:
            print(sep.join(str(r[i]).ljust(widths[i]) for i in range(len(r))))
    else:
        # JSON output
        if len(results) == 1:
            print(json.dumps(results[0], indent=2, ensure_ascii=False))
        else:
            print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
