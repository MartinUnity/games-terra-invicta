#!/usr/bin/env python3
"""Prototype AI worker that calls a local Ollama model and writes a staged candidate.

Usage examples:
  python3 scripts/ai_worker.py --once --dry-run
  python3 scripts/ai_worker.py --once --model gemma2:2b

This is a safe prototype: by default it writes output into `ai-worker/staging/<ts>/candidate.json`
and does not touch `Mods/`.
"""
import argparse
import json
from typing import Optional, Tuple, List, Any
import os
import random
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

import jsonschema
import requests
from jsonschema import Draft7Validator

# local helpers (refactored)
try:
    # When running the script directly from repo root, try short import paths first
    from utils.ai_worker_helpers import extract_json as helpers_extract_json, load_text as helpers_load_text
    from utils.ai_prompts import (
        build_fill_prompt as helpers_build_fill_prompt,
        build_localization_prompt as helpers_build_localization_prompt,
        build_prompt as helpers_build_prompt,
    )
    from utils.ai_worker_helpers import call_model as helpers_call_model, generate_and_extract as helpers_generate_and_extract
except Exception:
    # Fallback when executed from a different working dir or module path
    from scripts.utils.ai_worker_helpers import extract_json as helpers_extract_json, load_text as helpers_load_text
    from scripts.utils.ai_prompts import (
        build_fill_prompt as helpers_build_fill_prompt,
        build_localization_prompt as helpers_build_localization_prompt,
        build_prompt as helpers_build_prompt,
    )
    from scripts.utils.ai_worker_helpers import call_model as helpers_call_model, generate_and_extract as helpers_generate_and_extract


def load_effect_whitelist(path: str):
    """Load a simple whitelist file (one token per line).
    Accepts lines with or without a leading '-' and ignores blank lines and comments ('#').
    Returns a list of tokens (strings).
    """
    # delegate to refactored helper
    try:
        from utils.ai_worker_helpers import load_effect_whitelist as _hel
    except Exception:
        from scripts.utils.ai_worker_helpers import load_effect_whitelist as _hel

    return _hel(path)


def get_effect_whitelist():
    # prefer explicit whitelist file in ai-worker; return empty list if missing
    wl_file = os.path.join(AI_DIR, "effect_whitelist.txt")
    if os.path.exists(wl_file):
        return load_effect_whitelist(wl_file)
    return []


def effect_matches_whitelist(contexts, whitelist):
    try:
        from utils.ai_worker_helpers import effect_matches_whitelist as _emw
    except Exception:
        from scripts.utils.ai_worker_helpers import effect_matches_whitelist as _emw
    return _emw(contexts, whitelist)


def is_penalty_effect(name: str) -> bool:
    """Return True if the effect name contains the word 'penalty' (case-insensitive)."""
    try:
        from utils.ai_worker_helpers import is_penalty_effect as _ipe
    except Exception:
        from scripts.utils.ai_worker_helpers import is_penalty_effect as _ipe
    return _ipe(name)


# Pydantic removed: we prefer JSON Schema validation (schema.json)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AI_DIR = os.path.join(ROOT, "ai-worker")
DEFAULT_CONFIG = os.path.join(AI_DIR, "config.yml")
REQUIREMENTS_MD = os.path.join(AI_DIR, "requirements.md")
PROMPT_TEMPLATE = os.path.join(AI_DIR, "prompt_templates.md")


def load_text(path):
    # backward compatible wrapper to keep the original API in this module
    return helpers_load_text(path)


def call_model(model: str, prompt: str, temperature: float = 0.5, timeout: int = 300, ollama_url: str | None = None):
    """Delegate to refactored call_model helper (supports HTTP then CLI)."""
    return helpers_call_model(model, prompt, temperature=temperature, timeout=timeout, ollama_url=ollama_url)


def extract_json(text: str):
    # delegate to refactored helper with improved heuristics
    return helpers_extract_json(text)


def minimal_validate(candidate: dict, schema_path: Optional[str] = None) -> Tuple[bool, List[str]]:
    try:
        from utils.ai_worker_helpers import minimal_validate as _mv
    except Exception:
        from scripts.utils.ai_worker_helpers import minimal_validate as _mv
    return _mv(candidate, schema_path=schema_path)


def write_staged(candidate: dict, staging_root: str, raw_output: Optional[str] = None, meta: Optional[dict] = None) -> str:
    try:
        from utils.ai_worker_helpers import write_staged as _ws
    except Exception:
        from scripts.utils.ai_worker_helpers import write_staged as _ws
    return _ws(candidate, staging_root, raw_output=raw_output, meta=meta)


