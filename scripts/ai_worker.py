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


def load_effect_whitelist(path: str):
    """Load a simple whitelist file (one token per line).
    Accepts lines with or without a leading '-' and ignores blank lines and comments ('#').
    Returns a list of tokens (strings).
    """
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if s.startswith("-"):
                    token = s.lstrip("- ").strip()
                else:
                    token = s
                if token:
                    out.append(token)
    except Exception:
        pass
    return out


def get_effect_whitelist():
    # prefer explicit whitelist file in ai-worker; return empty list if missing
    wl_file = os.path.join(AI_DIR, "effect_whitelist.txt")
    if os.path.exists(wl_file):
        return load_effect_whitelist(wl_file)
    return []


def effect_matches_whitelist(contexts, whitelist):
    if not contexts or not whitelist:
        return False
    for ctx in contexts:
        for item in whitelist:
            if isinstance(ctx, str) and ctx.startswith(item):
                return True
    return False


# Pydantic removed: we prefer JSON Schema validation (schema.json)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AI_DIR = os.path.join(ROOT, "ai-worker")
DEFAULT_CONFIG = os.path.join(AI_DIR, "config.yml")
REQUIREMENTS_MD = os.path.join(AI_DIR, "requirements.md")
PROMPT_TEMPLATE = os.path.join(AI_DIR, "prompt_templates.md")


def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def call_model_via_cli(model: str, prompt: str, temperature: float = 0.5, timeout: int = 300):
    cmd = ["ollama", "run", model]
    try:
        proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError("ollama CLI not found in PATH")
    if proc.returncode != 0:
        raise RuntimeError(f"ollama run failed: {proc.stderr.strip()}")
    return proc.stdout


