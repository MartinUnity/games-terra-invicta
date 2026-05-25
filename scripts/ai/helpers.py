"""Small helper functions extracted from ai_worker.py.

Keep these utilities lightweight so the main script can remain focused.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
import random
import time
import re

from typing import Any, Dict, List, Tuple, Optional
import shutil
import subprocess
import requests
import sys

from jsonschema import Draft7Validator


def load_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def extract_json(text: str) -> Any:
    """Try to parse JSON from model output.

    If the model emits extra text, attempt a few heuristics to recover the first JSON
    object or array. Raise the original json error if parsing ultimately fails.
    """
    text = (text or "").strip()
    # direct parse first
    try:
        return json.loads(text)
    except Exception:
        pass

    # crude extraction: find first { ... } or [ ... ] and try progressive slices
    start = text.find("{")
    if start == -1:
        start = text.find("[")
    if start != -1:
        for end in range(len(text), start, -1):
            try:
                return json.loads(text[start:end])
            except Exception:
                continue

    # fallback: try last N characters (helps when model prepends commentary)
    for i in range(min(500, len(text)), 0, -1):
        try:
            return json.loads(text[-i:])
        except Exception:
            continue

    # nothing worked
    raise ValueError("unable to extract JSON from text")


def call_model_via_cli(model: str, prompt: str, temperature: float = 0.5, timeout: int = 300) -> str:
    cmd = ["ollama", "run", model]
    try:
        proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError("ollama CLI not found in PATH")
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    if proc.returncode != 0:
        # include stdout for debugging convenience
        raise RuntimeError(f"ollama run failed: {stderr.strip()}\nSTDOUT:\n{stdout.strip()}")
    # return stdout and any stderr appended for additional diagnostic info
    if stderr.strip():
        return stdout + "\n\n[stderr]\n" + stderr
    return stdout


def call_model_via_http(url: Optional[str], model: str, prompt: str, temperature: float = 0.5, timeout: int = 300) -> str:
    if not url:
        raise RuntimeError("No Ollama URL provided")
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


def call_model(
    model: str,
    prompt: str,
    temperature: float = 0.5,
    timeout: int = 300,
    ollama_url: Optional[str] = None,
    probe_wait: float = 6.0,
) -> str:
    """Call model using HTTP then CLI fallback.

    probe_wait controls how long we probe the Ollama service for model
    readiness before attempting an HTTP call. Increasing this can reduce
    transient "pull model manifest" failures when models are being pulled.
    """
    ollama_url = ollama_url or os.environ.get("OLLAMA_URL")
    if not ollama_url:
        ollama_url = "http://localhost:11434"
    # best-effort probe to reduce transient errors when models are being pulled
    try:
        try:
            if not probe_ollama_model(model, ollama_url, total_wait=probe_wait):
                # model not present (or service unreachable) — continue and let
                # the underlying call produce an error which will be recorded.
                pass
        except Exception:
            pass
        return call_model_via_http(ollama_url, model, prompt, temperature, timeout)
    except Exception:
        try:
            return call_model_via_cli(model, prompt, temperature, timeout)
        except Exception as e:
            raise RuntimeError(f"Model call failed (HTTP and CLI attempts): {e}")


def probe_ollama_model(model: str, ollama_url: Optional[str], total_wait: float = 6.0) -> bool:
    """Probe Ollama for model availability using HTTP `/api/models` or
    the `ollama list` CLI. Returns True if the model is present; False if the
    probe completes without finding the model. This is best-effort.
    """
    start = time.time()
    ollama_url = ollama_url or os.environ.get("OLLAMA_URL") or "http://localhost:11434"
    while time.time() - start < total_wait:
        # Try HTTP endpoint first
        try:
            endpoint = ollama_url.rstrip("/")
            url = endpoint + "/api/models"
            resp = requests.get(url, timeout=2)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if isinstance(data, list):
                        names = [m.get("name") if isinstance(m, dict) else str(m) for m in data]
                        if model in names:
                            return True
                        return False
                    if isinstance(data, dict):
                        models = data.get("models") or data.get("models_list") or []
                        if isinstance(models, list):
                            names = [m.get("name") if isinstance(m, dict) else str(m) for m in models]
                            if model in names:
                                return True
                        return True
                except Exception:
                    return True
        except Exception:
            pass

        # Try CLI list as a fallback
        try:
            proc = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=4)
            out = (proc.stdout or "") + "\n" + (proc.stderr or "")
            if model in out:
                return True
            if proc.returncode == 0 and out.strip():
                return False
        except Exception:
            pass

        time.sleep(0.5)
    return False


def generate_and_extract(
    model: str,
    prompt: str,
    temperature: float = 0.5,
    timeout: int = 300,
    ollama_url: Optional[str] = None,
    attempts: int = 2,
    simplified_prompt: Optional[str] = None,
    ai_dir: Optional[str] = None,
    debug: bool = False,
    probe_wait: float = 6.0,
    retry_sleep_base: float = 0.25,
) -> tuple[str, Any]:
    """Call the model up to `attempts` times, trying the provided prompt first and
    then a simplified prompt if provided. Returns (raw_output, parsed_json) or
    raises ValueError on failure.
    """
    last_err: Optional[Exception] = None
    used_prompt = prompt
    last_raw: str = ""
    for attempt in range(attempts):
        try:
            raw = call_model(
                model,
                used_prompt,
                temperature=temperature,
                timeout=timeout,
                ollama_url=ollama_url,
                probe_wait=probe_wait,
            )
            last_raw = raw
        except Exception as e:
            last_err = e
            raw = str(e)
            last_raw = raw
        try:
            parsed = extract_json(raw)
            return (raw, parsed)
        except Exception as e:
            last_err = e
            # log debugging output if requested and ai_dir is a valid path
            if debug and ai_dir:
                try:
                    # ensure ai_dir exists
                    if not os.path.isdir(ai_dir):
                        os.makedirs(ai_dir, exist_ok=True)
                    dbg = os.path.join(ai_dir, "debug_logs.txt")
                    with open(dbg, "a", encoding="utf-8") as lf:
                        lf.write(f"{datetime.now(timezone.utc).isoformat()} - generate_and_extract: attempt={attempt+1} failed to extract JSON: {e}\nRAW OUTPUT:\n{raw}\n---\n")
                except Exception:
                    pass
            # if we have a simplified prompt and haven't used it yet, switch to it next
            if simplified_prompt and used_prompt != simplified_prompt:
                used_prompt = simplified_prompt
                # small pause before retrying with the simplified prompt to
                # allow transient model readiness issues to clear up
                try:
                    sleep_for = min(5.0, retry_sleep_base * (2 ** attempt))
                    time.sleep(sleep_for)
                except Exception:
                    pass
                continue
            # otherwise loop to retry with same prompt; add a small backoff to
            # reduce immediate retries while the model/service stabilizes.
            try:
                sleep_for = min(5.0, retry_sleep_base * (2 ** attempt))
                time.sleep(sleep_for)
            except Exception:
                pass
            continue
    raise ValueError(f"generate_and_extract failed after {attempts} attempts: {last_err}")
    


def minimal_validate(candidate: Dict[str, Any], schema_path: Optional[str] = None) -> Tuple[bool, List[str]]:
    """Validate candidate against provided JSON schema if available, otherwise perform minimal checks.

    Returns (ok, errors).
    """
    errors: List[str] = []
    if schema_path and os.path.exists(schema_path):
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            validator = Draft7Validator(schema)
            errs = list(validator.iter_errors(candidate))
            for e in errs:
                errors.append(f"{'/'.join([str(p) for p in e.path])}: {e.message}")
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


def load_effect_whitelist(path: str) -> List[str]:
    """Load a simple whitelist file (one token per line).
    Accepts lines with or without a leading '-' and ignores blank lines and comments ('#').
    Returns a list of tokens (strings).
    """
    out: List[str] = []
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


def effect_matches_whitelist(contexts: List[str] | None, whitelist: List[str] | None) -> bool:
    if not contexts or not whitelist:
        return False
    for ctx in contexts:
        for item in whitelist:
            if isinstance(ctx, str) and ctx.startswith(item):
                return True
    return False


def is_penalty_effect(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    s = name.lower()
    # treat obvious negative-effect tokens as penalties so they are not selected
    negative_tokens = (
        "penalty",
        "loss",
        "losses",
        "decrease",
        "decreased",
        "decreases",
        "reduce",
        "reduces",
        "reduction",
        "damage",
        "negative",
        "lose",
        "lost",
    )
    for t in negative_tokens:
        if t in s:
            return True
    return False


def collect_tieffects(path: str) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    if not os.path.exists(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            te = json.load(f)

        def collect(obj: Any):
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


def load_project_templates(path: str) -> List[Any]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        lists: List[Any] = []

        def collect(obj: Any):
            if isinstance(obj, list):
                lists.append(obj)
            elif isinstance(obj, dict):
                for v in obj.values():
                    collect(v)

        collect(data)
        return lists[0] if lists else []
    except Exception:
        return []


def roll_research_cost(base_cost: Any) -> int:
    """Roll a research cost around a base value.

    The multiplier adds some randomness so generated projects do not all have
    identical costs. The variance range can be tuned by passing a different
    `variance` (0.05..0.5 by default).
    """
    try:
        base = float(base_cost)
    except Exception:
        base = 1000.0
    # Use a small upward variance so generated costs generally match or exceed
    # comparable projects. This prevents accidentally producing values that are
    # significantly lower than existing similar projects while still allowing
    # modest randomness.
    mult = random.uniform(1.0, 1.25)
    return int(max(1, round(base * mult)))


def estimate_base_cost(template: Any, chosen_effect: Optional[str], projects: List[Any]) -> float:
    """Estimate a sensible base research cost for a template + effect.

    Strategy:
    - If there are existing projects that reference the chosen_effect, use the
      median of their researchCost values.
    - Otherwise, prefer projects in the same techCategory and use the median
      of those researchCost values.
    - Fallback to the template's researchCost or a default (1000).
    """
    costs: List[float] = []
    try:
        if chosen_effect:
            for p in projects:
                if not isinstance(p, dict):
                    continue
                # effects might be under several keys; prefer 'effects'
                effs = p.get("effects") if isinstance(p.get("effects"), list) else []
                # also scan other fields for effect IDs
                if isinstance(effs, list) and chosen_effect in effs:
                    rc = p.get("researchCost")
                    try:
                        if rc is not None:
                            costs.append(float(rc))
                    except Exception:
                        continue
        # if no costs found for the effect, try same techCategory
        if not costs and isinstance(template, dict):
            cat = template.get("techCategory")
            if cat:
                for p in projects:
                    if not isinstance(p, dict):
                        continue
                    if p.get("techCategory") == cat:
                        rc = p.get("researchCost")
                        try:
                            if rc is not None:
                                costs.append(float(rc))
                        except Exception:
                            continue
    except Exception:
        costs = []

    if costs:
        costs.sort()
        n = len(costs)
        # median
        if n % 2 == 1:
            return costs[n // 2]
        else:
            return (costs[n // 2 - 1] + costs[n // 2]) / 2.0

    # fallback to template values
    try:
        if isinstance(template, dict):
            return float(template.get("researchCost", template.get("cost", 1000)))
    except Exception:
        pass
    return 1000.0


# expose mining level helper for other scripts
try:
    from .mining_leveler import apply_mining_level_suffix, level_for_cost  # type: ignore
except Exception:
    # fallback when imported as module from different working dir
    try:
        from .mining_leveler import apply_mining_level_suffix, level_for_cost  # type: ignore
    except Exception:
        apply_mining_level_suffix = None  # type: ignore
        level_for_cost = None  # type: ignore


def write_staged(candidate: Dict[str, Any], staging_root: str, raw_output: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(staging_root, ts)
    os.makedirs(dest, exist_ok=True)
    candidate_path = os.path.join(dest, "candidate.json")
    with open(candidate_path, "w", encoding="utf-8") as f:
        json.dump(candidate, f, indent=2, ensure_ascii=False)
    # Always write a raw output file to help debugging. If no raw output was
    # provided, write a placeholder so consumers know there was no model text.
    raw_text = raw_output if raw_output is not None else ""
    try:
        with open(candidate_path + ".raw.txt", "w", encoding="utf-8") as f:
            f.write(raw_text)
    except Exception:
        # best-effort: don't fail staging because raw couldn't be written
        pass
    if meta is not None:
        with open(candidate_path + ".meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    return candidate_path


def backup_staged(staging_root: str, backup_root: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(backup_root, ts)
    parent = os.path.dirname(dest) or "."
    os.makedirs(parent, exist_ok=True)
    # copytree requires the destination not to exist
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(staging_root, dest)
    return dest


def prune_dir(root: str, keep: int = 200) -> None:
    """Remove older entries (files or directories) in `root`, keeping only the
    newest `keep` items (sorted by name). This is a simple rotation helper to
    avoid unbounded disk growth from staging/backups.
    """
    try:
        if not os.path.isdir(root):
            return
        entries = [os.path.join(root, e) for e in os.listdir(root)]
        entries = [e for e in entries if os.path.isdir(e) or os.path.isfile(e)]
        if len(entries) <= keep:
            return
        entries.sort()
        to_remove = entries[0 : max(0, len(entries) - keep)]
        for p in to_remove:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
            except Exception:
                continue
    except Exception:
        return


def prune_debug_log(file_path: str, keep_blocks: int = 200) -> None:
    """Trim the debug log file by keeping only the last `keep_blocks` log
    blocks. Blocks are separated by the marker '\n---\n' which is used when
    generate_and_extract appends entries.
    """
    try:
        if not os.path.exists(file_path):
            return
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        blocks = content.split("\n---\n")
        if len(blocks) <= keep_blocks:
            return
        kept = blocks[-keep_blocks:]
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n---\n".join(kept))
            f.write("\n---\n")
    except Exception:
        return


def _normalize_token(s: Optional[str]) -> str:
    if not s or not isinstance(s, str):
        return ""
    return "".join([c.lower() for c in s if c.isalnum()])


def find_project_by_friendlyname(projects: List[Any], friendly_name: str) -> Optional[Dict[str, Any]]:
    """Find a project dict by friendlyName (case-insensitive) or by
    normalized name. Returns the project dict or None.
    """
    if not friendly_name:
        return None
    norm = _normalize_token(friendly_name)
    for p in projects:
        if not isinstance(p, dict):
            continue
        fn = p.get("friendlyName")
        dn = p.get("dataName")
        if isinstance(fn, str) and fn.strip().lower() == friendly_name.strip().lower():
            return p
        if isinstance(dn, str) and _normalize_token(dn).endswith(_normalize_token(friendly_name)):
            return p
        if isinstance(fn, str) and _normalize_token(fn) == norm:
            return p
    return None


_ROMAN = {2: "II", 3: "III", 4: "IV", 5: "V"}


def _roman_to_int(s: str) -> Optional[int]:
    s = (s or "").upper()
    for k, v in _ROMAN.items():
        if v == s:
            return k
    return None


def next_level_for_base(base_data_name: str, projects: List[Any], cap: int = 5) -> Optional[int]:
    """Return the next integer level for base_data_name (2..cap) or None if cap reached.
    Scans existing projects for suffixes like '_II', '_III', etc.
    """
    if not base_data_name:
        return None
    found = 1
    for p in projects:
        if not isinstance(p, dict):
            continue
        dn = p.get("dataName")
        if not isinstance(dn, str):
            continue
        if dn.startswith(base_data_name + "_"):
            suffix = dn[len(base_data_name) + 1 :]
            lvl = _roman_to_int(suffix)
            if lvl and lvl > found:
                found = lvl
    next_lvl = found + 1
    if next_lvl > cap:
        return None
    return next_lvl


def build_leveled_candidate(
    base: Dict[str, Any],
    level: int,
    model_rolls: Optional[Dict[str, Any]] = None,
    tieffects_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a derived candidate based on `base` project, increasing level.

    model_rolls: optional dict containing randomly-rolled fields (factionAvailableChance, initialUnlockChance, etc.)
    tieffects_map: optional map of available effects to help pick upgraded effect variants.
    """
    out = dict(base)  # shallow copy
    roman = _ROMAN.get(level, str(level))
    base_dn = base.get("dataName")
    base_fn = base.get("friendlyName")
    if isinstance(base_dn, str):
        out["dataName"] = f"{base_dn}_{roman}"
    else:
        out["dataName"] = f"{(base_fn or 'Project')}_{roman}"
    if isinstance(base_fn, str):
        out["friendlyName"] = f"{base_fn} {roman}"
    # researchCost: increase by 20-100% of original
    try:
        base_cost = float(base.get("researchCost", base.get("cost", 1000)))
    except Exception:
        base_cost = 1000.0
    inc = random.uniform(0.2, 1.0)
    out["researchCost"] = int(max(1, round(base_cost * (1.0 + inc))))
    # prereqs becomes the base project
    out["prereqs"] = [base.get("dataName")]
    # effects: attempt to upgrade numeric suffix (05->10 etc.) if variant exists in tieffects_map
    if isinstance(base.get("effects"), list) and tieffects_map:
        new_effects: List[str] = []
        promoted: List[Dict[str, str]] = []
        for eff in base.get("effects", []):
            if not isinstance(eff, str):
                continue
            # try to find a trailing numeric token (with optional underscore)
            m = re.search(r"(?P<prefix>.*?)(?P<sep>_?)(?P<num>\d{1,3})$", eff)
            chosen = eff
            if m:
                prefix = m.group("prefix")
                sep = m.group("sep") or ""
                num_str = m.group("num")
                try:
                    num = int(num_str)
                except Exception:
                    num = None
                width = len(num_str)
                if num is not None:
                    # derive available numeric variants dynamically from tieffects_map
                    found_variants: List[int] = []
                    for candidate_key in tieffects_map.keys():
                        # match keys that share the same prefix and end with a numeric token
                        # allow an optional separator between prefix and number
                        try:
                            km = re.match(rf"^{re.escape(prefix)}{re.escape(sep)}(?P<n>\d{{1,3}})$", candidate_key)
                        except re.error:
                            km = None
                        if km:
                            try:
                                nv = int(km.group("n"))
                                if nv > num:
                                    found_variants.append(nv)
                            except Exception:
                                continue
                    # if we found variants, sort unique
                    if found_variants:
                        found_variants = sorted(list({int(x) for x in found_variants}))
                        # pick the variant corresponding to the requested derived level
                        idx = max(0, level - 2)  # level=2 -> idx=0 (next higher)
                        if idx < len(found_variants):
                            pick = found_variants[idx]
                        else:
                            pick = found_variants[-1]
                        # construct pick string preserving original width where possible
                        pick_str = f"{pick:0{width}d}"
                        candidate_name = f"{prefix}{sep}{pick_str}"
                        # prefer exact match, otherwise try in-place replacement or plain number
                        if candidate_name in tieffects_map:
                            chosen = candidate_name
                        else:
                            start, end = m.span("num")
                            alt = eff[:start] + pick_str + eff[end:]
                            if alt in tieffects_map:
                                chosen = alt
                            else:
                                pick_plain = str(pick)
                                alt2 = f"{prefix}{sep}{pick_plain}"
                                if alt2 in tieffects_map:
                                    chosen = alt2
                                else:
                                    chosen = eff
                        promoted.append({"from": eff, "to": chosen})
            # if not matched or no variant found, keep original
            new_effects.append(chosen)
        out["effects"] = new_effects
        if promoted:
            # remove no-op self-maps (from == to) to avoid noisy entries
            real_promoted = [p for p in promoted if p.get("from") != p.get("to")]
            if real_promoted:
                # annotate candidate with the promoted mapping for review
                out.setdefault("__derived_effect_upgrades", real_promoted)
    else:
        out["effects"] = base.get("effects", [])

    # preserve or set AI fields/defaults
    out.setdefault("AI_techRole", base.get("AI_techRole", "None"))
    out.setdefault("AI_criticalTech", base.get("AI_criticalTech", False))
    out.setdefault("AI_projectRole", base.get("AI_projectRole", "SpaceResources"))
    out.setdefault("oneTimeGlobally", base.get("oneTimeGlobally", False))
    out.setdefault("repeatable", base.get("repeatable", False))
    out.setdefault("resourcesGranted", base.get("resourcesGranted", []))

    # use model_rolls if present for faction/unlock chances, else randomize
    if model_rolls and isinstance(model_rolls, dict):
        out["factionAvailableChance"] = model_rolls.get("factionAvailableChance", random.randint(20, 100))
        out["initialUnlockChance"] = model_rolls.get("initialUnlockChance", random.randint(1, 20))
        out["deltaUnlockChance"] = model_rolls.get("deltaUnlockChance", random.randint(1, 10))
        out["maxUnlockChance"] = model_rolls.get("maxUnlockChance", random.randint(20, 100))
    else:
        out["factionAvailableChance"] = random.randint(20, 100)
        out["initialUnlockChance"] = random.randint(1, 20)
        out["deltaUnlockChance"] = random.randint(1, 10)
        out["maxUnlockChance"] = random.randint(20, 100)

    return out


def apply_candidate_to_mods(candidate: Dict[str, Any], localization_text: str, mods_path: str, loc_path: str, backup_root: str) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        os.makedirs(os.path.dirname(mods_path), exist_ok=True)
        # backup mods file if exists
        if os.path.exists(mods_path):
            bmods = os.path.join(backup_root, f"mods_{ts}.json")
            os.makedirs(os.path.dirname(bmods), exist_ok=True)
            shutil.copy2(mods_path, bmods)
        # load existing mods JSON (expecting list) or create new list
        mods_list: List[Any] = []
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