def backup_staged(staging_root: str, backup_root: str):
    try:
        from utils.ai_worker_helpers import backup_staged as _bs
    except Exception:
        from scripts.utils.ai_worker_helpers import backup_staged as _bs
    return _bs(staging_root, backup_root)


def apply_candidate_to_mods(candidate: dict, localization_text: str, mods_path: str, loc_path: str, backup_root: str):
    """Append candidate to mods_path JSON array and append localization_text to loc_path.
    Create backups of both files under backup_root with a timestamp. Returns (ok, errors).
    """
    try:
        from utils.ai_worker_helpers import apply_candidate_to_mods as _ac
    except Exception:
        from scripts.utils.ai_worker_helpers import apply_candidate_to_mods as _ac
    return _ac(candidate, localization_text, mods_path, loc_path, backup_root)


def build_prompt(requirements_md: str, prompt_template: str):
    return helpers_build_prompt(requirements_md, prompt_template)


def load_project_templates(path: str):
    try:
        from utils.ai_worker_helpers import load_project_templates as _lpt
    except Exception:
        from scripts.utils.ai_worker_helpers import load_project_templates as _lpt

    return _lpt(path)


def select_template_and_effect(
    projects: list, tieffects_map: dict, whitelist: list, category: Optional[str] = None, require_prereq: bool = False
):
    # pick a category if not provided
    candidates = projects
    if category:
        candidates = [p for p in projects if p.get("techCategory") == category]
    if not candidates:
        candidates = projects
    if not candidates:
        return (None, None)
    # Prefer templates that have a non-empty prereqs list when requested
    if require_prereq:
        pref = [
            p for p in candidates if isinstance(p, dict) and isinstance(p.get("prereqs"), list) and p.get("prereqs")
        ]
        if pref:
            template = random.choice(pref)
        else:
            # fallback and log that we had no templates with prereqs
            try:
                logpath = os.path.join(AI_DIR, "generation_issues.log")
                with open(logpath, "a", encoding="utf-8") as lf:
                    lf.write(
                        f"{datetime.now(timezone.utc).isoformat()} - no templates with prereqs for category={category!r}; candidates={len(candidates)}\n"
                    )
            except Exception:
                pass
            template = random.choice(candidates)
    else:
        template = random.choice(candidates)
    # try to pick an effect from the template or from global tieffects by checking contexts against whitelist
    chosen_effect = None
    # gather effects referenced in template
    if isinstance(template, dict):
        # look for keys that look like effects
        for k, v in template.items():
            if isinstance(v, str) and v.startswith("Effect_"):
                # accept only if in tieffects_map and matches whitelist
                if (
                    not is_penalty_effect(v)
                    and v in tieffects_map
                    and effect_matches_whitelist(tieffects_map.get(v, []), whitelist)
                ):
                    chosen_effect = v
                    break
        # maybe template has an effects array
        if not chosen_effect:
            for v in template.values():
                if isinstance(v, list):
                    for it in v:
                        if (
                            isinstance(it, str)
                            and it.startswith("Effect_")
                            and (not is_penalty_effect(it))
                            and it in tieffects_map
                            and effect_matches_whitelist(tieffects_map.get(it, []), whitelist)
                        ):
                            chosen_effect = it
                            break
                    if chosen_effect:
                        break
    # fallback: random tieffect
    if not chosen_effect and tieffects_map:
        valid = [
            e
            for e, ctxs in tieffects_map.items()
            if (not is_penalty_effect(e)) and effect_matches_whitelist(ctxs, whitelist)
        ]
        if valid:
            chosen_effect = random.choice(valid)
        else:
            chosen_effect = None
    return (template, chosen_effect)


def collect_tieffects(path: str):
    try:
        from utils.ai_worker_helpers import collect_tieffects as _ct
    except Exception:
        from scripts.utils.ai_worker_helpers import collect_tieffects as _ct
    return _ct(path)


def roll_research_cost(base_cost):
    try:
        from utils.ai_worker_helpers import roll_research_cost as _rrc
    except Exception:
        from scripts.utils.ai_worker_helpers import roll_research_cost as _rrc
    return _rrc(base_cost)


def build_fill_prompt(template: dict, chosen_effect: Optional[str], research_cost: int) -> str:
    return helpers_build_fill_prompt(template, chosen_effect, research_cost)


def build_localization_prompt(candidate: Optional[dict], tieffects_map: Optional[dict] = None) -> str:
    return helpers_build_localization_prompt(candidate, tieffects_map)


