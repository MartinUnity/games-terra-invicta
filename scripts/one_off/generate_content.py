#!/usr/bin/env python3
"""
generate_content.py — AI-driven content generator for Terra Invicta mods.

Three tiers of content generation:

  easy   — Reuse existing Effect_* entries to create new research projects.
            Minimal new JSON (1 project + localization). Fast, safe.

  middle — Invent a new Tech (higher-tier research gate) plus 2-4 child
            projects that unlock from it. Full localization included.

  full   — Invent new equipment (weapon / drive / powerplant / etc.),
            the linking research project, and localization for both.
            Assets are always drawn from the existing palette — no new
            Unity assets required, no hard crashes.

Usage
-----
    # Preview without writing
    python3 scripts/one_off/generate_content.py --tier easy   --count 5  --dry-run
    python3 scripts/one_off/generate_content.py --tier middle --count 3  --dry-run
    python3 scripts/one_off/generate_content.py --tier full   --type laser --count 2 --dry-run

    # Write to mod files (backs up first)
    python3 scripts/one_off/generate_content.py --tier easy   --count 20 --apply
    python3 scripts/one_off/generate_content.py --tier middle --count 5  --apply
    python3 scripts/one_off/generate_content.py --tier full   --type drive --count 3 --apply

Supported --type values for --tier full:
    laser, gun, magnetic, drive, powerplant, missile,
    particle, plasma, radiator, heatsink, armor, hab

Notes
-----
- All results are cached in .generate_cache.json and never re-generated.
  Kill mid-run safely; resume with the same command.
- Ship hulls are intentionally excluded (Unity hardpoint mismatch crashes).
- The AI endpoint may be slow (thinking model, 3-5 t/s). Default timeout
  is 18000 s. The proxy at ai.skytech.dk handles wake-on-LAN automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = Path("/home/martin/Games/TerraInvicta/templates")
LOC_DIR = Path("/home/martin/Games/TerraInvicta/localization")
MODS_DIR = REPO_ROOT / "Mods"
MOD_LOC_DIR = MODS_DIR / "Localization" / "en"
CACHE_FILE = Path(__file__).resolve().parent / ".generate_cache.json"

# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
DEFAULT_AI_ENDPOINT = "http://192.168.0.197:8000/v1"
DEFAULT_MODEL = "Qwen3.6-27B-Q4_K_M.gguf"

# DEFAULT_AI_ENDPOINT = "https://ai.skytech.dk/v1"
# DEFAULT_MODEL = "Qwen3.6-27B-Q6_K.gguf"
DEFAULT_TIMEOUT = 18000  # 30 min — thinking model + WoL wake delay

# ---------------------------------------------------------------------------
# Equipment type → file mapping
# ---------------------------------------------------------------------------
EQUIPMENT_TYPES: Dict[str, str] = {
    "laser": "TILaserWeaponTemplate",
    "gun": "TIGunTemplate",
    "magnetic": "TIMagneticGunTemplate",
    "drive": "TIDriveTemplate",
    "powerplant": "TIPowerPlantTemplate",
    "missile": "TIMissileTemplate",
    "particle": "TIParticleWeaponTemplate",
    "plasma": "TIPlasmaWeaponTemplate",
    "radiator": "TIRadiatorTemplate",
    "heatsink": "TIHeatSinkTemplate",
    "armor": "TIShipArmorTemplate",
    "hab": "TIHabModuleTemplate",
}

ASSET_FIELDS = [
    "iconResource",
    "modelResource",
    "effectResource",
    "fireSoundFXResource",
    "impactVisualFXResource",
    "impactSoundFXResource",
    "exhaustFXResource",
]

# Drive x1-x6: fields that scale linearly with thrusters count
DRIVE_LINEAR_FIELDS = {"thrust_N", "thrustRating_GW"}
# Drive fields that are per-thruster (divide by thrusters to normalise)
DRIVE_CONSTANT_FIELDS = {"EV_kps", "efficiency", "EV_kps"}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def strip_thinking(text: str) -> str:
    """Remove <think>…</think> blocks before JSON parsing."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_json(text: str) -> Any:
    text = strip_thinking(text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    for start_char in ("{", "["):
        start = text.find(start_char)
        if start != -1:
            for end in range(len(text), start, -1):
                try:
                    return json.loads(text[start:end])
                except Exception:
                    continue
    raise ValueError(f"Could not extract JSON from:\n{text[:400]!r}")


def load_json(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: List[Dict]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_loc(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def append_loc(path: Path, lines: str) -> None:
    """Append localization lines, skipping keys that already exist in the file."""
    existing = load_loc(path)
    existing_keys: Set[str] = set()
    for ln in existing.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, _ = ln.split("=", 1)
            existing_keys.add(k.strip())

    new_lines = []
    for ln in lines.strip().splitlines():
        stripped = ln.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(ln)
            continue
        k, _ = stripped.split("=", 1)
        if k.strip() not in existing_keys:
            new_lines.append(ln)

    if not new_lines:
        return
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(existing + "\n".join(new_lines).strip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def load_cache(path: Path, no_cache: bool) -> Dict[str, Any]:
    if no_cache or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  Warning: could not read cache ({e}), starting fresh.")
        return {}


def save_cache(path: Path, cache: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# AI client
# ---------------------------------------------------------------------------


def call_ai(
    messages: List[Dict[str, str]],
    endpoint: str,
    model: str,
    timeout: int,
    temperature: float = 0.5,
) -> str:
    url = endpoint.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages, "temperature": temperature}
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


class GameData:
    """All base-game + mod data, loaded once."""

    def __init__(self) -> None:
        self.base_projects = load_json(TEMPLATES_DIR / "TIProjectTemplate.json")
        self.base_techs = load_json(TEMPLATES_DIR / "TITechTemplate.json")
        self.base_effects = load_json(TEMPLATES_DIR / "TIEffectTemplate.json")
        self.mod_projects = load_json(MODS_DIR / "TIProjectTemplate.json")
        self.mod_techs = load_json(MODS_DIR / "TITechTemplate.json")
        self.mod_effects = load_json(MODS_DIR / "TIEffectTemplate.json")

        self.base_project_names: Set[str] = {p["dataName"] for p in self.base_projects}
        self.base_tech_names: Set[str] = {t["dataName"] for t in self.base_techs}

        # All dataNames across all mod files (for uniqueness checking)
        self.all_mod_names: Set[str] = set()
        for tmpl in EQUIPMENT_TYPES.values():
            self.all_mod_names.update(e["dataName"] for e in load_json(MODS_DIR / f"{tmpl}.json"))
        self.all_mod_names.update(p["dataName"] for p in self.mod_projects)
        self.all_mod_names.update(t["dataName"] for t in self.mod_techs)

        # All base-game names (for uniqueness checking across everything)
        self.all_base_names: Set[str] = set()
        for tmpl in EQUIPMENT_TYPES.values():
            self.all_base_names.update(e["dataName"] for e in load_json(TEMPLATES_DIR / f"{tmpl}.json"))
        self.all_base_names.update(self.base_project_names)
        self.all_base_names.update(self.base_tech_names)

    def is_unique(self, name: str) -> bool:
        return name not in self.all_mod_names and name not in self.all_base_names

    def all_valid_prereqs(self) -> List[str]:
        """All base-game tech/project names that can be used as prereqs.

        Excludes:
        - Projects with disable:true (game silently ignores/cascades errors on these)
        - Geopolitical project roles the game rejects as tech-tree prereqs
          (NeutralizeNation and related types)
        - Faction-exclusive projects (factionAlways without factionPrereq)
          — invisible to other factions, break downstream project visibility
        - Objective/milestone-gated projects (requiredObjectiveName / requiredMilestone)
          — hidden until a specific alien event fires; using one as a prereq makes the
          downstream project invisible for the whole early/mid-game.  Transitive chains
          through base-game projects (e.g. PlasmaBatteryMk3 -> Exotics) are intentional
          game design and are left alone; we just avoid DIRECTLY referencing gated nodes.
        """
        _BAD_ROLES = {"NeutralizeNation", "AlienSignature", "AlienMethods", "AlienOperations"}
        valid_projects = {
            p["dataName"]
            for p in self.base_projects
            if not p.get("disable")
            and p.get("AI_projectRole") not in _BAD_ROLES
            and not ("factionAlways" in p and "factionPrereq" not in p)
            and not p.get("requiredObjectiveName")
            and not p.get("requiredMilestone")
        }
        return list(self.base_tech_names | valid_projects)

    def usable_effects(self) -> List[Dict]:
        """Effects suitable for 'easy' tier (permanent, additive, numeric value)."""
        all_eff = self.base_effects + self.mod_effects
        good = []
        for e in all_eff:
            if (
                e.get("effectDuration") == "permanent"
                and isinstance(e.get("value"), (int, float))
                and e.get("value", 0) != 0
                and e.get("operation") in ("Additive", "Multiplicative")
            ):
                good.append(e)
        return good


def build_asset_palette(tmpl_name: str) -> Dict[str, List[str]]:
    """Merge asset field values from base-game + mod entries for a template type."""
    palette: Dict[str, Set[str]] = defaultdict(set)
    for root in (TEMPLATES_DIR, MODS_DIR):
        for entry in load_json(root / f"{tmpl_name}.json"):
            for af in ASSET_FIELDS:
                val = entry.get(af)
                if val is None:
                    continue
                if isinstance(val, list):
                    val = val[0]
                palette[af].add(str(val))
    return {k: sorted(v) for k, v in palette.items()}


def extract_schema(tmpl_name: str) -> Dict[str, Dict]:
    """
    Extract field names and numeric value ranges from all entries of a template.
    Returns {field: {required: bool, numeric_min: float, numeric_max: float, sample_values: list}}.
    """
    entries: List[Dict] = []
    for root in (TEMPLATES_DIR, MODS_DIR):
        entries.extend(load_json(root / f"{tmpl_name}.json"))

    field_info: Dict[str, Dict] = {}
    for entry in entries:
        for k, v in entry.items():
            if k in ASSET_FIELDS or k in ("dataName", "friendlyName"):
                continue
            info = field_info.setdefault(k, {"count": 0, "nums": [], "samples": []})
            info["count"] += 1
            if isinstance(v, (int, float)):
                info["nums"].append(float(v))
            if len(info["samples"]) < 5 and v not in info["samples"]:
                info["samples"].append(v)

    total = len(entries)
    result = {}
    for k, info in field_info.items():
        entry_info: Dict[str, Any] = {
            "required": info["count"] >= total * 0.75,
            "sample_values": info["samples"],
        }
        if info["nums"]:
            entry_info["numeric_min"] = min(info["nums"])
            entry_info["numeric_max"] = max(info["nums"])
        result[k] = entry_info
    return result


def sample_entries(tmpl_name: str, n: int = 3) -> List[Dict]:
    """Return a representative sample of existing entries for use in prompts."""
    entries = load_json(TEMPLATES_DIR / f"{tmpl_name}.json")
    mod_entries = load_json(MODS_DIR / f"{tmpl_name}.json")
    pool = entries + mod_entries
    if not pool:
        return []
    step = max(1, len(pool) // n)
    return [pool[i * step] for i in range(min(n, len(pool)))]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_equipment(
    entry: Dict,
    tmpl_name: str,
    schema: Dict[str, Dict],
    palette: Dict[str, List[str]],
    game_data: GameData,
) -> List[str]:
    """Return list of validation errors (empty = OK)."""
    errors = []

    # Unique dataName
    dn = entry.get("dataName", "")
    if not dn:
        errors.append("Missing dataName")
    elif not game_data.is_unique(dn):
        errors.append(f"dataName '{dn}' already exists")

    # Required fields
    for field, info in schema.items():
        if info.get("required") and field not in entry:
            errors.append(f"Missing required field: {field}")

    # Asset paths must come from palette
    for af in ASSET_FIELDS:
        val = entry.get(af)
        if val is None:
            continue
        if isinstance(val, list):
            val = val[0]
        allowed = palette.get(af, [])
        if allowed and str(val) not in allowed:
            errors.append(f"{af} '{val}' not in palette (pick from: {allowed[:3]}...)")

    # Numeric ranges (warn only, not fail)
    for field, info in schema.items():
        if "numeric_min" in info and field in entry:
            v = entry[field]
            if isinstance(v, (int, float)):
                lo, hi = info["numeric_min"], info["numeric_max"]
                # Allow 10x beyond existing max for creative content
                if v < lo * 0.05 or v > hi * 10:
                    errors.append(f"WARN: {field}={v} outside expected range [{lo:.2g}, {hi:.2g}]")

    return errors


def validate_project(entry: Dict, game_data: GameData) -> List[str]:
    errors = []
    dn = entry.get("dataName", "")
    if not dn:
        errors.append("Missing dataName")
    elif not game_data.is_unique(dn):
        errors.append(f"dataName '{dn}' already exists")
    if not entry.get("friendlyName"):
        errors.append("Missing friendlyName")
    cat = entry.get("techCategory", "")
    if not cat:
        errors.append("Missing techCategory")
    elif cat not in VALID_TECH_CATEGORIES:
        errors.append(f"Invalid techCategory '{cat}' (must be one of {sorted(VALID_TECH_CATEGORIES)})")
    # Validate prereqs reference known names
    valid_prereqs = game_data.all_valid_prereqs()
    for pr in entry.get("prereqs") or []:
        if pr not in valid_prereqs and pr not in game_data.all_mod_names:
            errors.append(f"WARN: prereq '{pr}' not found in known names")
    return errors


def validate_tech(entry: Dict, game_data: GameData) -> List[str]:
    errors = []
    dn = entry.get("dataName", "")
    if not dn:
        errors.append("Missing dataName")
    elif not game_data.is_unique(dn):
        errors.append(f"dataName '{dn}' already exists")
    return errors


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_JSON = (
    "You are a content designer for the game Terra Invicta. "
    "Always reply ONLY with valid JSON — no prose, no markdown fences, no <think> tags. "
    "Use dataNames that are CamelCase with no spaces. "
    "Never invent asset paths (iconResource, modelResource, etc.) — only use values "
    "from the provided palette."
)


VALID_TECH_CATEGORIES = {
    "Energy",
    "InformationScience",
    "LifeScience",
    "Materials",
    "MilitaryScience",
    "SocialScience",
    "SpaceScience",
    "Xenology",
}


def _project_defaults(
    data_name: str,
    friendly_name: str,
    tech_category: str,
    effects: Any,
    prereqs: List[str],
    research_cost: int,
) -> Dict:
    return {
        "dataName": data_name,
        "friendlyName": friendly_name,
        "techCategory": tech_category,
        "AI_techRole": "None",
        "AI_criticalTech": False,
        "AI_projectRole": "None",
        "researchCost": research_cost,
        "prereqs": prereqs,
        "effects": effects,
        "oneTimeGlobally": False,
        "repeatable": False,
        "factionAvailableChance": random.randint(20, 100),
        "initialUnlockChance": random.randint(5, 50),
        "deltaUnlockChance": random.randint(2, 5),
        "maxUnlockChance": random.randint(20, 100),
        "resourcesGranted": [],
    }


# ---------------------------------------------------------------------------
# TIER: EASY
# ---------------------------------------------------------------------------


def _build_name_hint(game_data: "GameData", n: int = 30) -> str:
    """
    Return a short block listing a random sample of existing mod project dataNames.
    Used to steer the AI away from names it might independently reinvent.
    """
    pool = sorted(game_data.all_mod_names | game_data.all_base_names)
    sample = random.sample(pool, min(n, len(pool)))
    return "\n".join(sample)


_EASY_SYSTEM = _SYSTEM_JSON + """

You are generating a new Terra Invicta research project that uses an existing effect.
IMPORTANT: The mod already contains over 2000 named items. You MUST invent a
dataName that does NOT appear in the "Already taken names" list supplied in the
user message. Be creative and specific — avoid generic names like
'Project_CouncilorTrainingSim' or 'Project_CelestialBulwarkProtocol'.

Reply with a JSON object containing ONLY these fields:
  dataName        (string, prefix with "Project_", CamelCase)
  friendlyName    (string, 2-5 words, creative)
  techCategory    (one of: MilitaryScience, SocialScience, SpaceScience, Energy, Materials, InformationScience, LifeScience, Xenology)
  researchCost    (integer, 200-50000, proportional to effect magnitude)
  prereq          (string, one prereq dataName from the provided list)
  displayName     (string, same as friendlyName or slightly different)
  summary         (string, 1 sentence flavour description, max 150 chars)
  description     (string, 2-3 sentence lore/technical description)
"""

_EASY_USER = """
Create a new research project that grants this effect when researched:

Effect: {effect_json}

Choose a prereq that fits thematically from this list (pick ONE):
{prereq_sample}

Already taken names (do NOT use any of these as your dataName):
{name_hint}

Respond with JSON:
{{
  "dataName": "Project_...",
  "friendlyName": "...",
  "techCategory": "...",
  "researchCost": ...,
  "prereq": "...",
  "displayName": "...",
  "summary": "...",
  "description": "..."
}}
"""


def generate_easy(
    count: int,
    game_data: GameData,
    endpoint: str,
    model: str,
    timeout: int,
    cache: Dict,
    dry_run: bool,
) -> List[Dict]:
    """Generate 'count' effect-reuse projects. Returns list of result dicts."""
    cache.setdefault("easy", {})
    effects = game_data.usable_effects()
    prereqs = [n for n in game_data.all_valid_prereqs() if not n.startswith("Project_")]  # base-game techs only

    results = []
    generated = 0

    while generated < count:
        effect = random.choice(effects)
        cache_key = f"effect_{effect['dataName']}_{generated}"
        if cache_key in cache["easy"]:
            result = cache["easy"][cache_key]
            print(f"  [cache] {result.get('project', {}).get('dataName', '?')}")
            results.append(result)
            generated += 1
            continue

        prereq_sample = random.sample(prereqs, min(20, len(prereqs)))
        name_hint = _build_name_hint(game_data)

        def _make_easy_prompt(hint: str) -> str:
            return _EASY_USER.format(
                effect_json=json.dumps(effect, ensure_ascii=False),
                prereq_sample="\n".join(prereq_sample),
                name_hint=hint,
            )

        print(
            f"  Generating easy project {generated+1}/{count} " f"(effect: {effect['dataName']})...",
            end=" ",
            flush=True,
        )
        try:
            raw = call_ai(
                [
                    {"role": "system", "content": _EASY_SYSTEM},
                    {"role": "user", "content": _make_easy_prompt(name_hint)},
                ],
                endpoint=endpoint,
                model=model,
                timeout=timeout,
            )
            ai = extract_json(raw)
        except Exception as e:
            print(f"FAILED: {e}")
            continue

        dn = ai.get("dataName", "")
        if not dn or not game_data.is_unique(dn):
            # One targeted retry: tell the AI exactly which name collided
            print(f"retry ('{dn}' taken)...", end=" ", flush=True)
            retry_hint = name_hint + (f"\n{dn}" if dn else "")
            retry_messages = [
                {"role": "system", "content": _EASY_SYSTEM},
                {"role": "user", "content": _make_easy_prompt(retry_hint)},
                {"role": "assistant", "content": json.dumps(ai)},
                {
                    "role": "user",
                    "content": f"The dataName '{dn}' already exists. "
                    f"Please choose a completely different, more specific dataName and return updated JSON.",
                },
            ]
            try:
                raw2 = call_ai(retry_messages, endpoint=endpoint, model=model, timeout=timeout)
                ai = extract_json(raw2)
                dn = ai.get("dataName", "")
            except Exception as e:
                print(f"FAILED on retry: {e}")
                continue
            if not dn or not game_data.is_unique(dn):
                print(f"SKIP (still duplicate after retry: {dn!r})")
                continue

        prereq = ai.get("prereq", "")
        if prereq not in game_data.all_valid_prereqs():
            prereq = random.choice(prereq_sample)

        project = _project_defaults(
            data_name=dn,
            friendly_name=ai.get("friendlyName", dn),
            tech_category=(
                ai.get("techCategory", "SocialScience")
                if ai.get("techCategory") in VALID_TECH_CATEGORIES
                else "SocialScience"
            ),
            effects=[effect["dataName"]],
            prereqs=[prereq],
            research_cost=int(ai.get("researchCost", 1000)),
        )
        easy_summary = ai.get("summary", "")
        loc_project = (
            f"TIProjectTemplate.displayName.{dn}={ai.get('displayName', ai.get('friendlyName', dn))}\n"
            f"TIProjectTemplate.summary.{dn}={easy_summary}\n"
            f"TIProjectTemplate.description.{dn}={ai.get('description', easy_summary)}\n"
        )

        errs = validate_project(project, game_data)
        warns = [e for e in errs if e.startswith("WARN")]
        errs = [e for e in errs if not e.startswith("WARN")]
        if errs:
            print(f"INVALID: {errs}")
            continue

        # Register name as used only after successful validation
        game_data.all_mod_names.add(dn)

        result = {"project": project, "loc_project": loc_project, "warns": warns}
        cache["easy"][cache_key] = result
        results.append(result)
        generated += 1
        print(f"OK → {dn}")

    return results


# ---------------------------------------------------------------------------
# TIER: MIDDLE
# ---------------------------------------------------------------------------

_MIDDLE_SYSTEM = _SYSTEM_JSON + """

You are designing a new Terra Invicta research tech tree node.
A "tech" is a high-level research gate; researching it unlocks child "projects".
The tech itself may optionally have effects.

Reply with a JSON object:
{
  "tech": {
    "dataName":        (CamelCase, no "Project_" prefix),
    "friendlyName":    (2-4 words),
    "techCategory":    (one of: MilitaryScience, SocialScience, SpaceScience, Energy, Materials, InformationScience, LifeScience, Xenology),
    "AI_techRole":     (one of: SpaceDevelopment, SpaceWar, EarthPower, None),
    "AI_criticalTech": false,
    "endGameTech":     false,
    "researchCost":    (integer 5000-200000),
    "prereqs":         [list of 1-3 existing tech dataNames],
    "effects":         []
  },
  "tech_loc": {
    "displayName": "...",
    "summary":     "(1-2 sentences)",
    "quote":       "(an in-universe quote from a character, 1-3 sentences, include attribution on a new line starting with --)",
    "description": "(2-4 sentences of technical/lore detail)"
  },
  "projects": [
    {
      "dataName":      "Project_...",
      "friendlyName":  "...",
      "techCategory":  "...",
      "researchCost":  (integer),
      "effects":       ["Effect_ExistingEffectName"],
      "summary":       "(1 sentence)",
      "description":   "(2-3 sentence lore/technical detail)"
    },
    ... (2-4 projects total)
  ]
}
"""

_MIDDLE_USER = """
Invent a new Terra Invicta research tech and 2-4 child projects.

Theme / concept (optional): {theme}

Available prereq techs (pick 1-3 for the tech prereqs):
{prereq_sample}

Available effects to use in projects (pick real ones from this list):
{effect_sample}

Already taken names (do NOT use any of these as dataName for the tech or any project):
{name_hint}

Create something thematically coherent. The projects should use effects
from the list above — only use EXACT effect dataNames from the list.
"""


def generate_middle(
    count: int,
    game_data: GameData,
    endpoint: str,
    model: str,
    timeout: int,
    cache: Dict,
    dry_run: bool,
    themes: Optional[List[str]] = None,
) -> List[Dict]:
    cache.setdefault("middle", {})
    prereqs = [n for n in game_data.all_valid_prereqs() if not n.startswith("Project_")]
    effects = game_data.usable_effects()
    results = []
    generated = 0

    while generated < count:
        theme = (
            themes[generated % len(themes)]
            if themes
            else random.choice(
                [
                    "economy",
                    "space exploration",
                    "military doctrine",
                    "alien research",
                    "social engineering",
                    "energy production",
                    "information warfare",
                    "materials science",
                ]
            )
        )
        cache_key = f"middle_{theme}_{generated}"
        if cache_key in cache["middle"]:
            result = cache["middle"][cache_key]
            tech_dn = result.get("tech", {}).get("dataName", "?")
            print(f"  [cache] tech={tech_dn}")
            results.append(result)
            generated += 1
            continue

        prereq_sample = random.sample(prereqs, min(25, len(prereqs)))
        effect_sample = random.sample(effects, min(30, len(effects)))
        name_hint = _build_name_hint(game_data)

        def _make_middle_prompt(hint: str) -> str:
            return _MIDDLE_USER.format(
                theme=theme,
                prereq_sample="\n".join(prereq_sample),
                effect_sample="\n".join(
                    f"  {e['dataName']}  (value={e.get('value')}, contexts={e.get('contexts',[])})"
                    for e in effect_sample
                ),
                name_hint=hint,
            )

        print(f"  Generating middle tech {generated+1}/{count} (theme: {theme})...", end=" ", flush=True)
        try:
            raw = call_ai(
                [
                    {"role": "system", "content": _MIDDLE_SYSTEM},
                    {"role": "user", "content": _make_middle_prompt(name_hint)},
                ],
                endpoint=endpoint,
                model=model,
                timeout=timeout,
                temperature=0.6,
            )
            ai = extract_json(raw)
        except Exception as e:
            print(f"FAILED: {e}")
            continue

        tech = ai.get("tech", {})
        tech_loc = ai.get("tech_loc", {})
        projects = ai.get("projects", [])

        if not tech or not isinstance(projects, list) or not projects:
            print("SKIP (incomplete response)")
            continue

        tech_dn = tech.get("dataName", "")
        if not tech_dn or not game_data.is_unique(tech_dn):
            print(f"SKIP (bad/duplicate tech dataName: {tech_dn!r})")
            continue

        # Ensure required tech fields
        tech.setdefault("AI_techRole", "None")
        tech.setdefault("AI_criticalTech", False)
        tech.setdefault("endGameTech", False)
        tech.setdefault("effects", [])
        tech.setdefault("prereqs", [])

        # Clamp prereqs to known names
        tech["prereqs"] = [p for p in tech["prereqs"] if p in prereqs][:3]
        if not tech["prereqs"]:
            tech["prereqs"] = [random.choice(prereq_sample)]

        loc_tech = (
            f"TITechTemplate.displayName.{tech_dn}={tech_loc.get('displayName', tech.get('friendlyName', tech_dn))}\n"
            f"TITechTemplate.summary.{tech_dn}={tech_loc.get('summary', '')}\n"
            f"TITechTemplate.quote.{tech_dn}={tech_loc.get('quote', '')}\n"
            f"TITechTemplate.description.{tech_dn}={tech_loc.get('description', '')}\n"
        )

        game_data.all_mod_names.add(tech_dn)

        built_projects = []
        loc_projects = []
        effect_names = {e["dataName"] for e in effects}

        for p_ai in projects[:4]:
            p_dn = p_ai.get("dataName", "")
            if not p_dn or not game_data.is_unique(p_dn):
                continue
            p_effects = [e for e in (p_ai.get("effects") or []) if e in effect_names]
            if not p_effects:
                p_effects = [random.choice(effects)["dataName"]]
            p_cat = p_ai.get("techCategory", tech.get("techCategory", "SocialScience"))
            if p_cat not in VALID_TECH_CATEGORIES:
                p_cat = (
                    tech.get("techCategory", "SocialScience")
                    if tech.get("techCategory") in VALID_TECH_CATEGORIES
                    else "SocialScience"
                )
            proj = _project_defaults(
                data_name=p_dn,
                friendly_name=p_ai.get("friendlyName", p_dn),
                tech_category=p_cat,
                effects=p_effects,
                prereqs=[tech_dn],
                research_cost=int(p_ai.get("researchCost", 2000)),
            )
            errs = [e for e in validate_project(proj, game_data) if not e.startswith("WARN")]
            if errs:
                print(f"\n    WARN: project {p_dn} invalid ({errs}), skipping")
                continue
            game_data.all_mod_names.add(p_dn)
            built_projects.append(proj)
            mid_summary = p_ai.get("summary", "")
            loc_projects.append(
                f"TIProjectTemplate.displayName.{p_dn}={p_ai.get('friendlyName', p_dn)}\n"
                f"TIProjectTemplate.summary.{p_dn}={mid_summary}\n"
                f"TIProjectTemplate.description.{p_dn}={p_ai.get('description', mid_summary)}\n"
            )

        if not built_projects:
            print("SKIP (no valid child projects)")
            continue

        result = {
            "tech": tech,
            "loc_tech": loc_tech,
            "projects": built_projects,
            "loc_projects": loc_projects,
        }
        cache["middle"][cache_key] = result
        results.append(result)
        generated += 1
        print(f"OK → {tech_dn} + {len(built_projects)} projects")

    return results


# ---------------------------------------------------------------------------
# TIER: FULL
# ---------------------------------------------------------------------------

_FULL_SYSTEM = _SYSTEM_JSON + """

You are designing a new equipment item for Terra Invicta ships.
You will be given:
  - The template type
  - Example entries (study their field names and value magnitudes carefully)
  - The schema (required fields and numeric ranges)
  - Asset palettes (you MUST use ONLY these exact values for asset fields)

For drives: generate ONE entry (x1 variant only). The script will compute x2-x6.
For laser/gun/particle/plasma weapons: you may generate 1-3 size variants
  (small/medium/large) using the same requiredProjectName. Use mount values:
  OneHull, TwoHullHoriz, FourHull for small/medium/large.

Reply with JSON:
{
  "concept_name":  (short CamelCase base name, no prefix/suffix),
  "items":         [ ... array of equipment entries ... ],
  "project": {
    "dataName":      "Project_...",
    "friendlyName":  "...",
    "techCategory":  (matching category),
    "researchCost":  (integer),
    "prereq":        (one prereq dataName from provided list)
  },
  "loc": {
    "item_displayNames":   {"DataName": "Friendly Name", ...},
    "item_descriptions":   {"DataName": "(1-2 sentence description of this item)", ...},
    "project_displayName": "...",
    "project_summary":     "(1 sentence)",
    "project_description": "(2-3 sentence lore/technical description)"
  }
}
"""

_FULL_USER = """
Template type: {tmpl_name}

Example existing entries:
{examples}

Schema (required fields + numeric ranges):
{schema_summary}

Asset palettes — use ONLY these exact strings for asset fields:
{palette}

Available prereqs (choose ONE thematically appropriate):
{prereq_sample}

Already taken names (do NOT use any of these as a dataName):
{name_hint}

Design a new, creative {tmpl_name} item that fits thematically.
It should feel distinct from existing entries but balanced within the ranges shown.
If designing a drive: create 1 entry (x1). The x2-x6 variants will be auto-generated.
If designing weapons: 1-3 size variants using the SAME requiredProjectName.
"""


def _scale_drive_variants(base_entry: Dict, project_dn: str) -> List[Dict]:
    """Given an x1 drive entry, produce x1 through x6 variants."""
    base = dict(base_entry)
    # Normalise dataName to base (strip any existing xN suffix)
    base_name = re.sub(r"x\d+$", "", base["dataName"]).rstrip("_")
    variants = []
    thrust_base = base.get("thrust_N", 0)
    rating_base_str = base.get("thrustRating_GW", "0")
    try:
        rating_base = float(rating_base_str)
    except (TypeError, ValueError):
        rating_base = 0.0

    for n in range(1, 7):
        v = dict(base)
        v["dataName"] = f"{base_name}x{n}"
        v["friendlyName"] = re.sub(r"\s+x\d+$", "", base.get("friendlyName", base_name)) + f" x{n}"
        v["thrusters"] = n
        v["thrust_N"] = round(thrust_base * n)
        if rating_base:
            v["thrustRating_GW"] = str(round(rating_base * n, 3))
        v["requiredProjectName"] = project_dn
        variants.append(v)
    return variants


def generate_full(
    equip_type: str,
    count: int,
    game_data: GameData,
    endpoint: str,
    model: str,
    timeout: int,
    cache: Dict,
    dry_run: bool,
) -> List[Dict]:
    tmpl_name = EQUIPMENT_TYPES[equip_type]
    palette = build_asset_palette(tmpl_name)
    schema = extract_schema(tmpl_name)
    examples = sample_entries(tmpl_name, 3)
    prereqs = [n for n in game_data.all_valid_prereqs() if not n.startswith("Project_")]

    cache.setdefault("full", {})
    results = []
    generated = 0

    schema_summary = []
    for field, info in schema.items():
        if field in ASSET_FIELDS:
            continue
        line = f"  {field}: required={info['required']}"
        if "numeric_min" in info:
            line += f", range=[{info['numeric_min']:.3g}, {info['numeric_max']:.3g}]"
        else:
            line += f", sample={info['sample_values'][:3]}"
        schema_summary.append(line)

    palette_str = json.dumps({k: v[:8] for k, v in palette.items()}, indent=2, ensure_ascii=False)

    while generated < count:
        cache_key = f"full_{equip_type}_{generated}"
        if cache_key in cache["full"]:
            result = cache["full"][cache_key]
            print(f"  [cache] {result.get('concept_name', '?')}")
            results.append(result)
            generated += 1
            continue

        prereq_sample = random.sample(prereqs, min(20, len(prereqs)))
        name_hint = _build_name_hint(game_data)

        def _make_full_prompt(hint: str) -> str:
            return _FULL_USER.format(
                tmpl_name=tmpl_name,
                examples=json.dumps(examples, indent=2, ensure_ascii=False),
                schema_summary="\n".join(schema_summary),
                palette=palette_str,
                prereq_sample="\n".join(prereq_sample),
                name_hint=hint,
            )

        print(f"  Generating full {equip_type} item {generated+1}/{count}...", end=" ", flush=True)
        try:
            raw = call_ai(
                [
                    {"role": "system", "content": _FULL_SYSTEM},
                    {"role": "user", "content": _make_full_prompt(name_hint)},
                ],
                endpoint=endpoint,
                model=model,
                timeout=timeout,
                temperature=0.55,
            )
            ai = extract_json(raw)
        except Exception as e:
            print(f"FAILED: {e}")
            continue

        concept = ai.get("concept_name", f"New{equip_type.title()}{generated}")
        ai_items = ai.get("items", [])
        ai_proj = ai.get("project", {})
        ai_loc = ai.get("loc", {})

        if not ai_items or not ai_proj:
            print("SKIP (incomplete response)")
            continue

        project_dn = ai_proj.get("dataName", f"Project_{concept}")
        if not game_data.is_unique(project_dn):
            # Retry with explicit collision info
            print(f"retry ('{project_dn}' taken)...", end=" ", flush=True)
            retry_hint = name_hint + (f"\n{project_dn}" if project_dn else "")
            try:
                raw2 = call_ai(
                    [
                        {"role": "system", "content": _FULL_SYSTEM},
                        {"role": "user", "content": _make_full_prompt(retry_hint)},
                        {"role": "assistant", "content": json.dumps(ai)},
                        {
                            "role": "user",
                            "content": f"The project dataName '{project_dn}' already exists. "
                            f"Please choose a different dataName for both the project and all items, "
                            f"then return the full updated JSON.",
                        },
                    ],
                    endpoint=endpoint,
                    model=model,
                    timeout=timeout,
                    temperature=0.55,
                )
                ai = extract_json(raw2)
                ai_items = ai.get("items", [])
                ai_proj = ai.get("project", {})
                ai_loc = ai.get("loc", {})
                project_dn = ai_proj.get("dataName", f"Project_{concept}")
            except Exception as e:
                print(f"FAILED on retry: {e}")
                continue
            if not game_data.is_unique(project_dn):
                print(f"SKIP (still duplicate after retry: {project_dn!r})")
                continue

        # For drives: scale x1 to x6
        if equip_type == "drive":
            if len(ai_items) >= 1:
                ai_items = _scale_drive_variants(ai_items[0], project_dn)

        # Set requiredProjectName on all items
        for item in ai_items:
            item["requiredProjectName"] = project_dn

        # Validate and register items
        valid_items = []
        loc_items = []
        dn_names = ai_loc.get("item_displayNames", {})
        for item in ai_items:
            dn = item.get("dataName", "")
            if not dn:
                continue
            if not game_data.is_unique(dn):
                # For x1-x6 we may have collisions — just skip those
                print(f"\n    WARN: {dn} already exists, skipping")
                continue
            errs = validate_equipment(item, tmpl_name, schema, palette, game_data)
            hard = [e for e in errs if not e.startswith("WARN")]
            for w in errs:
                if w.startswith("WARN"):
                    print(f"\n    {w}")
            if hard:
                print(f"\n    INVALID item {dn}: {hard}")
                continue
            game_data.all_mod_names.add(dn)
            valid_items.append(item)
            fn = dn_names.get(dn, item.get("friendlyName", dn))
            desc_map = ai_loc.get("item_descriptions", {})
            desc = desc_map.get(dn, "")
            loc_entry = f"{tmpl_name}.displayName.{dn}={fn}\n"
            if desc and item.get("thrusters", 1) == 1:  # drives: only x1 gets description
                loc_entry += f"{tmpl_name}.description.{dn}={desc}\n"
            elif desc and equip_type != "drive":
                loc_entry += f"{tmpl_name}.description.{dn}={desc}\n"
            loc_items.append(loc_entry)

        if not valid_items:
            print("SKIP (no valid items after validation)")
            continue

        # The project itself needs no effects — items reference it via requiredProjectName
        prereq = ai_proj.get("prereq", "")
        if prereq not in game_data.all_valid_prereqs():
            prereq = random.choice(prereq_sample)

        project = _project_defaults(
            data_name=project_dn,
            friendly_name=ai_proj.get("friendlyName", concept),
            tech_category=(
                ai_proj.get("techCategory", "MilitaryScience")
                if ai_proj.get("techCategory") in VALID_TECH_CATEGORIES
                else "MilitaryScience"
            ),
            effects=[],
            prereqs=[prereq],
            research_cost=int(ai_proj.get("researchCost", 5000)),
        )
        errs = [e for e in validate_project(project, game_data) if not e.startswith("WARN")]
        if errs:
            print(f"SKIP (project invalid: {errs})")
            continue

        game_data.all_mod_names.add(project_dn)

        proj_summary = ai_loc.get("project_summary", "")
        proj_desc = ai_loc.get("project_description", proj_summary)
        loc_project = (
            f"TIProjectTemplate.displayName.{project_dn}={ai_loc.get('project_displayName', ai_proj.get('friendlyName', concept))}\n"
            f"TIProjectTemplate.summary.{project_dn}={proj_summary}\n"
            f"TIProjectTemplate.description.{project_dn}={proj_desc}\n"
        )

        result = {
            "concept_name": concept,
            "tmpl_name": tmpl_name,
            "equip_type": equip_type,
            "items": valid_items,
            "loc_items": loc_items,
            "project": project,
            "loc_project": loc_project,
        }
        cache["full"][cache_key] = result
        results.append(result)
        generated += 1
        print(f"OK → {project_dn} ({len(valid_items)} items)")

    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def print_easy_preview(results: List[Dict]) -> None:
    print(f"\n{'='*70}")
    print(f"  EASY TIER — {len(results)} projects")
    print(f"{'='*70}")
    for r in results:
        p = r["project"]
        print(f"\n  {p['dataName']}")
        print(f"    Name:     {p['friendlyName']}")
        print(f"    Category: {p['techCategory']}")
        print(f"    Cost:     {p['researchCost']}")
        print(f"    Effects:  {p['effects']}")
        print(f"    Prereqs:  {p['prereqs']}")
        print(f"    Loc:      {r['loc_project'].strip()[:120]}")
        if r.get("warns"):
            print(f"    Warns:    {r['warns']}")


def print_middle_preview(results: List[Dict]) -> None:
    print(f"\n{'='*70}")
    print(f"  MIDDLE TIER — {len(results)} tech trees")
    print(f"{'='*70}")
    for r in results:
        t = r["tech"]
        print(f"\n  Tech: {t['dataName']} ({t.get('techCategory')}, cost={t.get('researchCost')})")
        print(f"    Prereqs: {t.get('prereqs')}")
        for p in r["projects"]:
            print(f"    Project: {p['dataName']} (cost={p['researchCost']}, effects={p['effects']})")


def print_full_preview(results: List[Dict]) -> None:
    print(f"\n{'='*70}")
    print(f"  FULL TIER — {len(results)} equipment sets")
    print(f"{'='*70}")
    for r in results:
        print(f"\n  Concept: {r['concept_name']} ({r['equip_type']})")
        print(f"  Project: {r['project']['dataName']} (prereq={r['project']['prereqs']})")
        for item in r["items"]:
            print(f"    {item['dataName']}")


def apply_results(
    tier: str,
    equip_type: Optional[str],
    results: List[Dict],
    dry_run: bool,
) -> None:
    if not results:
        print("Nothing to apply.")
        return

    if dry_run:
        print("\n[DRY RUN] No files written.")
        return

    if tier == "easy":
        _apply_easy(results)
    elif tier == "middle":
        _apply_middle(results)
    elif tier == "full":
        _apply_full(results)


def _backup(path: Path) -> None:
    if path.exists():
        bak = path.with_suffix(".json.bak")
        shutil.copy2(path, bak)
        print(f"  Backed up {path.name} → {bak.name}")


def _apply_easy(results: List[Dict]) -> None:
    proj_path = MODS_DIR / "TIProjectTemplate.json"
    loc_path = MOD_LOC_DIR / "TIProjectTemplate.en"
    _backup(proj_path)
    data = load_json(proj_path)
    existing = {p.get("dataName") for p in data}
    added = 0
    for r in results:
        dn = r["project"].get("dataName")
        if dn in existing:
            print(f"  Skip duplicate: {dn}")
            continue
        data.append(r["project"])
        existing.add(dn)
        append_loc(loc_path, r["loc_project"])
        added += 1
    save_json(proj_path, data)
    print(f"  Written {added} projects to {proj_path.name} ({len(results)-added} already present)")
    print(f"  Appended localization to {loc_path.name}")


def _apply_middle(results: List[Dict]) -> None:
    proj_path = MODS_DIR / "TIProjectTemplate.json"
    tech_path = MODS_DIR / "TITechTemplate.json"
    proj_loc = MOD_LOC_DIR / "TIProjectTemplate.en"
    tech_loc = MOD_LOC_DIR / "TITechTemplate.en"
    _backup(proj_path)
    _backup(tech_path)
    projs = load_json(proj_path)
    techs = load_json(tech_path)
    existing_projs = {p.get("dataName") for p in projs}
    existing_techs = {t.get("dataName") for t in techs}
    added_techs = 0
    added_projs = 0
    for r in results:
        tdn = r["tech"].get("dataName")
        if tdn in existing_techs:
            print(f"  Skip duplicate tech: {tdn}")
            continue
        techs.append(r["tech"])
        existing_techs.add(tdn)
        append_loc(tech_loc, r["loc_tech"])
        added_techs += 1
        for p, lp in zip(r["projects"], r["loc_projects"]):
            pdn = p.get("dataName")
            if pdn in existing_projs:
                print(f"  Skip duplicate project: {pdn}")
                continue
            projs.append(p)
            existing_projs.add(pdn)
            append_loc(proj_loc, lp)
            added_projs += 1
    save_json(tech_path, techs)
    save_json(proj_path, projs)
    print(f"  Written {added_techs} techs, {added_projs} projects ({len(results)-added_techs} techs already present)")


def _apply_full(results: List[Dict]) -> None:
    proj_path = MODS_DIR / "TIProjectTemplate.json"
    proj_loc = MOD_LOC_DIR / "TIProjectTemplate.en"
    _backup(proj_path)
    projs = load_json(proj_path)
    existing_projs = {p.get("dataName") for p in projs}

    # Group results by tmpl_name so we do one backup per file
    by_tmpl: Dict[str, List[Dict]] = defaultdict(list)
    for r in results:
        by_tmpl[r["tmpl_name"]].append(r)

    for tmpl_name, tmpl_results in by_tmpl.items():
        equip_path = MODS_DIR / f"{tmpl_name}.json"
        equip_loc_path = MOD_LOC_DIR / f"{tmpl_name}.en"
        _backup(equip_path)
        equip_data = load_json(equip_path)
        existing_equip = {e.get("dataName") for e in equip_data}
        added_items = 0
        for r in tmpl_results:
            for item, loc_line in zip(r["items"], r["loc_items"]):
                idn = item.get("dataName")
                if idn in existing_equip:
                    print(f"  Skip duplicate item: {idn}")
                    continue
                equip_data.append(item)
                existing_equip.add(idn)
                append_loc(equip_loc_path, loc_line)
                added_items += 1
            pdn = r["project"].get("dataName")
            if pdn in existing_projs:
                print(f"  Skip duplicate project: {pdn}")
                continue
            projs.append(r["project"])
            existing_projs.add(pdn)
            append_loc(proj_loc, r["loc_project"])
        save_json(equip_path, equip_data)
        print(f"  Written to {equip_path.name} ({added_items} items added)")

    save_json(proj_path, projs)
    print(f"  Written linking projects to TIProjectTemplate.json")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI-driven Terra Invicta mod content generator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--tier", required=True, choices=["easy", "middle", "full"], help="Generation tier")
    parser.add_argument(
        "--type",
        dest="equip_type",
        default=None,
        choices=list(EQUIPMENT_TYPES.keys()),
        help="Equipment type (required for --tier full)",
    )
    parser.add_argument("--count", type=int, default=5, help="Number of items/sets to generate (default 5)")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Generate and preview, do not write files")
    mode.add_argument("--apply", action="store_true", help="Write results to mod files")

    parser.add_argument("--ai-endpoint", default=DEFAULT_AI_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Per-request timeout in seconds (default {DEFAULT_TIMEOUT})",
    )
    parser.add_argument("--no-cache", action="store_true", help="Ignore cached AI results")
    parser.add_argument("--cache-file", default=str(CACHE_FILE))
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--themes", nargs="*", default=None, help="(middle) Theme hints, one per tech to generate")

    args = parser.parse_args()

    if args.tier == "full" and not args.equip_type:
        parser.error("--tier full requires --type <equipment_type>")

    if args.seed is not None:
        random.seed(args.seed)

    print("Loading game data...")
    game_data = GameData()
    print(
        f"  Base: {len(game_data.base_projects)} projects, "
        f"{len(game_data.base_techs)} techs, "
        f"{len(game_data.base_effects)} effects"
    )
    print(
        f"  Mod:  {len(game_data.mod_projects)} projects, "
        f"{len(game_data.mod_techs)} techs, "
        f"{len(game_data.mod_effects)} effects"
    )

    cache_path = Path(args.cache_file)
    cache = load_cache(cache_path, args.no_cache)

    dry_run = args.dry_run

    if args.tier == "easy":
        print(f"\nGenerating {args.count} easy-tier projects...")
        results = generate_easy(
            args.count,
            game_data,
            args.ai_endpoint,
            args.model,
            args.timeout,
            cache,
            dry_run,
        )
        save_cache(cache_path, cache)
        print_easy_preview(results)
        apply_results("easy", None, results, dry_run)

    elif args.tier == "middle":
        print(f"\nGenerating {args.count} middle-tier tech trees...")
        results = generate_middle(
            args.count,
            game_data,
            args.ai_endpoint,
            args.model,
            args.timeout,
            cache,
            dry_run,
            themes=args.themes,
        )
        save_cache(cache_path, cache)
        print_middle_preview(results)
        apply_results("middle", None, results, dry_run)

    elif args.tier == "full":
        print(f"\nGenerating {args.count} full-tier {args.equip_type} sets...")
        results = generate_full(
            args.equip_type,
            args.count,
            game_data,
            args.ai_endpoint,
            args.model,
            args.timeout,
            cache,
            dry_run,
        )
        save_cache(cache_path, cache)
        print_full_preview(results)
        apply_results("full", args.equip_type, results, dry_run)


if __name__ == "__main__":
    main()
