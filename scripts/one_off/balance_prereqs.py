#!/usr/bin/env python3
"""
balance_prereqs.py — Redistribute mod project prerequisites for an even game-progression spread.

The script builds a topological depth map of the base-game tech/project tree,
scores each mod-only project's "value" via AI (batched and cached), then reassigns
their external prereqs so that high-value projects appear late and low-value projects
appear early.

Key concepts
------------
- External prereq: points to a base-game tech/project  → can be reassigned
- Internal prereq: points to another mod project       → always preserved
- Depth: longest path from a root in the base-game DAG (0 = earliest, 14 = latest)
- Value score: AI-rated 1–10 (how powerful/impactful the project's effect is)

Usage
-----
    # Show current distribution only (no AI calls)
    python3 scripts/one_off/balance_prereqs.py --analyze

    # Score values via AI and preview proposed changes
    python3 scripts/one_off/balance_prereqs.py --dry-run

    # Apply changes (writes Mods/TIProjectTemplate.json)
    python3 scripts/one_off/balance_prereqs.py --apply

    # Fast preview using researchCost as value proxy (no AI for scoring)
    python3 scripts/one_off/balance_prereqs.py --dry-run --skip-ai-value
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_TECH_FILE = Path("/home/martin/Games/TerraInvicta/templates/TITechTemplate.json")
BASE_PROJECT_FILE = Path("/home/martin/Games/TerraInvicta/templates/TIProjectTemplate.json")
MOD_PROJECT_FILE = REPO_ROOT / "Mods" / "TIProjectTemplate.json"
CACHE_FILE = Path(__file__).resolve().parent / ".balance_cache.json"

# ---------------------------------------------------------------------------
# AI configuration
# ---------------------------------------------------------------------------
DEFAULT_AI_ENDPOINT = "https://ai.skytech.dk/v1"
DEFAULT_MODEL = "Qwen3.6-27B-Q6_K.gguf"
DEFAULT_TIMEOUT = 1800  # seconds — thinking model at 3-5 t/s can take many minutes;
# proxy also handles WoL so first call may include wake delay
AI_VALUE_BATCH_SIZE = 8  # smaller batches → less thinking time per call, safer JSON extraction

# ---------------------------------------------------------------------------
# Category compatibility
# When finding prereq candidates prefer exact match, then compatible categories
# ---------------------------------------------------------------------------
CATEGORY_COMPAT: Dict[str, Set[str]] = {
    "MilitaryScience": {"MilitaryScience"},
    "SocialScience": {"SocialScience", "InformationScience"},
    "SpaceScience": {"SpaceScience", "Materials", "Energy"},
    "Energy": {"Energy", "SpaceScience", "Materials"},
    "Materials": {"Materials", "Energy", "SpaceScience"},
    "InformationScience": {"InformationScience", "SocialScience"},
    "LifeScience": {"LifeScience", "Xenology"},
    "Xenology": {"Xenology", "LifeScience", "SpaceScience"},
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def strip_thinking(text: str) -> str:
    """Remove <think>…</think> blocks emitted by Qwen3 before JSON parsing."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_json(text: str) -> Any:
    """Best-effort JSON extraction from model output that may contain prose."""
    text = strip_thinking(text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # Find first { or [ and walk backwards to find matching close
    for start_char in ("{", "["):
        start = text.find(start_char)
        if start != -1:
            for end in range(len(text), start, -1):
                try:
                    return json.loads(text[start:end])
                except Exception:
                    continue
    raise ValueError(f"Could not extract JSON from response: {text[:300]!r}")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def load_cache(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  Warning: could not load cache ({e}), starting fresh.")
    return {}


def save_cache(path: Path, cache: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# AI client (OpenAI-compatible chat completions)
# ---------------------------------------------------------------------------


def call_ai(
    messages: List[Dict[str, str]],
    endpoint: str,
    model: str,
    timeout: int,
    temperature: float = 0.1,
) -> str:
    """POST to /v1/chat/completions and return the assistant message content."""
    url = endpoint.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Graph building
# ---------------------------------------------------------------------------


def _normalise_prereqs(raw: Any) -> List[str]:
    """Return a plain list of prereq dataNames from whatever format the JSON uses."""
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, dict):
        return list(raw.keys())
    return []


def build_base_graph(techs: List[Dict], projects: List[Dict]) -> Dict[str, Dict]:
    """Build dataName → {prereqs, type, cat, friendlyName, researchCost}."""
    nodes: Dict[str, Dict] = {}
    for t in techs:
        nodes[t["dataName"]] = {
            "prereqs": _normalise_prereqs(t.get("prereqs", [])),
            "type": "tech",
            "cat": t.get("techCategory", ""),
            "friendlyName": t.get("friendlyName", t["dataName"]),
            "researchCost": t.get("researchCost", 0),
        }
    for p in projects:
        nodes[p["dataName"]] = {
            "prereqs": _normalise_prereqs(p.get("prereqs", [])),
            "type": "project",
            "cat": p.get("techCategory", ""),
            "friendlyName": p.get("friendlyName", p["dataName"]),
            "researchCost": p.get("researchCost", 0),
        }
    return nodes


def compute_depths(nodes: Dict[str, Dict]) -> Dict[str, int]:
    """
    Longest-path depth from any root (node with no known prereqs).
    Uses Kahn's topological-sort algorithm.  Nodes in cycles fall back to 0.
    """
    children: Dict[str, List[str]] = defaultdict(list)
    in_degree: Dict[str, int] = {name: 0 for name in nodes}

    for name, node in nodes.items():
        for pr in node["prereqs"]:
            if pr in nodes:
                children[pr].append(name)
                in_degree[name] += 1

    depth: Dict[str, int] = {}
    queue: deque = deque()
    for name in nodes:
        if in_degree[name] == 0:
            depth[name] = 0
            queue.append(name)

    while queue:
        n = queue.popleft()
        for child in children[n]:
            in_degree[child] -= 1
            depth[child] = max(depth.get(child, 0), depth[n] + 1)
            if in_degree[child] == 0:
                queue.append(child)

    # Nodes still in cycles (in_degree > 0) get depth 0
    for name in nodes:
        if name not in depth:
            depth[name] = 0

    return depth


# ---------------------------------------------------------------------------
# AI value scoring
# ---------------------------------------------------------------------------

_VALUE_SYSTEM = """\
You are evaluating Terra Invicta research project power levels on a 1–10 scale.

Scale guide:
  1–2  Minor early-game bonus (e.g. +1% resource gain, tiny army buff)
  3–4  Modest early/mid-game benefit
  5–6  Meaningful mid-game upgrade
  7–8  Significant late-game advancement
  9–10 Powerful end-game / transformative effect (e.g. +50% bonus, life extension, advanced drives)

Consider the researchCost as a rough hint, but judge primarily on effect magnitude and game impact.
Reply ONLY with a valid JSON array — no explanation, no markdown, no <think> tags.
"""

_VALUE_USER = """\
Rate these projects. Required format: [{{"dataName": "...", "value_score": 5}}, ...]

{projects_json}
"""


def score_values_ai(
    projects: List[Dict],
    endpoint: str,
    model: str,
    timeout: int,
    cache: Dict[str, Any],
) -> None:
    """
    Score each project's value in-place into cache["value_scores"].
    Skips projects already in cache.  Saves cache after every batch.
    """
    cache.setdefault("value_scores", {})
    to_score = [p for p in projects if p["dataName"] not in cache["value_scores"]]
    already = len(projects) - len(to_score)
    if already:
        print(f"  {already} value scores loaded from cache.")
    if not to_score:
        return

    total_batches = (len(to_score) + AI_VALUE_BATCH_SIZE - 1) // AI_VALUE_BATCH_SIZE
    print(
        f"  Scoring {len(to_score)} projects via AI in {total_batches} batches "
        f"(timeout={timeout}s per batch — thinking model, expect slow returns)."
        f"\n  Cache saves after every batch so you can safely interrupt and resume."
    )

    for batch_idx in range(0, len(to_score), AI_VALUE_BATCH_SIZE):
        batch = to_score[batch_idx : batch_idx + AI_VALUE_BATCH_SIZE]
        bn = batch_idx // AI_VALUE_BATCH_SIZE + 1
        print(f"    Batch {bn}/{total_batches} ({len(batch)} projects)...", end=" ", flush=True)

        payload = [
            {
                "dataName": p["dataName"],
                "friendlyName": p.get("friendlyName", ""),
                "techCategory": p.get("techCategory", ""),
                "effects": p.get("effects", []),
                "researchCost": p.get("researchCost", 0),
            }
            for p in batch
        ]
        prompt = _VALUE_USER.format(projects_json=json.dumps(payload, ensure_ascii=False))

        try:
            raw = call_ai(
                [
                    {"role": "system", "content": _VALUE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                endpoint=endpoint,
                model=model,
                timeout=timeout,
            )
            results = extract_json(raw)
            if not isinstance(results, list):
                print("WARN: unexpected shape, skipping batch")
                continue
            scored = 0
            for item in results:
                if isinstance(item, dict) and "dataName" in item and "value_score" in item:
                    try:
                        cache["value_scores"][item["dataName"]] = float(item["value_score"])
                        scored += 1
                    except (ValueError, TypeError):
                        pass
            print(f"OK ({scored}/{len(batch)} scored)")
        except Exception as e:
            print(f"ERROR: {e}")

        # Incremental save so progress survives interruptions
        save_cache(CACHE_FILE, cache)


# ---------------------------------------------------------------------------
# Prereq candidate finding
# ---------------------------------------------------------------------------


def find_prereq_candidates(
    project_cat: str,
    target_depth: float,
    base_nodes: Dict[str, Dict],
    base_depths: Dict[str, int],
    tolerance: int = 2,
) -> List[Tuple[int, str]]:
    """
    Return base-game nodes near target_depth with a compatible techCategory,
    sorted by (category_score * 100 + depth_delta) ascending (best first).
    """
    compat = CATEGORY_COMPAT.get(project_cat, {project_cat})
    target_int = round(target_depth)
    candidates: List[Tuple[int, str]] = []

    for name, node in base_nodes.items():
        d = base_depths.get(name, 0)
        depth_delta = abs(d - target_int)
        if depth_delta > tolerance:
            continue
        cat = node.get("cat", "")
        if cat == project_cat:
            cat_score = 0
        elif cat in compat:
            cat_score = 1
        else:
            continue
        candidates.append((cat_score * 100 + depth_delta, name))

    candidates.sort(key=lambda x: x[0])
    return candidates


def pick_prereq_via_ai(
    project: Dict,
    candidates: List[str],
    base_nodes: Dict[str, Dict],
    base_depths: Dict[str, int],
    endpoint: str,
    model: str,
    timeout: int,
    cache: Dict[str, Any],
) -> Optional[str]:
    """
    Ask the AI to choose the best prereq from a list of candidates.
    Results are cached under cache["prereq_choices"][dataName].
    """
    cache.setdefault("prereq_choices", {})
    dn = project["dataName"]
    if dn in cache["prereq_choices"]:
        chosen = cache["prereq_choices"][dn]
        if chosen in base_nodes:
            return chosen

    cands_info = [
        {
            "dataName": n,
            "friendlyName": base_nodes[n].get("friendlyName", n),
            "techCategory": base_nodes[n].get("cat", ""),
            "depth": base_depths.get(n, 0),
        }
        for n in candidates[:30]
    ]
    system_msg = (
        "You are helping balance a Terra Invicta mod by choosing the best research prerequisite "
        "for a newly added project.  Consider thematic fit (matching science / technology domain) "
        'and sensible game progression.  Reply ONLY with a JSON object: {"chosen": "dataName"}'
    )
    user_msg = (
        f"Project to place:\n"
        f"{json.dumps({'dataName': project['dataName'], 'friendlyName': project.get('friendlyName',''), 'techCategory': project.get('techCategory',''), 'effects': project.get('effects', [])}, ensure_ascii=False)}\n\n"
        f"Choose the most thematically appropriate prerequisite from these candidates "
        f"(pick the dataName that best fits):\n"
        f"{json.dumps(cands_info, ensure_ascii=False)}\n\n"
        f'Reply ONLY with JSON: {{"chosen": "dataName"}}'
    )
    try:
        raw = call_ai(
            [{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
            endpoint=endpoint,
            model=model,
            timeout=timeout,
        )
        result = extract_json(raw)
        if isinstance(result, dict) and "chosen" in result:
            chosen = result["chosen"]
            if chosen in base_nodes:
                cache["prereq_choices"][dn] = chosen
                save_cache(CACHE_FILE, cache)
                return chosen
    except Exception as e:
        print(f"      AI prereq selection failed for {dn}: {e}")
    return None


# ---------------------------------------------------------------------------
# Core rebalancing logic
# ---------------------------------------------------------------------------


def value_to_target_depth(value_score: float, max_depth: int) -> float:
    """Map value 1–10 → target prereq depth 0…max_depth (with small jitter)."""
    # Soft clamp
    v = max(1.0, min(10.0, value_score))
    pct = (v - 1.0) / 9.0  # 0..1
    jitter = (random.random() - 0.5) * 0.4  # ±0.2 depth
    return max(0.0, min(float(max_depth), pct * max_depth + jitter))


def rebalance(
    mod_projects: List[Dict],
    base_nodes: Dict[str, Dict],
    base_depths: Dict[str, int],
    value_scores: Dict[str, float],
    endpoint: str,
    model: str,
    timeout: int,
    dry_run: bool,
    cache: Dict[str, Any],
    skip_ai_prereq: bool = False,
) -> List[Dict]:
    """
    For each mod project that has at least one external prereq, assign a new
    external prereq based on value score and thematic compatibility.

    Internal (mod → mod) prereqs are always preserved.
    Returns a list of change-record dicts for reporting.
    """
    mod_names: Set[str] = {p["dataName"] for p in mod_projects}
    max_depth = max(base_depths.values()) if base_depths else 14

    changes: List[Dict] = []
    stats = {"skipped_internal_only": 0, "skipped_no_candidate": 0, "ai_prereq": 0}

    for project in mod_projects:
        prereqs = _normalise_prereqs(project.get("prereqs", []))
        internal = [p for p in prereqs if p in mod_names]
        external = [p for p in prereqs if p not in mod_names]

        if not external:
            # Fully determined by internal chain — skip; it will move with its root
            stats["skipped_internal_only"] += 1
            continue

        # Current entry depth (max depth of external prereqs we know about)
        current_ext_depth = max(
            (base_depths.get(e, 0) for e in external if e in base_depths),
            default=0,
        )

        # Value score (default 5 = mid-game if unknown)
        value = value_scores.get(project["dataName"], 5.0)
        target_depth = value_to_target_depth(value, max_depth)
        project_cat = project.get("techCategory", "")

        # Find candidate base-game prereqs
        candidates = find_prereq_candidates(project_cat, target_depth, base_nodes, base_depths, tolerance=2)
        if not candidates:
            candidates = find_prereq_candidates(project_cat, target_depth, base_nodes, base_depths, tolerance=4)
        if not candidates:
            # Widen to any category within depth tolerance
            target_int = round(target_depth)
            candidates = sorted(
                (abs(base_depths.get(n, 0) - target_int), n)
                for n in base_nodes
                if abs(base_depths.get(n, 0) - target_int) <= 3
            )
        if not candidates:
            stats["skipped_no_candidate"] += 1
            continue

        # Decide which prereq to use
        top_priority = candidates[0][0]
        top_names = [n for pri, n in candidates if pri == top_priority]

        if len(top_names) == 1 or skip_ai_prereq:
            # Deterministic: pick best-scored; break ties by alphabetical order for reproducibility
            best = sorted(top_names)[0]
        else:
            # Multiple equally good candidates → ask AI
            ai_choice = pick_prereq_via_ai(
                project,
                top_names,
                base_nodes,
                base_depths,
                endpoint,
                model,
                timeout,
                cache,
            )
            if ai_choice:
                best = ai_choice
                stats["ai_prereq"] += 1
            else:
                best = sorted(top_names)[0]

        new_prereqs = internal + [best]
        new_ext_depth = base_depths.get(best, 0)

        # Only record as a change if something actually differs
        if sorted(new_prereqs) == sorted(prereqs):
            continue

        changes.append(
            {
                "dataName": project["dataName"],
                "friendlyName": project.get("friendlyName", ""),
                "techCategory": project_cat,
                "value_score": value,
                "target_depth": round(target_depth, 1),
                "old_prereqs": prereqs,
                "new_prereqs": new_prereqs,
                "old_ext_depth": current_ext_depth,
                "new_ext_depth": new_ext_depth,
                "prereq_friendly": base_nodes.get(best, {}).get("friendlyName", best),
            }
        )

        if not dry_run:
            project["prereqs"] = new_prereqs

    print(f"\n  Stats:")
    print(f"    Skipped (only internal prereqs):  {stats['skipped_internal_only']}")
    print(f"    Skipped (no candidates found):    {stats['skipped_no_candidate']}")
    print(f"    AI used for prereq selection:     {stats['ai_prereq']}")
    return changes


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def depth_histogram(depths: List[int], max_depth: int, bar_scale: int = 10) -> str:
    """ASCII histogram of a depth list."""
    buckets: Dict[int, int] = defaultdict(int)
    for d in depths:
        buckets[d] += 1
    lines = []
    for d in range(max_depth + 1):
        count = buckets.get(d, 0)
        bar = "█" * (count // bar_scale)
        lines.append(f"  {d:2d}: {count:4d}  {bar}")
    return "\n".join(lines)


def print_report(changes: List[Dict], max_depth: int) -> None:
    print(f"\n{'='*80}")
    print(f"  {len(changes)} projects will have their prereqs changed")
    print(f"{'='*80}")

    old_d = [c["old_ext_depth"] for c in changes]
    new_d = [c["new_ext_depth"] for c in changes]

    print(f"\nExternal-prereq depth BEFORE changes (bar = {10} projects):")
    print(depth_histogram(old_d, max_depth))
    print(f"\nExternal-prereq depth AFTER changes (bar = {10} projects):")
    print(depth_histogram(new_d, max_depth))

    # Top 25 highest-value changes
    top = sorted(changes, key=lambda x: -x["value_score"])[:25]
    print(f"\nTop 25 highest-value changes:")
    hdr = f"{'Project':<38} {'Val':>4} {'OD':>3} {'ND':>3}  {'Old prereq':<32}  New prereq"
    print(hdr)
    print("-" * len(hdr))
    for c in top:
        old_p = c["old_prereqs"][0] if c["old_prereqs"] else ""
        new_p = c["new_prereqs"][-1] if c["new_prereqs"] else ""  # last = new external
        print(
            f"{c['friendlyName'][:37]:<38} {c['value_score']:>4.0f} "
            f"{c['old_ext_depth']:>3} {c['new_ext_depth']:>3}  "
            f"{old_p[:31]:<32}  {new_p}"
        )

    # Value-score distribution of changed projects
    buckets: Dict[int, int] = defaultdict(int)
    for c in changes:
        buckets[round(c["value_score"])] += 1
    print(f"\nValue-score distribution of changed projects:")
    for v in range(1, 11):
        bar = "█" * (buckets.get(v, 0) // 5)
        print(f"  {v:2d}: {buckets.get(v,0):4d}  {bar}")


def print_analyze(mod_only: List[Dict], mod_names: Set[str], base_depths: Dict[str, int]) -> None:
    """Print current distribution without making any changes."""
    entry_depths: List[int] = []
    for p in mod_only:
        prereqs = _normalise_prereqs(p.get("prereqs", []))
        ext = [pr for pr in prereqs if pr not in mod_names]
        d = max((base_depths.get(pr, 0) for pr in ext if pr in base_depths), default=0)
        entry_depths.append(d)

    max_d = max(entry_depths) if entry_depths else 0
    print(f"\nCurrent external-prereq depth distribution for {len(mod_only)} mod projects:")
    print(f"(bar scale = 20 projects per █)\n")
    buckets: Dict[int, int] = defaultdict(int)
    for d in entry_depths:
        buckets[d] += 1
    for d in range(max_d + 1):
        count = buckets.get(d, 0)
        bar = "█" * (count // 20)
        print(f"  {d:2d}: {count:4d}  {bar}")
    print(f"\nTotal: {len(entry_depths)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebalance mod project prereqs for even game-progression spread.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--analyze", action="store_true", help="Show current depth distribution only")
    mode_group.add_argument("--dry-run", action="store_true", help="Show proposed changes without writing")
    mode_group.add_argument("--apply", action="store_true", help="Write changes to Mods/TIProjectTemplate.json")

    parser.add_argument("--ai-endpoint", default=DEFAULT_AI_ENDPOINT, metavar="URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, metavar="NAME")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        metavar="SECS",
        help=f"AI request timeout in seconds (default {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--skip-ai-value", action="store_true", help="Use researchCost as value proxy instead of querying the AI"
    )
    parser.add_argument(
        "--skip-ai-prereq", action="store_true", help="Pick prereq deterministically (no AI for tied candidates)"
    )
    parser.add_argument(
        "--output",
        default=str(MOD_PROJECT_FILE),
        metavar="PATH",
        help="Output path for --apply (default: Mods/TIProjectTemplate.json)",
    )
    parser.add_argument("--no-cache", action="store_true", help="Ignore cached AI results")
    parser.add_argument("--cache-file", default=str(CACHE_FILE), metavar="PATH")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for depth jitter (default 42)")
    args = parser.parse_args()

    random.seed(args.seed)

    # --- Load data ---
    print("Loading data files...")
    with open(BASE_TECH_FILE, encoding="utf-8") as f:
        base_techs = json.load(f)
    with open(BASE_PROJECT_FILE, encoding="utf-8") as f:
        base_projects = json.load(f)
    with open(MOD_PROJECT_FILE, encoding="utf-8") as f:
        mod_data = json.load(f)

    base_names: Set[str] = {p["dataName"] for p in base_projects}
    mod_only = [p for p in mod_data if p["dataName"] not in base_names]
    mod_names: Set[str] = {p["dataName"] for p in mod_only}

    print(f"  Base techs: {len(base_techs)}, Base projects: {len(base_projects)}, " f"Mod-only: {len(mod_only)}")

    # --- Build base graph and depths ---
    print("Building dependency graph and computing depths...")
    base_nodes = build_base_graph(base_techs, base_projects)
    base_depths = compute_depths(base_nodes)
    max_depth = max(base_depths.values())
    print(f"  Depth range: 0–{max_depth}")

    # --- Analyze only ---
    if args.analyze:
        print_analyze(mod_only, mod_names, base_depths)
        return

    # --- Cache ---
    cache_path = Path(args.cache_file)
    cache: Dict[str, Any] = {} if args.no_cache else load_cache(cache_path)

    # --- Value scoring ---
    if args.skip_ai_value:
        print("Using researchCost as value proxy (--skip-ai-value)...")
        costs = [p.get("researchCost", 1) for p in mod_only]
        min_c = min(costs)
        range_c = max(max(costs) - min_c, 1)
        cache.setdefault("value_scores", {})
        for p in mod_only:
            c = p.get("researchCost", 1)
            cache["value_scores"][p["dataName"]] = 1.0 + 9.0 * (c - min_c) / range_c
    else:
        print("Scoring project values via AI...")
        score_values_ai(mod_only, args.ai_endpoint, args.model, args.timeout, cache)
        save_cache(cache_path, cache)

    value_scores = cache.get("value_scores", {})
    scored = sum(1 for p in mod_only if p["dataName"] in value_scores)
    print(f"  Value scores available: {scored}/{len(mod_only)}")

    # --- Rebalance ---
    print("\nRebalancing prerequisites...")
    changes = rebalance(
        mod_projects=mod_only,
        base_nodes=base_nodes,
        base_depths=base_depths,
        value_scores=value_scores,
        endpoint=args.ai_endpoint,
        model=args.model,
        timeout=args.timeout,
        dry_run=args.dry_run,
        cache=cache,
        skip_ai_prereq=args.skip_ai_prereq,
    )

    # --- Report ---
    print_report(changes, max_depth)

    # --- Write ---
    if args.apply:
        output_path = Path(args.output)
        backup_path = output_path.with_suffix(".json.bak")
        shutil.copy2(output_path, backup_path)
        print(f"\nBacked up original to {backup_path}")
        output_path.write_text(
            json.dumps(mod_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Written to {output_path}")
    else:
        print("\n[DRY RUN] No files written.")


if __name__ == "__main__":
    main()
