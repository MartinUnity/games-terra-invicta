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
import glob
import json
import math
import os
import random
import shlex
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

    # Determine per-shot damage required. If DPS provided, derive per-shot damage.
    if dps is not None:
        rps = rps_from_timing(cooldown, salvo, intra)
        if rps == 0:
            raise ValueError("computed RPS is zero -- check timing/salvo values")
        per_shot_damage = dps / rps
        damage_in_game = per_shot_damage

    # If neither damage nor dps was provided, but warhead mass and muzzle velocity are present,
    # compute energy -> damageInGame from those values so existing weapons can be analyzed.
    if damage_in_game is None:
        if warhead_mass is not None and muzzle_kps is not None:
            energy_mj = 0.5 * warhead_mass * (muzzle_kps**2)
            damage_in_game = energy_mj / 20.0
        else:
            raise ValueError(
                "either damage, dps, or both warheadMass+muzzleVelocity must be provided for gun/magnetic type"
            )

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
    def _fmt(v: Any) -> str:
        try:
            return f"{float(v):.2f}"
        except Exception:
            return str(v)

    if shot_power_mj is None:
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
    p.add_argument("--type", choices=["gun", "magnetic", "laser", "particle", "plasma"], required=False, default=None)
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
    p.add_argument("--compare", action="store_true", help="Compare two weapon parameter sets (--left and --right)")
    p.add_argument(
        "--left", type=str, default=None, help='Left param string: "type=gun cooldown=6 salvo=2 warheadMass=40 ..."'
    )
    p.add_argument("--right", type=str, default=None, help="Right param string")
    p.add_argument("--scan-existing", action="store_true", help="Scan game template files and print one-line stats")
    p.add_argument(
        "--sort",
        choices=["none", "dps", "grouped"],
        default="none",
        help="Sort results: 'dps' for global dps desc, 'grouped' to group by type then sort by dps",
    )
    p.add_argument(
        "--filter-type",
        type=str,
        default=None,
        help="Comma-separated list of types to include when using --scan-existing (e.g. 'gun,laser')",
    )
    p.add_argument(
        "--include-alien",
        action="store_true",
        default=False,
        help="Include Alien weapons in --scan-existing output (off by default; Alien weapons often considered cheat)",
    )
    args = p.parse_args(argv)

    # When using --compare we can infer types from the left/right strings;
    # otherwise require --type to be present for normal operation.
    if not args.scan_existing and not args.compare and not args.type:
        print("Error: --type is required unless --compare is used", file=sys.stderr)
        return 2

    # If user asked to scan existing template files, do that and exit
    if args.scan_existing:
        # try to locate the Templates folder by walking up a few levels
        start = os.path.dirname(__file__)
        base_dir = None
        for up in range(0, 6):
            cand = os.path.abspath(os.path.join(start, *([".."] * up), "Games", "TerraInvicta", "templates"))
            if os.path.exists(cand):
                base_dir = cand
                break
        if not base_dir:
            # fallback to ~/Games/TerraInvicta/templates
            cand = os.path.expanduser(os.path.join("~", "Games", "TerraInvicta", "templates"))
            if os.path.exists(cand):
                base_dir = cand
        if not base_dir:
            print("Templates directory not found; checked candidate locations", file=sys.stderr)
            return 1
        mapping = {
            "TIGunTemplate.json": "gun",
            "TILaserWeaponTemplate.json": "laser",
            "TIMagneticGunTemplate.json": "magnetic",
            "TIParticleWeaponTemplate.json": "particle",
            "TIPlasmaWeaponTemplate.json": "plasma",
        }

        def _fmt(v):
            try:
                return f"{float(v):.2f}"
            except Exception:
                return ""

        rows_all: List[List[str]] = []
        # also scan Mods/ in the repo for custom templates
        repo_root = os.path.abspath(os.path.join(start, ".."))
        mods_dir = os.path.join(repo_root, "Mods")

        sources = [(base_dir, ""), (mods_dir, "MOD")]
        for fname, wtype in mapping.items():
            for src_dir, src_tag in sources:
                path = os.path.join(src_dir, fname)
                if not os.path.exists(path):
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                except Exception:
                    continue
                if not isinstance(data, list):
                    continue
                for entry in data:
                    name = entry.get("dataName") or entry.get("name") or ""
                    friendly = entry.get("friendlyName") or ""
                    # determine per-shot energy (MJ)
                    energy = None
                    if "damage_MJ" in entry:
                        energy = float(entry.get("damage_MJ") or 0)
                    elif "shotPower_MJ" in entry:
                        energy = float(entry.get("shotPower_MJ") or 0)
                    elif entry.get("warheadMass_kg") and entry.get("muzzleVelocity_kps"):
                        war = float(entry.get("warheadMass_kg") or 0)
                        mv = float(entry.get("muzzleVelocity_kps") or 0)
                        energy = 0.5 * war * (mv**2)

                    damage_in_game = (energy / 20.0) if energy is not None else None

                    # timing
                    cooldown = entry.get("cooldown_s") or entry.get("cooldown") or 0
                    salvo = entry.get("salvo_shots") or entry.get("salvo") or 1
                    intra = (
                        entry.get("intraSalvoCooldown_s") or entry.get("intraSalvoCooldown_s") or entry.get("intra", 0)
                    )
                    try:
                        if wtype in ("gun", "magnetic"):
                            rps = rps_from_timing(float(cooldown), int(salvo), float(intra))
                        else:
                            rps = 1.0 / float(cooldown) if float(cooldown) > 0 else 0.0
                    except Exception:
                        rps = 0.0

                    dps = (damage_in_game * rps) if isinstance(damage_in_game, float) else None

                    war_kg = entry.get("warheadMass_kg") or entry.get("warheadMass") or None
                    mv_kps = entry.get("muzzleVelocity_kps") or entry.get("muzzleVelocity") or None
                    mag = entry.get("magazine") or None

                    rows_all.append(
                        [
                            wtype,
                            name,
                            friendly,
                            _fmt(damage_in_game) if damage_in_game is not None else "",
                            _fmt(energy) if energy is not None else "",
                            _fmt(dps) if dps is not None else "",
                            _fmt(rps),
                            _fmt(war_kg) if war_kg is not None else "",
                            _fmt(mv_kps) if mv_kps is not None else "",
                            _fmt(cooldown),
                            str(int(salvo)) if salvo is not None else "",
                            str(mag) if mag is not None else "",
                            src_tag,
                        ]
                    )

        # Apply filter if requested (comma-separated types)
        if args.filter_type:
            allowed = {t.strip().lower() for t in args.filter_type.split(",") if t.strip()}
            rows_all = [r for r in rows_all if (r[0] or "").lower() in allowed]

        # Exclude generic base templates and region defense entries by name
        # e.g. T1Base, T2Base, T3Base, RegionDefense (case-insensitive).
        # Also exclude Alien weapons by default (they contain 'Alien' in name);
        # pass --include-alien to show them.
        exclude = ("t1base", "t2base", "t3base", "regiondefense")
        filtered = []
        for r in rows_all:
            dn = (r[1] or "").lower()
            fn = (r[2] or "").lower()
            # skip base/regiondefense matches
            if any((p in dn) or (p in fn) for p in exclude):
                continue
            # skip alien entries unless explicitly allowed
            if not args.include_alien and ("alien" in dn or "alien" in fn):
                continue
            filtered.append(r)
        rows_all = filtered

        # apply sorting if requested
        def _num_or_neginf(s: str) -> float:
            try:
                return float(s)
            except Exception:
                return float("-inf")

        if args.sort == "dps":
            rows_all.sort(key=lambda r: _num_or_neginf(r[5]), reverse=True)
        elif args.sort == "grouped":
            # preserve mapping order for groups
            group_order = list(mapping.values())
            groups = {t: [] for t in group_order}
            others: List[List[str]] = []
            for r in rows_all:
                if r[0] in groups:
                    groups[r[0]].append(r)
                else:
                    others.append(r)
            new_rows: List[List[str]] = []
            for t in group_order:
                grp = groups.get(t, [])
                grp.sort(key=lambda r: _num_or_neginf(r[5]), reverse=True)
                new_rows.extend(grp)
            # append any others unsorted
            new_rows.extend(others)
            rows_all = new_rows

        # print table with fixed-width columns
        if rows_all:
            header = [
                "type",
                "dataName",
                "friendly",
                "dmg",
                "MJ",
                "dps",
                "rps",
                "warhead",
                "muzzle",
                "cd",
                "salvo",
                "mag",
                "src",
            ]
            cols = [header] + rows_all
            widths = [max(len(str(r[i])) for r in cols) for i in range(len(header))]
            sep = " | "
            print(sep.join(header[i].ljust(widths[i]) for i in range(len(header))))
            print("-" * (sum(widths) + len(sep) * (len(widths) - 1)))
            for r in rows_all:
                print(sep.join(str(r[i]).ljust(widths[i]) for i in range(len(r))))
        return 0

    def parse_kv_string(s: str) -> Dict[str, str]:
        # parse space-separated key=val tokens, allow quoted values
        res: Dict[str, str] = {}
        if not s:
            return res
        toks = shlex.split(s)
        for t in toks:
            if "=" in t:
                k, v = t.split("=", 1)
                res[k] = v
        return res

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
        elif args.type in ("laser", "particle", "plasma"):
            try:
                snippet = make_laser_snippet(
                    args.name,
                    friendly,
                    args.shotPower_MJ,
                    args.damage,
                    args.cooldown,
                    args.efficiency,
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
                    "damageInGame": round(dmg, 2),
                    "energy_MJ": round(energy, 2),
                    "muzzle_kps": round(mv, 2),
                    "warhead_kg": round(war, 2),
                    "rps": round(rps, 2),
                    "dps": round(dps, 2),
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
                    "damageInGame": round(dmg, 2),
                    "shotPower_MJ": round(shot, 2),
                    "energy_MJ": round(shot, 2),
                    "rps": round(rps, 2),
                    "dps": round(dps, 2),
                }
            )
        return stats

    # Compare mode: build two snippets from param strings and print side-by-side diffs
    if args.compare:
        if not args.left or not args.right:
            print("Error: --compare requires --left and --right parameter strings", file=sys.stderr)
            return 2
        left_map = parse_kv_string(args.left)
        right_map = parse_kv_string(args.right)

        def build_from_map(m: Dict[str, str], default_type: Optional[str]) -> Dict[str, Any]:
            t = m.get("type", default_type)
            name = m.get("name", m.get("dataName", "LHS"))
            friendly = m.get("friendly", name)

            def gf(k: str, default: Optional[Any] = None) -> Optional[Any]:
                if k in m:
                    v = m[k]
                    try:
                        if isinstance(default, int):
                            return int(float(v))
                        return float(v)
                    except Exception:
                        return v
                return default

            if t in ("gun", "magnetic"):
                return make_gun_snippet(
                    name,
                    friendly,
                    gf("damage", None),
                    gf("dps", None),
                    gf("cooldown", 6.0) or 6.0,
                    int(gf("salvo", 1) or 1),
                    gf("intra", 0.0) or 0.0,
                    gf("ammoMass", None),
                    gf("warheadMass", None),
                    gf("muzzleVelocity", None),
                    gf("propellantFraction", 0.4) or 0.4,
                )
            else:
                return make_laser_snippet(
                    name,
                    friendly,
                    gf("shotPower_MJ", None),
                    gf("damage", None),
                    gf("cooldown", 6.0) or 6.0,
                    gf("efficiency", 1.0) or 1.0,
                    gf("wavelength_nm", 810.0) or 810.0,
                    gf("mirror_cm", 60.0) or 60.0,
                    gf("beam_quality", 1.2) or 1.2,
                    gf("jitter", 9e-8) or 9e-8,
                    gf("base_mass", 150.0) or 150.0,
                )

        left_snip = build_from_map(left_map, args.type)
        right_snip = build_from_map(right_map, args.type)

        l_stats = compute_stats(left_snip, left_map.get("type", args.type))
        r_stats = compute_stats(right_snip, right_map.get("type", args.type))

        if left_map.get("type", args.type) in ("gun", "magnetic"):
            keys = ["damageInGame", "energy_MJ", "dps", "rps", "warhead_kg", "muzzle_kps", "cooldown_s"]
            if "magazine" in left_map and "magazine" in right_map:
                keys.insert(6, "magazine")
        else:
            keys = ["damageInGame", "energy_MJ", "dps", "rps", "shotPower_MJ", "baseWeaponMass_tons", "cooldown_s"]

        def _fmt(v: Any) -> str:
            try:
                return f"{float(v):.2f}"
            except Exception:
                return str(v)

        rows: List[List[str]] = []

        def val(stats: Dict[str, Any], snip: Dict[str, Any], k: str) -> Any:
            if k in stats:
                return stats[k]
            return snip.get(k, snip.get(k.replace("_", ""), ""))

        header = [
            "stat",
            f"left ({left_snip.get('friendlyName')})",
            f"right ({right_snip.get('friendlyName')})",
            "diff",
        ]

        for k in keys:
            lv = val(l_stats, left_snip, k)
            rv = val(r_stats, right_snip, k)
            try:
                lfv = float(lv)
                rfv = float(rv)
                diff = lfv - rfv
                if rfv == 0:
                    pct_s = "(inf%)" if diff != 0 else "(+0.00%)"
                else:
                    pct = (diff / rfv) * 100.0
                    pct_s = f" ({pct:+.2f}%)"
                diff_s = f"{diff:+.2f} {pct_s}"
            except Exception:
                diff_s = ""
            rows.append([k, _fmt(lv), _fmt(rv), diff_s])

        cols = [header] + rows
        widths = [max(len(str(r[i])) for r in cols) for i in range(len(header))]
        sep = " | "
        print(sep.join(header[i].ljust(widths[i]) for i in range(len(header))))
        print("-" * (sum(widths) + len(sep) * (len(widths) - 1)))
        for r in rows:
            print(sep.join(str(r[i]).ljust(widths[i]) for i in range(len(r))))
        return 0

    if args.output == "table":
        # Build table rows
        rows: List[List[str]] = []

        # local formatter for table numeric columns (2 decimals)
        def _fmt_local(v: Any) -> str:
            try:
                return f"{float(v):.2f}"
            except Exception:
                return "" if v == "" else str(v)

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
                        _fmt_local(stats.get("damageInGame", "")),
                        _fmt_local(stats.get("dps", "")),
                        _fmt_local(stats.get("rps", "")),
                        _fmt_local(stats.get("warhead_kg", "")),
                        _fmt_local(stats.get("muzzle_kps", "")),
                        _fmt_local(sn.get("cooldown_s", "")),
                        _fmt_local(sn.get("salvo_shots", "")),
                        _fmt_local(sn.get("magazine", "")),
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
                        _fmt_local(stats.get("damageInGame", "")),
                        _fmt_local(stats.get("dps", "")),
                        _fmt_local(stats.get("shotPower_MJ", "")),
                        _fmt_local(sn.get("cooldown_s", "")),
                        _fmt_local(sn.get("baseWeaponMass_tons", "")),
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
