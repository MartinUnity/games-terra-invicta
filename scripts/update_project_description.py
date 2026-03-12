#!/usr/bin/env python3
"""Update TIProjectTemplate.en summaries using a local Ollama model.

Reads Mods/Localization/en/TIProjectTemplate.en, iterates entries starting at
the specified dataName (or from the top), calls a local `ollama generate`
model to produce a new summary for each project, and writes updated summary
lines back to the file. Creates a timestamped backup before modifying.

Usage example:
  python3 scripts/update_project_description.py \
    --model llama2 --temperature 0.8 --top_p 0.95 --top_k 20 \
    --presence_penalty 1.5 --start-data Project_Asteroid_Claim --batch 5
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import shlex
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

import requests

DISPLAY_RE = re.compile(r"^TIProjectTemplate\.displayName\.([A-Za-z0-9_]+)=(.*)$")
SUMMARY_RE = re.compile(r"^TIProjectTemplate\.summary\.([A-Za-z0-9_]+)=(.*)$")


def read_en(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def parse_entries(lines: List[str]) -> List[Tuple[str, Optional[str], Optional[str], int, int]]:
    """Return list of tuples: (dataName, display, summary, display_idx, summary_idx)
    summary_idx may be -1 if not present.
    """
    entries: Dict[str, Dict[str, object]] = {}
    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        m = DISPLAY_RE.match(line)
        if m:
            name, val = m.group(1), m.group(2)
            entries.setdefault(name, {})["display"] = val
            entries[name]["display_idx"] = i
            continue
        m2 = SUMMARY_RE.match(line)
        if m2:
            name, val = m2.group(1), m2.group(2)
            entries.setdefault(name, {})["summary"] = val
            entries[name]["summary_idx"] = i

    ordered: List[Tuple[str, Optional[str], Optional[str], int, int]] = []
    # preserve file order by scanning for display lines
    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        m = DISPLAY_RE.match(line)
        if m:
            name = m.group(1)
            info = entries.get(name, {})
            display = info.get("display")
            summary = info.get("summary")
            display_idx = info.get("display_idx", -1)
            summary_idx = info.get("summary_idx", -1)
            ordered.append((name, display, summary, display_idx, summary_idx))

    return ordered


def call_ollama(
    model: str, prompt: str, temperature: float, top_p: float, top_k: int, presence_penalty: float, timeout: int = 60
):
    """Try Ollama HTTP API first (if available) then fall back to CLI.

    Returns the response text from Ollama.
    """
    # prefer explicit OLLAMA_URL env var, otherwise default to localhost:11434
    ollama_url = os.environ.get("OLLAMA_URL") or "http://localhost:11434"

    # attempt HTTP API
    try:
        endpoint = ollama_url.rstrip("/")
        if not endpoint.endswith("/api/generate"):
            endpoint = endpoint + "/api/generate"
        params = {
            "model": model,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        payload = {
            "prompt": prompt,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "presence_penalty": presence_penalty,
        }
        resp = requests.post(endpoint, params=params, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.text.strip()
    except Exception:
        # fallback to CLI
        pass

    cmd = ["ollama", "run", model]
    try:
        proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError("ollama CLI not found in PATH and HTTP attempt failed")
    except subprocess.TimeoutExpired:
        raise RuntimeError("ollama call timed out (CLI)")

    if proc.returncode != 0:
        raise RuntimeError(f"ollama run failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def make_prompt(display: str, current_summary: Optional[str]) -> str:
    s = current_summary or ""
    prompt = (
        "You are an assistant that rewrites short project summaries for a game. "
        "Given the project display name and current summary, return an improved, concise summary (one or two sentences) "
        "that preserves meaning, is in English, and fits a UI tooltip. Return ONLY the new summary text with no headings."
        " Do NOT include any chain-of-thought, step-by-step reasoning, analysis, or internal deliberation. "
        "Output must be a single line containing only the final summary.\n\n"
        f"Project name: {display}\n"
        f"Current summary: {s}\n\n"
        "New summary:"
    )
    return prompt


def extract_final_summary(text: str) -> str:
    """Heuristic to remove chain-of-thought / reasoning and return the final summary line.

    Strategy:
    - Split output into lines and scan from the end for a plausible final sentence.
    - Skip lines that look like analysis (contain 'Thinking', 'Process', numbered steps, or markdown markers).
    - Prefer the last short paragraph/line with length >= 20 characters.
    - Fallback to the first non-empty line.
    """
    if not text:
        return ""
    # normalize
    # remove common artifacts
    cleaned = text.replace("\r\n", "\n")
    lines = [ln.strip() for ln in cleaned.split("\n") if ln.strip()]
    # reverse search for best candidate
    for ln in reversed(lines):
        low = ln.lower()
        # skip obvious reasoning/analysis lines
        if "thinking" in low or "process" in low or low.startswith("step") or low.startswith("1."):
            continue
        if ln.startswith("*") or ln.startswith("-") or ln.startswith("**"):
            continue
        # skip lines that are clearly prompt echoes or constraints
        if ln.lower().startswith("project name:") or ln.lower().startswith("current summary:"):
            continue
        # strip leading labels like 'Final:' or 'Final choice:'
        ln2 = re.sub(r"^(final[:\-\s]+)", "", ln, flags=re.IGNORECASE).strip()
        # remove trailing 'done thinking' artifacts
        ln2 = re.sub(r"done thinking\.?$", "", ln2, flags=re.IGNORECASE).strip()
        # accept reasonably long lines
        if len(ln2) >= 20:
            return ln2
    # fallback: return the first non-empty line
    return lines[0] if lines else ""


def safe_write(path: str, lines: List[str]):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp_ti_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(lines)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def backup_file(path: str) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bpath = f"{path}.bak.{ts}"
    with open(path, "rb") as src, open(bpath, "wb") as dst:
        dst.write(src.read())
    return bpath


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Update project summaries using local Ollama model")
    p.add_argument("--en", default=os.path.join("Mods", "Localization", "en", "TIProjectTemplate.en"))
    p.add_argument("--model", required=True, help="Ollama model name to use")
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--top_p", type=float, default=0.95)
    p.add_argument("--top_k", type=int, default=20)
    p.add_argument("--presence_penalty", type=float, default=1.5)
    p.add_argument("--start-data", help="dataName to start from (e.g. Project_Asteroid_Claim)")
    p.add_argument("--batch", type=int, default=1, help="Number of entries to update in one run")
    p.add_argument("--timeout", type=int, default=60, help="Timeout seconds for each ollama call")
    p.add_argument("--dry-run", action="store_true", help="Do not write file; just print intended updates")
    args = p.parse_args(argv)

    enpath = args.en
    if not os.path.exists(enpath):
        print(f"EN file not found: {enpath}", file=sys.stderr)
        return 2

    lines = read_en(enpath)
    entries = parse_entries(lines)
    if not entries:
        print("No project display entries found.")
        return 0

    start_idx = 0
    if args.start_data:
        for i, (name, *_rest) in enumerate(entries):
            if name == args.start_data:
                start_idx = i
                break
        else:
            print(f"Start dataName not found: {args.start_data}", file=sys.stderr)
            return 2

    end_idx = min(len(entries), start_idx + args.batch)

    # Prepare modifications in-memory
    new_lines = list(lines)
    updated = []

    for i in range(start_idx, end_idx):
        name, display, summary, display_idx, summary_idx = entries[i]
        if display is None:
            print(f"Skipping {name}: no displayName found", file=sys.stderr)
            continue

        prompt = make_prompt(display, summary)
        try:
            out = call_ollama(
                args.model,
                prompt,
                args.temperature,
                args.top_p,
                args.top_k,
                args.presence_penalty,
                timeout=args.timeout,
            )
        except RuntimeError as e:
            print(f"Error generating for {name}: {e}", file=sys.stderr)
            return 3

        # sanitize result: keep single-line, strip surrounding quotes
        # sanitize model output to strip chain-of-thought and reasoning
        out_line = extract_final_summary(out)
        out_line = out_line.strip('"')

        new_summary = out_line
        summary_key = f"TIProjectTemplate.summary.{name}="

        if summary_idx is not None and summary_idx >= 0:
            # replace existing line
            new_lines[summary_idx] = f"{summary_key}{new_summary}\n"
        else:
            # insert after display_idx
            insert_at = display_idx + 1 if display_idx >= 0 else len(new_lines)
            new_lines.insert(insert_at, f"{summary_key}{new_summary}\n")

        updated.append((name, new_summary))
        print(f"Updated: {name}")

    next_idx = end_idx
    next_name = entries[next_idx][0] if next_idx < len(entries) else ""

    if args.dry_run:
        print("Dry-run enabled; no file was changed.")
        for name, s in updated:
            print(f"Would update {name}: {s}")
        if next_name:
            print(f"Next dataName to update: {next_name}")
        return 0

    # backup and write
    bak = backup_file(enpath)
    try:
        safe_write(enpath, new_lines)
    except Exception as e:
        print(f"Failed to write updated file: {e}", file=sys.stderr)
        print(f"Backup saved as: {bak}")
        return 4

    print(f"Backup created: {bak}")
    for name, s in updated:
        print(f"Wrote: {name}")
    if next_name:
        print(next_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