def enforce_candidate_defaults(candidate: dict):
    # Ensure required hardcoded/default fields exist and have proper types
    if not isinstance(candidate, dict):
        return candidate
    candidate.setdefault("AI_techRole", "None")
    candidate.setdefault("AI_criticalTech", False)
    candidate.setdefault("AI_projectRole", "SpaceResources")
    candidate.setdefault("oneTimeGlobally", False)
    candidate.setdefault("repeatable", False)
    candidate.setdefault("resourcesGranted", [])
    candidate.setdefault("factionAvailableChance", random.randint(20, 100))
    # randomize initialUnlockChance 1-20 and deltaUnlockChance 1-10 if not provided
    if "initialUnlockChance" not in candidate:
        candidate["initialUnlockChance"] = random.randint(1, 20)
    if "deltaUnlockChance" not in candidate:
        candidate["deltaUnlockChance"] = random.randint(1, 10)
    candidate.setdefault("maxUnlockChance", random.randint(20, 100))
    return candidate


# effect keyword extraction removed; keep names freer but generally consistent with category/effect


def cleanup_staging(staging_root: str, keep: int = 5):
    """Keep only the most recent `keep` directories in staging_root (by name/timestamp)."""
    try:
        entries = [d for d in os.listdir(staging_root) if os.path.isdir(os.path.join(staging_root, d))]
        if len(entries) <= keep:
            return
        entries.sort()
        to_remove = entries[0 : max(0, len(entries) - keep)]
        for d in to_remove:
            path = os.path.join(staging_root, d)
            try:
                shutil.rmtree(path)
            except Exception:
                pass
    except FileNotFoundError:
        return


def run_cycle(args):
    # delegate to refactored runner module
    try:
        from utils.ai_runner import run_cycle as _run
    except Exception:
        from scripts.utils.ai_runner import run_cycle as _run

    return _run(args)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    p.add_argument(
        "--count",
        type=int,
        default=1,
        help="When used with --once, run this many cycles sequentially (default 1).",
    )
    p.add_argument("--dry-run", action="store_true", help="Do not auto-apply; write staged output only")
    p.add_argument("--model", default="gemma2:2b")
    p.add_argument("--temperature", type=float, default=0.5)
    p.add_argument("--interval", type=int, default=12, help="Interval hours between runs when running continuously")
    p.add_argument("--staging-dir", default=os.path.join(AI_DIR, "staging"))
    p.add_argument("--backup-dir", default=os.path.join(ROOT, "LocalSaves", "ai-backups"))
    p.add_argument(
        "--attempts", type=int, default=3, help="Number of LLM attempts per cycle to generate a friendlyName"
    )
    p.add_argument("--category", type=str, default=None, help="Optional techCategory to restrict template selection")
    p.add_argument(
        "--ollama-url",
        default=os.environ.get("OLLAMA_URL", None),
        help="Base URL for Ollama HTTP API, e.g. http://host:11434",
    )
    p.add_argument(
        "--generate-localization", action="store_true", help="Generate localization snippet for valid candidate"
    )
    p.add_argument(
        "--loc-attempts", type=int, default=3, help="Number of attempts to ask the model for a short description"
    )
    p.add_argument(
        "--auto-apply",
        action="store_true",
        help="Append valid candidate to Mods/TIProjectTemplate.json and append localization (creates backups).",
    )
    p.add_argument(
        "--print-output",
        action="store_true",
        help="When used with --dry-run, also print the generated candidate and localization to the console",
    )
    p.add_argument("--debug", action="store_true", help="Enable debug logging of raw model outputs and extraction attempts")
    p.add_argument(
        "--probe-wait",
        type=float,
        default=6.0,
        help="Seconds to probe Ollama for model readiness before HTTP call (default 6.0)",
    )
    p.add_argument(
        "--retry-sleep-base",
        type=float,
        default=0.25,
        help="Base seconds used for exponential backoff between retries (default 0.25)",
    )
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.staging_dir, exist_ok=True)
    # backup_dir may be a path; ensure its parent exists before use
    try:
        parent = os.path.dirname(args.backup_dir) or "."
        os.makedirs(parent, exist_ok=True)
    except Exception:
        pass
    if args.once:
        count = max(1, getattr(args, "count", 1))
        for i in range(count):
            try:
                print(f"Run {i+1}/{count}")
                run_cycle(args)
            except Exception as e:
                print("Error during run:", e)
                sys.exit(1)
        return
    # long running loop
    while True:
        try:
            run_cycle(args)
        except Exception as e:
            print("Error during run:", e)
        time.sleep(max(60, args.interval * 3600))


if __name__ == "__main__":
    main()
