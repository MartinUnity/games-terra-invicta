#!/usr/bin/env python3
"""Swarm AI worker that orchestrates multiple Ollama models for Terra Invicta project generation.

Usage:
    python3 scripts/ai_swarm.py --brain-model qwen2.5-coder:14b --worker-model qwen2.5-coder:1.5b
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

import requests
import hashlib
import re
from math import inf
import concurrent.futures

# Configuration
OLLAMA_API = "http://localhost:11434/api/generate"

BRAIN_MODEL = "qwen2.5-coder:14b"
WORKER_MODEL = "qwen2.5-coder:1.5b"


def parse_args():
    p = argparse.ArgumentParser(description="Swarm AI worker that uses Ollama HTTP API")
    p.add_argument(
        "--ollama-url",
        default=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        help="Base URL for Ollama (e.g. http://host:11434 or http://host:11434/api/generate)",
    )
    p.add_argument(
        "--brain-ollama-url",
        default=None,
        help="Optional separate Ollama base URL (or full /api/generate) for the brain model",
    )
    p.add_argument(
        "--worker-ollama-url",
        default=None,
        help="Optional separate Ollama base URL (or full /api/generate) for the worker model",
    )
    p.add_argument("--brain-model", default=BRAIN_MODEL, help="Model to use for the brain/generation step")
    p.add_argument("--worker-model", default=WORKER_MODEL, help="Model to use for the worker/extraction step")
    p.add_argument("--timeout", type=int, default=300, help="HTTP timeout seconds for Ollama requests")
    p.add_argument("--brain-timeout", type=int, default=900, help="HTTP timeout seconds for Brain Ollama requests (default 900s)")
    # Probing removed (was opt-in). If you need health checks, use --probe in earlier versions.
    p.add_argument(
        "--persistent",
        action="store_true",
        help="Persist Brain output to scripts/tmp/brain_lore.txt and reuse if present",
    )
    p.add_argument(
        "--invalidate-persistent",
        action="store_true",
        help="Remove persisted Brain cache files from scripts/tmp before running",
    )
    p.add_argument("--sim-threshold", type=float, default=0.8, help="Similarity threshold (0-1) to report near-matching short_summary values")
    p.add_argument("--workers", type=int, default=1, help="Number of worker instances to spawn concurrently to simulate distribution")
    p.add_argument("--worker-temp", type=float, default=0.1, help="Temperature to use for worker models")
    return p.parse_args()


def ask_agent(
    model_name: str,
    prompt: str,
    temperature: float = 0.5,
    timeout: int = 300,
    ollama_api: Optional[str] = None,
) -> Tuple[str, float]:
    """Sends a task to a specific Ollama model and returns response + elapsed time.

    If `ollama_api` is provided it overrides the module-level `OLLAMA_API`.
    """
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": 8192,
        },
    }

    api = ollama_api or OLLAMA_API

    start_time = time.time()
    try:
        response = requests.post(api, json=payload, timeout=timeout)
        response.raise_for_status()
        elapsed = time.time() - start_time
        return response.json().get("response", "").strip(), elapsed
    except requests.exceptions.RequestException as e:
        print(f"❌ Ollama API error: {e}")
        return "", time.time() - start_time


def ask_agent_with_retry(
    model_name: str,
    prompt: str,
    temperature: float = 0.5,
    max_attempts: int = 3,
    timeout: int = 300,
    ollama_api: Optional[str] = None,
) -> Tuple[str, float]:
    """Retry ask_agent with exponential backoff. Pass `ollama_api` to target a specific server."""
    elapsed_total = 0.0
    response_text = ""
    for attempt in range(1, max_attempts + 1):
        print(f"🔄 Attempt {attempt}/{max_attempts}")
        response_text, elapsed = ask_agent(model_name, prompt, temperature, timeout=timeout, ollama_api=ollama_api)
        elapsed_total += elapsed
        if response_text:
            return response_text, elapsed_total
        time.sleep(2 ** (attempt - 1))
    return response_text, elapsed_total


def extract_json_text(text: str) -> str:
    """Clean common wrappers and extract a JSON object from model output.

    Handles fenced code blocks (``` or ~~~), BOM and smart quotes, and falls back to
    extracting from the first '{' to the last '}' if necessary.
    """
    if not text:
        return text
    t = text.strip()
    # normalize some unicode characters
    t = t.replace("\ufeff", "")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2018", "'").replace("\u2019", "'")

    # Prefer extracting content inside fenced code blocks if present
    m = re.search(r"```(?:\w+)?\s*([\s\S]*?)\s*```", t)
    if m:
        t = m.group(1).strip()
    else:
        m2 = re.search(r"~~~(?:\w+)?\s*([\s\S]*?)\s*~~~", t)
        if m2:
            t = m2.group(1).strip()

    # Fallback: extract from first '{' to last '}' if possible
    if not t.startswith("{"):
        first = t.find("{")
        last = t.rfind("}")
        if first != -1 and last != -1 and last > first:
            t = t[first : last + 1]

    return t.strip()


def print_header(text: str):
    """Print formatted header."""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def main():
    # parse CLI args and configure endpoint/models
    args = parse_args()

    # normalize provided ollama URLs to the API endpoint if necessary
    def normalize(base: str) -> str:
        if not base:
            return OLLAMA_API
        if base.endswith("/api/generate"):
            return base
        return base.rstrip("/") + "/api/generate"

    brain_api = normalize(args.brain_ollama_url or args.ollama_url)
    worker_api = normalize(args.worker_ollama_url or args.ollama_url)

    # update module-level defaults for models
    global BRAIN_MODEL, WORKER_MODEL
    BRAIN_MODEL = args.brain_model
    WORKER_MODEL = args.worker_model

    timeout = args.timeout
    brain_timeout = args.brain_timeout
    # probing disabled
    persistent = args.persistent

    # probing removed - skip health checks and proceed directly

    # ============ STEP 1: The Brain (Creative Generation) ========== #
    print_header("STEP 1: The Brain is generating new tech lore...")

    brain_prompt = """
You are a hard sci-fi writer specializing in late-game Terra Invicta technologies.
Invent a cutting-edge research project involving advanced physics or space engineering.
Write exactly two paragraphs of deep, plausible techno-babble lore that describes:
- The core scientific principle
- Its revolutionary applications
- Why this technology is game-changing for humanity's expansion

Be creative and specific. Use technical terms naturally.
"""

    tmp_dir = os.path.join(os.path.dirname(__file__), "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    # build a cache key based on the model and prompt to avoid collisions
    prompt_hash = hashlib.sha256((BRAIN_MODEL + "::" + brain_prompt).encode("utf-8")).hexdigest()[:16]
    brain_file = os.path.join(tmp_dir, f"brain_lore_{prompt_hash}.txt")

    # allow explicit invalidation
    if args.invalidate_persistent:
        try:
            for fn in os.listdir(tmp_dir):
                if fn.startswith("brain_lore_"):
                    os.remove(os.path.join(tmp_dir, fn))
            print("Cleared persisted brain cache files")
        except Exception as e:
            print(f"Failed to clear cache: {e}")

    lore = None
    brain_time = 0.0
    if persistent and os.path.exists(brain_file):
        try:
            with open(brain_file, "r", encoding="utf-8") as f:
                lore = f.read()
            print(f"🧠 Loaded cached Brain output from {brain_file}")
        except Exception:
            lore = None

    if not lore:
        print(f"🧠 Using model: {BRAIN_MODEL} @ {brain_api}")
        lore, brain_time = ask_agent_with_retry(BRAIN_MODEL, brain_prompt, temperature=0.8, timeout=brain_timeout, ollama_api=brain_api)
        print(f"\n✅ Brain finished in {brain_time:.1f}s")
        print(f"\n{lore}\n")
        if persistent:
            try:
                with open(brain_file, "w", encoding="utf-8") as f:
                    f.write(lore)
                print(f"Saved Brain output to {brain_file}")
            except Exception as e:
                print(f"Failed to save Brain output: {e}")


    # ============ STEP 2: The Worker (JSON Extraction) ========== #
    print_header("STEP 2: The Worker is formatting into JSON...")

    worker_prompt = f"""
Read the following sci-fi technology description:

{lore}

Extract exactly three pieces of information and format them as strict JSON.
Output ONLY the raw JSON object - no markdown, no thoughts, no conversational text.
Do NOT include code fences (```), tildes, or any surrounding markdown — output the JSON object only.