def call_model_via_http(url: str, model: str, prompt: str, temperature: float = 0.5, timeout: int = 300):
    """Call Ollama HTTP API. url should be base like http://host:11434 or full endpoint.
    Tries POST to /api/generate?model=<model> with JSON payload {"prompt": prompt, "temperature": ...}.
    Returns response text.
    """
    endpoint = url.rstrip("/")
    if not endpoint.endswith("/api/generate"):
        endpoint = endpoint + "/api/generate"
    params = {"model": model}
    payload = {"prompt": prompt, "temperature": temperature}
    try:
        resp = requests.post(endpoint, params=params, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        raise RuntimeError(f"Ollama HTTP request failed: {e}")


def call_model(model: str, prompt: str, temperature: float = 0.5, timeout: int = 300, ollama_url: str = None):
    """Try HTTP API first (if ollama_url provided or default localhost), then fall back to CLI."""
    # prefer explicit ollama_url, then env, then localhost
    ollama_url = ollama_url or os.environ.get("OLLAMA_URL")
    if not ollama_url:
        ollama_url = "http://localhost:11434"
    # try HTTP
    try:
        return call_model_via_http(ollama_url, model, prompt, temperature, timeout)
    except Exception:
        # fallback to CLI with a warning
        try:
            return call_model_via_cli(model, prompt, temperature, timeout)
        except Exception as e:
            raise RuntimeError(f"Model call failed (HTTP and CLI attempts): {e}")


def extract_json(text: str):
    """Try to parse JSON from model output. If the model emits extra text, attempt to find first JSON object/array."""
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        # crude extraction: find first { ... } or [ ... ]
        start = text.find("{")
        if start == -1:
            start = text.find("[")
        if start == -1:
            raise
        # attempt to find matching bracket by trying progressive slices
        for end in range(len(text), start, -1):
            try:
                return json.loads(text[start:end])
            except Exception:
                continue
        raise


def minimal_validate(candidate: dict, schema_path: str = None) -> (bool, list):
    """Validate candidate against provided JSON schema if available, otherwise perform minimal checks.
    Returns (ok, errors).
    """
    errors = []
    if schema_path and os.path.exists(schema_path):
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            validator = Draft7Validator(schema)
            errs = list(validator.iter_errors(candidate))
            for e in errs:
                errors.append(f'{"/".join([str(p) for p in e.path])}: {e.message}')
            return (len(errors) == 0, errors)
        except Exception as e:
            errors.append("schema validation failed to run: " + str(e))
            return (False, errors)
    # fallback minimal checks
    required = ["dataName", "friendlyName", "techCategory", "researchCost", "prereqs", "TIEffect"]
    for k in required:
        if k not in candidate:
            errors.append(f"missing {k}")
    if "researchCost" in candidate and not isinstance(candidate["researchCost"], (int, float)):
        errors.append("researchCost must be a number")
    if "prereqs" in candidate and not isinstance(candidate["prereqs"], list):
        errors.append("prereqs must be a list")
    if "TIEffect" in candidate and not isinstance(candidate["TIEffect"], dict):
        errors.append("TIEffect must be an object")
    return (len(errors) == 0, errors)


def write_staged(candidate: dict, staging_root: str, raw_output: str = None, meta: dict = None):
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(staging_root, ts)
    os.makedirs(dest, exist_ok=True)
    candidate_path = os.path.join(dest, "candidate.json")
    with open(candidate_path, "w", encoding="utf-8") as f:
        json.dump(candidate, f, indent=2, ensure_ascii=False)
    if raw_output is not None:
        with open(candidate_path + ".raw.txt", "w", encoding="utf-8") as f:
            f.write(raw_output)
    if meta is not None:
        with open(candidate_path + ".meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    return candidate_path


def backup_staged(staging_root: str, backup_root: str):
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(backup_root, ts)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copytree(staging_root, dest)
    return dest


def apply_candidate_to_mods(candidate: dict, localization_text: str, mods_path: str, loc_path: str, backup_root: str):
    """Append candidate to mods_path JSON array and append localization_text to loc_path.
    Create backups of both files under backup_root with a timestamp. Returns (ok, errors).
    """
    errors = []
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        os.makedirs(os.path.dirname(mods_path), exist_ok=True)
        # backup mods file if exists
        if os.path.exists(mods_path):
            bmods = os.path.join(backup_root, f"mods_{ts}.json")
            os.makedirs(os.path.dirname(bmods), exist_ok=True)
            shutil.copy2(mods_path, bmods)
        # load existing mods JSON (expecting list) or create new list
        mods_list = []
        if os.path.exists(mods_path):
            with open(mods_path, "r", encoding="utf-8") as mf:
                try:
                    mods_list = json.load(mf)
                    if not isinstance(mods_list, list):
                        errors.append("mods file does not contain a JSON list")
                        mods_list = []
                except Exception as e:
                    errors.append(f"failed to parse mods JSON: {e}")
                    mods_list = []
        # Append candidate (make a shallow copy)
        mods_list.append(candidate)
        # write back
        with open(mods_path, "w", encoding="utf-8") as mf:
            json.dump(mods_list, mf, indent=2, ensure_ascii=False)
    except Exception as e:
        errors.append(f"failed to write mods file: {e}")

    try:
        # backup localization file
        if os.path.exists(loc_path):
            bloc = os.path.join(backup_root, f"loc_{ts}.txt")
            os.makedirs(os.path.dirname(bloc), exist_ok=True)
            shutil.copy2(loc_path, bloc)
        # append localization_text (string with trailing newline(s) expected)
        os.makedirs(os.path.dirname(loc_path), exist_ok=True)
        with open(loc_path, "a", encoding="utf-8") as lf:
            lf.write(localization_text)
            if not localization_text.endswith("\n"):
                lf.write("\n")
    except Exception as e:
        errors.append(f"failed to append localization: {e}")

    return (len(errors) == 0, errors)


def build_prompt(requirements_md: str, prompt_template: str):
    base = ""
    if os.path.exists(prompt_template):
        base += load_text(prompt_template) + "\n\n"
    base += "You are an assistant that must return exactly one JSON object only (no surrounding text)."
    base += "\nFollow the rules and constraints in the following requirements document:\n\n"
    base += requirements_md
    base += "\n\nReturn only the JSON candidate object that fits the schema described above."
    base += '\nImportant: include an "effects" array containing one existing effect ID (string) that exactly matches an entry in /home/martin/Games/TerraInvicta/templates/TIEffectTemplate.json. Do NOT invent new effect IDs or full effect objects. If you cannot pick an existing effect, return { "error": "explanation" }.'
    base += '\n\nSTRICT WRAPPER: Output MUST be exactly three lines:\n<json>\n<the JSON object on one or more lines>\n</json>\nNo other text is allowed before or after these tags. If you cannot follow this format, return { "error": "reason" } inside the wrapper.'

    # Append allowed prereqs list derived from the game's TIProjectTemplate.json so the model can pick a valid prereq
    project_template_path = "/home/martin/Games/TerraInvicta/templates/TIProjectTemplate.json"
    try:
        if os.path.exists(project_template_path):
            with open(project_template_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # data may be an array of project objects
            names = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "dataName" in item:
                        names.append(item["dataName"])
            else:
                # try to extract any occurrences of dataName in nested structure
                def collect_names(obj):
                    if isinstance(obj, dict):
                        if "dataName" in obj and isinstance(obj["dataName"], str):
                            names.append(obj["dataName"])
                        for v in obj.values():
                            collect_names(v)
                    elif isinstance(obj, list):
                        for v in obj:
                            collect_names(v)

                collect_names(data)
            # limit list length to keep prompt concise
            if names:
                sample = names[:200]
                base += "\n\nAllowed prereqs (choose exactly one from this list):\n" + ", ".join(sample) + "\n"
    except Exception:
        pass
    # Append allowed effects list from TIEffectTemplate.json so the model can pick an exact existing effect ID
    tieffect_path = "/home/martin/Games/TerraInvicta/templates/TIEffectTemplate.json"
    try:
        if os.path.exists(tieffect_path):
            with open(tieffect_path, "r", encoding="utf-8") as f:
                te = json.load(f)
            # build whitelist (prefer ai-worker/effect_whitelist.txt if present)
            whitelist = get_effect_whitelist()
            effect_names = []

            def collect_effects(obj):
                if isinstance(obj, dict):
                    if "dataName" in obj and isinstance(obj["dataName"], str) and obj["dataName"].startswith("Effect_"):
                        contexts = obj.get("contexts") or obj.get("context") or []
                        if isinstance(contexts, str):
                            contexts = [contexts]
                        if effect_matches_whitelist(contexts, whitelist):
                            effect_names.append(obj["dataName"])
                    for v in obj.values():
                        collect_effects(v)
                elif isinstance(obj, list):
                    for v in obj:
                        collect_effects(v)

            collect_effects(te)
            if effect_names:
                eff_sample = effect_names[:500]
                base += "\n\nAllowed effect IDs (choose one or more):\n" + ", ".join(eff_sample) + "\n"
    except Exception:
        pass
    # Note: Pydantic schema removed — rely on ai-worker/schema.json for validation guidance
    return base


def load_project_templates(path: str):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        # try to find list inside
        lists = []

        def collect(obj):
            if isinstance(obj, list):
                lists.append(obj)
            elif isinstance(obj, dict):
                for v in obj.values():
                    collect(v)

        collect(data)
        return lists[0] if lists else []
    except Exception:
        return []


def select_template_and_effect(projects: list, tieffects_map: dict, whitelist: list, category: str = None):
    # pick a category if not provided
    candidates = projects
    if category:
        candidates = [p for p in projects if p.get("techCategory") == category]
    if not candidates:
        candidates = projects
    if not candidates:
        return (None, None)
    template = random.choice(candidates)
    # try to pick an effect from the template or from global tieffects by checking contexts against whitelist
    chosen_effect = None
    # gather effects referenced in template
    if isinstance(template, dict):
        # look for keys that look like effects
        for k, v in template.items():
            if isinstance(v, str) and v.startswith("Effect_"):
                # accept only if in tieffects_map and matches whitelist
                if v in tieffects_map and effect_matches_whitelist(tieffects_map.get(v, []), whitelist):
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
                            and it in tieffects_map
                            and effect_matches_whitelist(tieffects_map.get(it, []), whitelist)
                        ):
                            chosen_effect = it
                            break
                    if chosen_effect:
                        break
    # fallback: random tieffect
    if not chosen_effect and tieffects_map:
        valid = [e for e, ctxs in tieffects_map.items() if effect_matches_whitelist(ctxs, whitelist)]
        if valid:
            chosen_effect = random.choice(valid)
        else:
            chosen_effect = None
    return (template, chosen_effect)


def collect_tieffects(path: str):
    # Return a mapping of effect dataName -> contexts (list)
    out = {}
    if not os.path.exists(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            te = json.load(f)

        def collect(obj):
            if isinstance(obj, dict):
                if "dataName" in obj and isinstance(obj["dataName"], str) and obj["dataName"].startswith("Effect_"):
                    contexts = obj.get("contexts") or obj.get("context") or []
                    if isinstance(contexts, str):
                        contexts = [contexts]
                    if not isinstance(contexts, list):
                        contexts = []
                    out[obj["dataName"]] = contexts
                for v in obj.values():
                    collect(v)
            elif isinstance(obj, list):
                for v in obj:
                    collect(v)

        collect(te)
        return out
    except Exception:
        return out


def roll_research_cost(base_cost):
    try:
        base = float(base_cost)
    except Exception:
        base = 1000.0
    mult = 1.0 + random.uniform(0.05, 0.5)
    return int(max(1, round(base * mult)))


def build_fill_prompt(template: dict, chosen_effect: str, research_cost: int):
    # concise prompt that asks the model only for a friendlyName and optional subtitle/description
    lines = []
    lines.append("You are asked to produce a short, evocative project friendly name for a space strategy game.")
    lines.append("Return ONLY a JSON object wrapped in the exact three-line wrapper shown below.")
    lines.append("The JSON object must contain these keys: friendlyName (string), shortDescription (string, optional).")
    lines.append("")
    lines.append(
        "Important: The `friendlyName` must be thematically consistent with the project's `techCategory` and the chosen effect."
    )
    lines.append(
        "For example, if techCategory is 'Energy' and effect is 'Effect_MiningVolatilesBonus', prefer names that imply improved volatile/mining capacity (e.g. 'Volatile Resource Extraction')."
    )
    lines.append("Do NOT return names that imply unrelated gameplay (e.g., 'Stellar Domination' for a mining bonus).")
    lines.append("Do NOT return any other keys.")
    lines.append("")
    lines.append("CONTEXT:")
    if template is not None:
        lines.append(f"Example project template dataName (example): {template.get('dataName', '<none>')}")
        lines.append(f"Category: {template.get('techCategory', '<unknown>')}")
        lines.append(f"Example researchCost (template): {template.get('researchCost', '<n>')}")
    lines.append(f"Target researchCost for new project: {research_cost}")
    if chosen_effect:
        lines.append(f"Required effect for project: {chosen_effect}")
    lines.append("")
    lines.append("STRICT WRAPPER: Output MUST be exactly three lines:")
    lines.append("<json>")
    lines.append('{"friendlyName": "Example Name", "shortDescription": "..."}')
    lines.append("</json>")
    lines.append("No other text is allowed before or after these tags.")
    return "\n".join(lines)


def build_localization_prompt(candidate: dict, tieffects_map: dict = None):
    dn = candidate.get("dataName", "Project_Unknown")
    fn = candidate.get("friendlyName", "Unknown Project")
    cat = candidate.get("techCategory", "Unknown")
    rc = candidate.get("researchCost", 0)
    effs = candidate.get("effects", [])
    prompt = []
    prompt.append(
        "You are asked to produce a short, game-appropriate one-line summary for a project in a space strategy game."
    )
    prompt.append("Return ONLY a JSON object wrapped in the exact three-line wrapper below.")
    prompt.append("The JSON object must contain the key: shortDescription (string).")
    prompt.append("")
    prompt.append("CONTEXT:")
    prompt.append(f"Project dataName: {dn}")
    prompt.append(f"Friendly name: {fn}")
    prompt.append(f"Category: {cat}")
    prompt.append(f"Research cost: {rc}")
    # include prereqs if present so the model can reference source tech/context
    prereqs = candidate.get("prereqs", [])
    if prereqs:
        prompt.append("Prereqs: " + ", ".join(prereqs))
    if effs:
        # Provide effect IDs and any known contexts so the model can infer meaning
        eff_lines = []
        for e in effs:
            ctxs = []
            if tieffects_map and isinstance(tieffects_map, dict):
                ctxs = tieffects_map.get(e, [])
            if ctxs:
                eff_lines.append(f"{e} (contexts: {', '.join(ctxs)})")
            else:
                eff_lines.append(e)
        prompt.append("Effects: " + ", ".join(eff_lines))
    prompt.append("")
    prompt.append("")
    prompt.append("REQUIREMENTS:")
    prompt.append("- shortDescription must be 120-200 characters long (counting characters, inclusive).")
    prompt.append(
        "- Tone: clear scifi, 'scientific' and plausible — prefer concise, technical or investigative phrasing rather than grandiose metaphors."
    )
    prompt.append(
        "- Avoid flowery or unrelated imagery; make the description sound like an in-universe scientific/engineering blurb."
    )
    prompt.append(
        "- The description should be coherent with the project's category, prereqs, and effects; avoid repeating the friendlyName verbatim."
    )
    prompt.append(
        "- If the project has a prereq, you may incorporate that prereq name or its implied tech lineage briefly to give context (e.g., 'derived from VaporCore Fission Reactor tech')."
    )
    prompt.append("")
    prompt.append("STRICT WRAPPER: Output MUST be exactly three lines:")
    prompt.append("<json>")
    prompt.append('{"shortDescription": "An advanced technique that ..."}')
    prompt.append("</json>")
    prompt.append("No other text is allowed before or after these tags.")
    return "\n".join(prompt)


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
    candidate.setdefault("factionAvailableChance", 100)
    # randomize initialUnlockChance 1-20 and deltaUnlockChance 1-10 if not provided
    if "initialUnlockChance" not in candidate:
        candidate["initialUnlockChance"] = random.randint(1, 20)
    if "deltaUnlockChance" not in candidate:
        candidate["deltaUnlockChance"] = random.randint(1, 10)
    candidate.setdefault("maxUnlockChance", 100)
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
    # Try deterministic template selection + multi-attempt name generation
    # Ensure these are defined early to avoid UnboundLocalError in error paths
    staging_root = getattr(args, "staging_dir", os.path.join(AI_DIR, "staging"))
    candidate_path = None
    requirements_md = load_text(REQUIREMENTS_MD)
    prompt_template = load_text(PROMPT_TEMPLATE)
    project_template_path = "/home/martin/Games/TerraInvicta/templates/TIProjectTemplate.json"
    tieffect_path = "/home/martin/Games/TerraInvicta/templates/TIEffectTemplate.json"
    projects = load_project_templates(project_template_path)
    tieffects_map = collect_tieffects(tieffect_path)
    whitelist = load_effect_whitelist(REQUIREMENTS_MD)

    template, chosen_effect = select_template_and_effect(projects, tieffects_map, whitelist, category=args.category)
    # existing dataName set for uniqueness checks (include template + mods)
    existing_data_names = set()
    for p in projects:
        if isinstance(p, dict) and "dataName" in p:
            existing_data_names.add(p["dataName"])
    # also include any modded projects to avoid name collisions
    mods_path = os.path.join(ROOT, "Mods", "TIProjectTemplate.json")
    if os.path.exists(mods_path):
        mod_projects = load_project_templates(mods_path)
        for mp in mod_projects:
            if isinstance(mp, dict) and "dataName" in mp:
                existing_data_names.add(mp["dataName"])
    # if we couldn't select a template or effect, fall back to full prompt behavior
    if template is None:
        prompt = build_prompt(requirements_md, prompt_template)
        print("Calling model", args.model)
        out = call_model(args.model, prompt, temperature=args.temperature, ollama_url=args.ollama_url)
        try:
            candidate = extract_json(out)
        except Exception:
            candidate = {"error": "model output not JSON"}
        # enforce defaults so the game can parse the object safely
        if isinstance(candidate, dict):
            candidate = enforce_candidate_defaults(candidate)
        # Validate using JSON Schema (schema.json) only
        errors = []
        ok = False
        schema_path = os.path.join(AI_DIR, "schema.json")
        if os.path.exists(schema_path):
            ok, schema_errors = minimal_validate(candidate, schema_path=schema_path)
            errors.extend(schema_errors)
        staging_root = args.staging_dir
        meta = {
            "model": args.model,
            "temperature": args.temperature,
            "valid": ok,
            "errors": errors,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        candidate_path = write_staged(candidate, staging_root, raw_output=out, meta=meta)
        result = {"candidate_path": candidate_path, "valid": ok, "errors": errors}
        with open(candidate_path + ".result.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print("Wrote staged candidate to", candidate_path)
        if getattr(args, "dry_run", False) and getattr(args, "print_output", False):
            try:
                print("\n--- Generated candidate (staged) ---")
                print(json.dumps(candidate, indent=2, ensure_ascii=False))
                if out:
                    print("\n--- Raw model output ---\n")
                    print(out)
            except Exception:
                pass
        if not ok:
            print("Validation errors:", errors)
        if args.backup_dir:
            try:
                b = backup_staged(staging_root, args.backup_dir)
                print("Backed up staging to", b)
            except Exception as e:
                print("Backup failed:", e)
        try:
            cleanup_staging(staging_root, keep=5)
        except Exception:
            pass
        return result

    # We have a template and an effect; compute target research cost and build a small prompt
    base_cost = template.get("researchCost", template.get("cost", 1000))
    target_cost = roll_research_cost(base_cost)
    attempts = max(1, getattr(args, "attempts", 3))
    last_errors = []
    final_candidate = None
    final_ok = False
    final_meta = None
    for attempt in range(attempts):
        small_prompt = build_fill_prompt(template, chosen_effect, target_cost)
        try:
            out = call_model(args.model, small_prompt, temperature=args.temperature, ollama_url=args.ollama_url)
        except Exception as e:
            out = str(e)
        # extract the small JSON with friendlyName
        try:
            small = extract_json(out)
        except Exception:
            small = {"error": "model output not JSON"}

        # build full candidate ourselves from template + small
        candidate = {}
        # dataName from friendlyName (remove non-alnum, spaces -> _)
        fname = small.get("friendlyName") if isinstance(small, dict) else None
        if not fname or not isinstance(fname, str):
            last_errors.append("model did not return a valid friendlyName")
            continue
        # allow goofy names — they should still be thematically reasonable per the prompt
        data_name = "Project_" + "".join([c if c.isalnum() else "_" for c in fname.replace(" ", "_")])
        # ensure uniqueness of dataName
        if data_name in existing_data_names:
            last_errors.append(f"dataName already exists: {data_name}")
            continue
        candidate["dataName"] = data_name
        candidate["friendlyName"] = fname
        candidate["techCategory"] = template.get("techCategory", "Unknown")
        candidate["researchCost"] = target_cost
        # prereqs: pick one from template.prereqs if available
        prereqs = []
        if isinstance(template.get("prereqs"), list) and template.get("prereqs"):
            prereqs = [random.choice(template.get("prereqs"))]
        candidate["prereqs"] = prereqs
        # effects: use chosen_effect
        candidate["effects"] = [chosen_effect] if chosen_effect else []

        # enforce required defaults and randomized unlock chances
        candidate = enforce_candidate_defaults(candidate)

        # Validate constructed candidate via JSON Schema only
        errors = []
        ok = False
        schema_path = os.path.join(AI_DIR, "schema.json")
        if os.path.exists(schema_path):
            ok, schema_errors = minimal_validate(candidate, schema_path=schema_path)
            errors.extend(schema_errors)

        meta = {
            "model": args.model,
            "temperature": args.temperature,
            "valid": ok,
            "errors": errors,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "attempt": attempt + 1,
        }
        staging_root = args.staging_dir
        candidate_path = write_staged(candidate, staging_root, raw_output=out, meta=meta)
        result = {"candidate_path": candidate_path, "valid": ok, "errors": errors}
        with open(candidate_path + ".result.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print("Wrote staged candidate to", candidate_path)
        if ok:
            final_candidate = candidate
            final_ok = True
            final_meta = meta
            break
        else:
            last_errors.extend(errors)

    if args.backup_dir:
        try:
            b = backup_staged(staging_root, args.backup_dir)
            print("Backed up staging to", b)
        except Exception as e:
            print("Backup failed:", e)
    try:
        cleanup_staging(staging_root, keep=5)
    except Exception:
        pass
    if final_ok:
        # optionally generate localization for the produced candidate
        if getattr(args, "generate_localization", False):
            # try a few attempts to get a shortDescription from the model
            loc_ok = False
            loc_errors = []
            for la in range(max(1, getattr(args, "loc_attempts", 3))):
                loc_prompt = build_localization_prompt(final_candidate, tieffects_map)
                try:
                    loc_out = call_model(
                        args.model, loc_prompt, temperature=args.temperature, ollama_url=args.ollama_url
                    )
                except Exception as e:
                    loc_out = str(e)
                try:
                    loc_obj = extract_json(loc_out)
                except Exception:
                    loc_obj = {"error": "model output not JSON"}
                if (
                    isinstance(loc_obj, dict)
                    and "shortDescription" in loc_obj
                    and isinstance(loc_obj["shortDescription"], str)
                ):
                    # write localization snippet into the staging folder
                    loc_lines = []
                    dn = final_candidate.get("dataName")
                    fn = final_candidate.get("friendlyName")
                    loc_lines.append(f"TIProjectTemplate.displayName.{dn}={fn}")
                    loc_lines.append(f"TIProjectTemplate.summary.{dn}={loc_obj['shortDescription']}")
                    loc_dest = os.path.join(os.path.dirname(candidate_path), "localization.txt")
                    with open(loc_dest, "w", encoding="utf-8") as lf:
                        lf.write("\n".join(loc_lines) + "\n")
                    loc_ok = True
                    break
                else:
                    loc_errors.append(str(loc_obj))
            # add localization result to meta file
            try:
                meta_path = candidate_path + ".meta.json"
                if os.path.exists(meta_path):
                    with open(meta_path, "r", encoding="utf-8") as mf:
                        m = json.load(mf)
                else:
                    m = {}
                m["localization_generated"] = loc_ok
                if not loc_ok:
                    m["localization_errors"] = loc_errors
                with open(meta_path, "w", encoding="utf-8") as mf:
                    json.dump(m, mf, indent=2)
            except Exception:
                pass
        # If running as a dry-run and requested, print the generated candidate and localization to console
        if getattr(args, "dry_run", False) and getattr(args, "print_output", False):
            try:
                to_print = final_candidate if final_candidate else candidate
                print("\n--- Generated candidate (staged) ---")
                print(json.dumps(to_print, indent=2, ensure_ascii=False))
                loc_path = os.path.join(os.path.dirname(candidate_path), "localization.txt")
                if os.path.exists(loc_path):
                    print("\n--- Localization ---")
                    with open(loc_path, "r", encoding="utf-8") as lf:
                        print(lf.read().strip())
            except Exception:
                pass
        # Optionally auto-apply into Mods and localization files (with backups)
        if getattr(args, "auto_apply", False):
            if getattr(args, "dry_run", False):
                print("Auto-apply requested but skipped because --dry-run is set.")
            else:
                mods_path = os.path.join(ROOT, "Mods", "TIProjectTemplate.json")
                mods_loc_path = os.path.join(ROOT, "Mods", "Localization", "en", "TIProjectTemplate.en")
                # prefer localization written in staging
                loc_staging = os.path.join(os.path.dirname(candidate_path), "localization.txt")
                if os.path.exists(loc_staging):
                    try:
                        with open(loc_staging, "r", encoding="utf-8") as lf:
                            loc_text = lf.read()
                    except Exception:
                        loc_text = ""
                else:
                    dn = final_candidate.get("dataName")
                    fn = final_candidate.get("friendlyName")
                    loc_text = f"TIProjectTemplate.displayName.{dn}={fn}\nTIProjectTemplate.summary.{dn}=\n"
                ok, apply_errors = apply_candidate_to_mods(
                    final_candidate, loc_text, mods_path, mods_loc_path, args.backup_dir
                )
                if ok:
                    print("Auto-applied candidate to Mods and localization (backups created).")
                else:
                    print("Auto-apply failed:", apply_errors)
        return {"candidate_path": candidate_path, "valid": True, "errors": []}
    return {"candidate_path": candidate_path if not final_candidate else None, "valid": False, "errors": last_errors}


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
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.staging_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.backup_dir), exist_ok=True)
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
