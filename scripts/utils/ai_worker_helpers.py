"""Small helper functions extracted from ai_worker.py.

Keep these utilities lightweight so the main script can remain focused.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
import random

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
    if proc.returncode != 0:
        raise RuntimeError(f"ollama run failed: {proc.stderr.strip()}")
    return proc.stdout


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


def call_model(model: str, prompt: str, temperature: float = 0.5, timeout: int = 300, ollama_url: Optional[str] = None) -> str:
    ollama_url = ollama_url or os.environ.get("OLLAMA_URL")
    if not ollama_url:
        ollama_url = "http://localhost:11434"
    try:
        return call_model_via_http(ollama_url, model, prompt, temperature, timeout)
    except Exception:
        try:
            return call_model_via_cli(model, prompt, temperature, timeout)
        except Exception as e:
            raise RuntimeError(f"Model call failed (HTTP and CLI attempts): {e}")


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
) -> tuple[str, Any]:
    """Call the model up to `attempts` times, trying the provided prompt first and
    then a simplified prompt if provided. Returns (raw_output, parsed_json) or
    raises ValueError on failure.
    """
    last_err: Optional[Exception] = None
    used_prompt = prompt
    for attempt in range(attempts):
        try:
            raw = call_model(model, used_prompt, temperature=temperature, timeout=timeout, ollama_url=ollama_url)
        except Exception as e:
            last_err = e
            raw = str(e)
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
                continue
            # otherwise loop to retry with same prompt
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
    return "penalty" in name.lower()


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
    try:
        base = float(base_cost)
    except Exception:
        base = 1000.0
    mult = 1.0 + random.uniform(0.05, 0.5)
    return int(max(1, round(base * mult)))


def write_staged(candidate: Dict[str, Any], staging_root: str, raw_output: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> str:
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