Required keys:
1. "project_name" (2-4 word title, capitalize like a proper noun)
2. "category" (one of: "Energy", "Materials", "Spacecraft", "Computing", "Biotechnology", "Weaponry")
3. "short_summary" (single 10-15 word sentence describing the tech)

Example format:
{{
    "project_name": "Magnetically Constrained Fusion Reactor",
    "category": "Energy",
    "short_summary": "Uses magnetic fields to confine plasma for infinite clean energy generation."
}}
"""

    # Support spawning multiple worker instances concurrently to simulate a distributed swarm
    worker_count = max(1, args.workers)
    worker_temp = args.worker_temp

    print(f"🤖 Spawning {worker_count} worker(s) using model: {WORKER_MODEL} @ {worker_api}")

    def run_worker_instance(i: int) -> Tuple[int, str, float]:
        # each worker gets the same prompt + lore for this simulation
        out, wt = ask_agent_with_retry(WORKER_MODEL, worker_prompt, temperature=worker_temp, timeout=timeout, ollama_api=worker_api)
        return i, out, wt

    json_output = None
    worker_time = 0.0
    if worker_count == 1:
        _, json_output, worker_time = run_worker_instance(1)
        print(f"\n✅ Worker finished in {worker_time:.1f}s")
        print(f"\n{json_output}\n")
    else:
        results: List[Tuple[int, str, float]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as ex:
            futures = [ex.submit(run_worker_instance, i + 1) for i in range(worker_count)]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    i, out, wt = fut.result()
                    results.append((i, out, wt))
                    print(f"\n✅ Worker #{i} finished in {wt:.1f}s")
                    print(out)
                except Exception as e:
                    print(f"Worker task failed: {e}")
        # parse each worker's output and collect successes/failures
        parsed_results: List[dict] = []
        for (i, out, wt) in results:
            entry = {"worker": i, "raw": out, "time": wt, "parsed": None, "error": None}
            try:
                cleaned = extract_json_text(out or "")
                parsed = json.loads(cleaned)
                entry["parsed"] = parsed
            except Exception as e:
                entry["error"] = str(e)
            parsed_results.append(entry)

        # print brief summary per worker and detect identical short_summary matches
        success_count = sum(1 for e in parsed_results if e["parsed"])
        fail_count = len(parsed_results) - success_count
        print(f"\nWorker summary: {success_count} successful, {fail_count} failed (of {len(parsed_results)})")
        name_map: dict = {}
        summary_map: dict = {}
        # first pass: build maps
        for e in parsed_results:
            if e["parsed"]:
                name = e["parsed"].get("project_name")
                short = e["parsed"].get("short_summary")
                name_map.setdefault(name, []).append(e["worker"])
                summary_map.setdefault(short, []).append(e["worker"])

        # second pass: print with match notes if short_summary is shared
        for e in parsed_results:
            if e["parsed"]:
                name = e["parsed"].get("project_name")
                short = e["parsed"].get("short_summary")
                cat = e["parsed"].get("category")
                match_note = ""
                if short and len(summary_map.get(short, [])) > 1:
                    match_note = f" (short_summary matches workers: {', '.join(str(w) for w in summary_map[short] if w != e['worker'])})"
                print(f"Worker #{e['worker']}: OK ({e['time']:.1f}s) -> {name} / {cat}{match_note}")
            else:
                print(f"Worker #{e['worker']}: FAIL ({e['time']:.1f}s) -> {e['error']}")

        # decide which worker output to use: prefer the most common project_name, else first successful
        chosen = None
        if name_map:
            # pick project_name with most occurrences
            chosen_name = max(name_map.items(), key=lambda kv: len(kv[1]))[0]
            # pick the first worker that produced this name
            chosen_worker = name_map[chosen_name][0]
            for e in parsed_results:
                if e["worker"] == chosen_worker:
                    chosen = e
                    break
        else:
            for e in parsed_results:
                if e["parsed"]:
                    chosen = e
                    break

        if chosen:
            json_output = chosen["raw"]
            worker_time = chosen["time"]
            print(f"\nSelected Worker #{chosen['worker']} output for validation (project_name={chosen['parsed'].get('project_name')})")
        else:
            # fallback to last raw output if nothing parsed
            if results:
                json_output = results[-1][1]
                worker_time = results[-1][2]
            else:
                json_output = ""
                worker_time = 0.0

        # --- result table: unique parsed outputs and metadata placeholders ---
        print_header("RESULT SUMMARY")
        unique_map = {}
        for e in parsed_results:
            if not e["parsed"]:
                continue
            key = (e["parsed"].get("project_name"), e["parsed"].get("category"), e["parsed"].get("short_summary"))
            if key not in unique_map:
                unique_map[key] = {"workers": [], "raw": e["raw"]}
            unique_map[key]["workers"].append(e["worker"])

        idx = 1
        # compute pairwise similarity between short_summaries to detect near-matches
        def jaccard(a: str, b: str) -> float:
            sa = set(a.lower().split())
            sb = set(b.lower().split())
            if not sa and not sb:
                return 1.0
            inter = sa & sb
            uni = sa | sb
            return len(inter) / len(uni) if uni else 0.0

        shorts = [k[2] for k in unique_map.keys()]
        sim_threshold = args.sim_threshold
        # map index to group id for near matches
        groups: List[List[int]] = []
        for i, s in enumerate(shorts):
            placed = False
            for g in groups:
                # compare to first element in group
                if jaccard(s or "", shorts[g[0]] or "") >= sim_threshold:
                    g.append(i)
                    placed = True
                    break
            if not placed:
                groups.append([i])

        for (proj, cat, short), info in unique_map.items():
            print(f"{idx}. Project: {proj}")
            print(f"   Category: {cat}")
            print(f"   Short: {short}")
            print(f"   Workers: {', '.join(str(w) for w in info['workers'])}")
            print(f"   Metadata: {{owner: , notes: , confidence: }}")
            idx += 1

        # report near-matching short_summaries groups
        if len(groups) > 1:
            print_header("NEAR-MATCH GROUPS (short_summary similarity)")
            keys = list(unique_map.keys())
            for gi, g in enumerate(groups, start=1):
                print(f"Group {gi}:")
                for idx_in_group in g:
                    k = keys[idx_in_group]
                    print(f" - {k[0]} (workers: {', '.join(str(w) for w in unique_map[k]['workers'])})")

        # list failed worker raw outputs for inspection
        failed = [e for e in parsed_results if not e["parsed"]]
        if failed:
            print_header("FAILED WORKER OUTPUTS")
            for e in failed:
                print(f"Worker #{e['worker']} raw output (error={e['error']}):")
                print(e["raw"])


    # ============ STEP 3: Validation & Analysis ========== #
    print_header("STEP 3: Validating output...")

    try:
        # Clean and parse JSON from worker output
        cleaned = extract_json_text(json_output or "")
        parsed_data = json.loads(cleaned)
        print("✅ SUCCESS! The Worker generated valid JSON.")
        print(f"📋 Project Title: {parsed_data.get('project_name', 'N/A')}")
        print(f"📋 Category: {parsed_data.get('category', 'N/A')}")
        print(f"📋 Summary: {parsed_data.get('short_summary', 'N/A')}")

        # Calculate total time
        total_time = brain_time + worker_time
        print_header("TIMING SUMMARY")
        print(f"🧠 Brain latency: {brain_time:.1f}s (@0.8 temp)")
        print(f"🤖 Worker latency: {worker_time:.1f}s (@0.1 temp)")
        print(f"⏱️ Total swarm time: {total_time:.1f}s")

    except json.JSONDecodeError as e:
        print(f"❌ FAILED! The Worker generated invalid JSON.")
        print(f"🔍 Error details: {e}")
        print(f"\nRaw output received:")
        print(json_output)
        print("\nAttempting to show cleaned attempt:")
        try:
            cleaned = extract_json_text(json_output or "")
            print(cleaned)
        except Exception:
            pass


if __name__ == "__main__":
    main()
