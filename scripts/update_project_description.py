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
import difflib
import urllib.parse
import json
import shutil
from typing import Any, Dict, List, Optional, Tuple, cast

import requests
import time

# runtime flags (set in main)
DEBUG = False
COMPACT_ONLY = False
OUTPUT_WIDTH: Optional[int] = None

def dbg(*args, **kwargs):
    """Debug print (only when DEBUG True). Defaults to stderr."""
    if not DEBUG:
        return
    kwargs.setdefault("file", sys.stderr)
    print(*args, **kwargs)


def info(*args, **kwargs):
    """Informational print to stderr which respects compact-only mode.

    It is suppressed when --compact is set and --debug is not set.
    """
    # If compact-only mode is enabled and debug is not enabled, suppress info.
    if COMPACT_ONLY and not DEBUG:
        return
    kwargs.setdefault("file", sys.stderr)
    print(*args, **kwargs)

def truncate(s: str, width: int) -> str:
    if s is None:
        return ""
    s = str(s)
    if len(s) <= width:
        return s
    if width <= 3:
        return s[:width]
    return s[: width - 3] + "..."

def concise_line(
    idx: int,
    total: int,
    old: str,
    new: Optional[str],
    status: str,
    old_w: Optional[int] = None,
    new_w: Optional[int] = None,
    width: Optional[int] = None,
) -> str:
    # format index
    idx_fmt = f"[{idx:03}/{total:03}]"
    # determine total desired width
    w = width if width is not None else OUTPUT_WIDTH
    if w is None:
        # fallback to previous defaults
        old_w = old_w or 40
        new_w = new_w or 60
    else:
        # reserve space for index and separators (' | ' twice -> 6 chars)
        rem = max(w - len(idx_fmt) - 6, 20)
        # allow callers to override old_w/new_w, else split rem
        if old_w is None and new_w is None:
            # prefer a smaller left column for the old summary
            left = max(int(rem * 0.38), 10)
            right = rem - left
            old_w, new_w = left, right
        else:
            old_w = old_w or max(int(rem * 0.38), 10)
            new_w = new_w or (rem - old_w)

    if status == "OK":
        o = truncate(old or "", old_w)
        n = truncate(new or "", new_w)
        return f"{idx_fmt} | {o:<{old_w}} | {n:<{new_w}}"
    else:
        # center FAILED over the combined width
        comb_w = (old_w or 0) + 3 + (new_w or 0)
        label = "FAILED"
        return f"{idx_fmt} | {label:^{comb_w}}"

DISPLAY_RE = re.compile(r"^TIProjectTemplate\.displayName\.([A-Za-z0-9_]+)=(.*)$")
SUMMARY_RE = re.compile(r"^TIProjectTemplate\.summary\.([A-Za-z0-9_]+)=(.*)$")


def read_en(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def parse_entries(lines: List[str]) -> List[Tuple[str, Optional[str], Optional[str], int, int]]:
    """Return list of tuples: (dataName, display, summary, display_idx, summary_idx)
    summary_idx may be -1 if not present.
    """
    entries: Dict[str, Dict[str, Any]] = {}
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
            display = cast(Optional[str], info.get("display"))
            summary = cast(Optional[str], info.get("summary"))
            display_idx = cast(int, info.get("display_idx", -1))
            summary_idx = cast(int, info.get("summary_idx", -1))
            ordered.append((name, display, summary, display_idx, summary_idx))

    return ordered


def call_ollama(
    model: str,
    prompt: str,
    temperature: float,
    top_p: float,
    top_k: int,
    presence_penalty: float,
    timeout: int = 60,
    ollama_url: Optional[str] = None,
    storage_service: Optional[str] = None,
    storage_run_dir: Optional[str] = None,
    max_extraction_size: int = 200000,
): 
    """Try Ollama HTTP API first (if available) then fall back to CLI.

    Returns the response text from Ollama.
    """
    # prefer explicit function param, then OLLAMA_URL env var, otherwise default
    ollama_url = ollama_url or os.environ.get("OLLAMA_URL") or "http://localhost:11434"

    # attempt HTTP API
    try:
        endpoint = ollama_url.rstrip("/")
        if not endpoint.endswith("/api/generate"):
            endpoint = endpoint + "/api/generate"
        # log attempt
        info(f"Attempting Ollama HTTP API -> {endpoint} (model={model})")
        # Send model and any chat options in the JSON body — some Ollama servers
        # expect this rather than query params. This is more robust across versions.
        body = {
            "model": model,
            "prompt": prompt,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "presence_penalty": presence_penalty,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        # Use streaming POST so large NDJSON responses don't need to be
        # buffered fully in memory. We write each incoming line to the
        # run-specific raw file and assemble token fragments as they arrive.
        try:
            # Use a short connect timeout and rely on our per-call overall
            # timeout handling below to decide when to abort a long streaming
            # request. requests timeout accepts (connect, read).
            r = requests.post(endpoint, json=body, timeout=(10, timeout), stream=True)
        except Exception as ex:
            raise

        # prepare storage paths
        try:
            parsed = urllib.parse.urlparse(ollama_url)
            host = parsed.hostname or parsed.path or "remote"
        except Exception:
            host = "remote"
        safe_host = re.sub(r"[^A-Za-z0-9_.-]", "_", host)
        safe_model = re.sub(r"[^A-Za-z0-9_.-]", "_", model)
        if storage_run_dir:
            storage_dir_raw = storage_run_dir
        else:
            if storage_service:
                service_name = storage_service
            else:
                service_name = os.path.splitext(os.path.basename(__file__))[0]
            storage_dir_raw = os.path.join("scripts", "storage", service_name)
        os.makedirs(storage_dir_raw, exist_ok=True)
        raw_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        raw_name = f"raw_http_{safe_host}_{safe_model}_{raw_ts}.json"
        raw_path = os.path.join(storage_dir_raw, raw_name)
        extracted_name = f"extracted_{safe_host}_{safe_model}_{raw_ts}.txt"
        extracted_path = os.path.join(storage_dir_raw, extracted_name)

        buffers: Dict[str, List[str]] = {}
        done_flag = False
        # chosen_key is the priority key we will stream to the extracted file
        chosen_key: Optional[str] = None
        written_size = 0
        # stream and collect
        start_ts = time.monotonic()
        try:
            # open both raw and extracted files so they are always present and
            # incrementally written as data arrives. This avoids a race where
            # an assembled extracted file exists but the raw file appears empty.
            with open(raw_path, "w", encoding="utf-8") as rf, open(extracted_path, "w", encoding="utf-8") as ef:
                for ln in r.iter_lines(decode_unicode=True):
                    # enforce per-call overall timeout
                    if timeout and (time.monotonic() - start_ts) > timeout:
                        info(f"HTTP stream timeout after {timeout}s for model={model}")
                        # close connection and raise to fallback to CLI
                        try:
                            r.close()
                        except Exception:
                            pass
                        raise RuntimeError("ollama call timed out (http stream)")

                    if ln is None:
                        continue
                    line = ln.strip()
                    if not line:
                        continue
                    # write raw line for debugging
                    try:
                        rf.write(line + "\n")
                        rf.flush()
                    except Exception:
                        pass
                    # try parse JSON line and collect string fragments
                    try:
                        j = json.loads(line)
                    except Exception:
                        # non-JSON line — skip
                        continue
                    if isinstance(j, dict):
                        # accumulate string leaves per key
                        for k, v in j.items():
                            if isinstance(v, str):
                                buffers.setdefault(k, []).append(v)
                                # if we haven't chosen a key yet, and this key is
                                # one of the priority keys, pick it (highest
                                # priority among seen keys). This lets us
                                # stream the most likely final text to the
                                # extracted file incrementally.
                                if chosen_key is None:
                                    for pk in ("response", "text", "output", "result", "content", "message", "thinking"):
                                        if pk in buffers:
                                            chosen_key = pk
                                            break
                                # if this fragment belongs to the chosen key,
                                # append it to the extracted file (bounded).
                                if chosen_key and k == chosen_key and written_size < max_extraction_size:
                                    try:
                                        # trim fragment if it would exceed cap
                                        remaining = max_extraction_size - written_size
                                        to_write = v if len(v) <= remaining else v[:remaining]
                                        ef.write(to_write)
                                        ef.flush()
                                        written_size += len(to_write)
                                    except Exception:
                                        pass
                        # detect done signal
                        if j.get("done") is True or j.get("done_reason"):
                            done_flag = True
                    # if done and we have response-like content, we can stop early
                    if done_flag and any(k in buffers for k in ("response", "text", "output")):
                        # assemble the best candidate we have so far and return immediately
                        best_now = None
                        for key_now in ("response", "text", "output", "result", "content", "message", "thinking"):
                            if key_now in buffers:
                                cand_now = "".join(buffers[key_now]).strip()
                                if cand_now:
                                    best_now = cand_now
                                    break
                        if best_now is None:
                            # fallback to longest
                            best_now = ""
                            for parts_now in buffers.values():
                                c = "".join(parts_now).strip()
                                if c and len(c) > len(best_now):
                                    best_now = c

                        # ensure extracted file contains at least the best
                        # candidate (write if not already present or if it's
                        # larger than what we've streamed). Then return.
                        try:
                            # if what we streamed is shorter than best_now,
                            # overwrite the extracted file with the full best
                            # candidate to ensure coherency.
                            current_len = 0
                            try:
                                current_len = os.path.getsize(extracted_path)
                            except Exception:
                                current_len = 0
                            if current_len < len(best_now):
                                with open(extracted_path, "w", encoding="utf-8") as ef_now:
                                    ef_now.write(best_now)
                                info(f"Saved extracted text to: {extracted_path}")
                        except Exception:
                            pass
                        try:
                            r.close()
                        except Exception:
                            pass
                        return best_now, "http"
        except Exception:
            # if streaming failed, fall back to reading full response body
            try:
                text_raw = r.text
            except Exception:
                text_raw = ""
            # save fallback raw
            try:
                with open(raw_path, "w", encoding="utf-8") as rf:
                    rf.write(text_raw)
            except Exception:
                pass
            # attempt to parse what we can
            nd = parse_ndjson_responses(text_raw)
            if nd:
                text = nd
            else:
                text = text_raw.strip()
        else:
            # streaming completed normally; ensure extracted file exists
            # (it was created at loop start) and report saved raw path.
            info(f"Saved raw HTTP response to: {raw_path}")

        # After streaming completes (or we broke early) assemble best candidate
        text = None
        # prefer buffers in priority order
        for key in ("response", "text", "output", "result", "content", "message", "thinking"):
            if key in buffers:
                combined = "".join(buffers[key]).strip()
                if combined:
                    text = combined
                    break
        if text is None:
            # fallback: pick the longest assembled buffer
            best = ""
            for parts in buffers.values():
                cand = "".join(parts).strip()
                if cand and len(cand) > len(best):
                    best = cand
            text = best or ""

        # persist extracted text for debugging/auditing
        try:
            # write assembled text to extracted file if it's not already
            # present or if the assembled text is larger than what we
            # incrementally wrote.
            try:
                current_len = os.path.getsize(extracted_path)
            except Exception:
                current_len = 0
            if current_len < len(text or ""):
                with open(extracted_path, "w", encoding="utf-8") as ef:
                    ef.write(text)
            info(f"Saved extracted text to: {extracted_path}")
        except Exception:
            pass

        # If we successfully assembled text from the stream, return it
        # immediately — some Ollama servers may return an HTTP error after
        # streaming the final response, so accept the extracted text.
        if text:
            return text, "http"

        # If no direct text, try JSON extraction
        if not text:
            try:
                j = r.json()
                extracted = extract_text_from_resp_json(j)
                if extracted:
                    return extracted, "http"
                # fallback to common keys
                if isinstance(j, dict):
                    for k in ("text", "output", "result"):
                        if k in j and isinstance(j[k], str):
                            return j[k].strip(), "http"
                # If we couldn't extract, save the raw JSON for inspection
                try:
                    parsed = urllib.parse.urlparse(ollama_url)
                    host = parsed.hostname or parsed.path or "remote"
                except Exception:
                    host = "remote"
                safe_host = re.sub(r"[^A-Za-z0-9_.-]", "_", host)
                safe_model = re.sub(r"[^A-Za-z0-9_.-]", "_", model)
                storage_dir = os.path.join("scripts", "storage", os.path.splitext(os.path.basename(__file__))[0])
                os.makedirs(storage_dir, exist_ok=True)
                ts2 = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                raw_name = f"raw_http_{safe_host}_{safe_model}_{ts2}.json"
                raw_path = os.path.join(storage_dir, raw_name)
                try:
                    with open(raw_path, "w", encoding="utf-8") as rf:
                        # write the full response body
                        rf.write(r.text)
                    info(f"Saved raw HTTP response to: {raw_path}")
                except Exception:
                    pass
                # fallback to full JSON string
                return r.text.strip(), "http"
            except Exception:
                text = ""

        # If the HTTP status was an error (>=400) but we were able to extract
        # a useful payload, accept it; otherwise save diagnostics and raise.
        if r.status_code >= 400:
            # try to extract from the text we collected above
            if text:
                # accept extracted text even if status was non-2xx
                return text, "http"
            # nothing usable extracted; save response details for debugging
            try:
                detail = (r.text or "")[:1000]
            except Exception:
                detail = "<no-body>"
            dbg_path = os.path.join("scripts", "logs")
            os.makedirs(dbg_path, exist_ok=True)
            fname = os.path.join(dbg_path, f"ollama_http_error_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            try:
                with open(fname, "w", encoding="utf-8") as fh:
                    fh.write(f"URL: {endpoint}\nSTATUS: {r.status_code}\nRESPONSE:\n{r.text}\n")
            except Exception:
                pass
            raise RuntimeError(f"Ollama HTTP error {r.status_code}: response saved to {fname}; snippet: {detail}")

        # If the server returned a text body that looks like JSON wrapper, try to parse it
        if text.startswith("{") or text.startswith("["):
            try:
                j = json.loads(text)
                extracted = extract_text_from_resp_json(j)
                if extracted:
                    return extracted, "http"
                # couldn't find useful nested text; try a last-ditch regex extraction
                # look for long quoted substrings inside the JSON wrapper
                try:
                    # Try to extract a long quoted value for common keys like "response" or "text",
                    # allowing for escaped quotes inside the string.
                    m = re.search(r'"(?:response|text|output|result)"\s*:\s*"((?:\\.|[^"\\]){20,10000})"', text)
                    if m:
                        raw = m.group(1)
                        try:
                            # safe unescape using JSON string decoding
                            cand = json.loads('"' + raw + '"')
                        except Exception:
                            # fallback to unicode_escape
                            cand = bytes(raw, "utf-8").decode("unicode_escape", errors="ignore")
                        cand = cand.strip()
                        if cand and len(cand) >= 20 and not looks_suspicious(cand):
                            return cand, "http"
                    # generic fallback: extract any long quoted substring (with escapes)
                    generic = re.findall(r'"((?:\\.|[^"\\]){20,10000})"', text)
                    for raw in generic:
                        try:
                            cand = json.loads('"' + raw + '"')
                        except Exception:
                            cand = bytes(raw, "utf-8").decode("unicode_escape", errors="ignore")
                        cand = cand.strip()
                        if cand and len(cand) >= 20 and not looks_suspicious(cand):
                            return cand, "http"
                except Exception:
                    pass
                # couldn't find via regex; save raw response for inspection
                try:
                    parsed = urllib.parse.urlparse(ollama_url)
                    host = parsed.hostname or parsed.path or "remote"
                except Exception:
                    host = "remote"
                safe_host = re.sub(r"[^A-Za-z0-9_.-]", "_", host)
                safe_model = re.sub(r"[^A-Za-z0-9_.-]", "_", model)
                storage_dir = os.path.join("scripts", "storage", os.path.splitext(os.path.basename(__file__))[0])
                os.makedirs(storage_dir, exist_ok=True)
                ts2 = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                raw_name = f"raw_http_{safe_host}_{safe_model}_{ts2}.json"
                raw_path = os.path.join(storage_dir, raw_name)
                try:
                    with open(raw_path, "w", encoding="utf-8") as rf:
                        rf.write(text)
                    info(f"Saved raw HTTP response to: {raw_path}")
                except Exception:
                    pass
            except Exception:
                pass
            return text, "http"
    except Exception as ex:
        # fallback to CLI
        info(f"Ollama HTTP attempt failed: {ex}. Falling back to ollama CLI.")
        # continue to CLI fallback
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
    info(f"Used ollama CLI for model={model}")
    return proc.stdout.strip(), "cli"


def make_prompt(display: str, current_summary: Optional[str], data_name: Optional[str] = None) -> str:
    s = current_summary or ""
    # If the data name indicates a tiered progression (lvl1..lvl6 or mkI..mkVI)
    # provide a small contextual hint so the model uses wording appropriate
    # for the item's tier within a progression.
    level_hint = ""
    # consider both data_name and display text when detecting tier markers
    combined = ""
    if data_name:
        combined += data_name + " "
    if display:
        combined += display
    dn = combined.lower()
    # detect numeric levels like _lvl1 .. _lvl6, _lvl_1, _lvl-1
    m = re.search(r"_lvl[_\-]?([1-6])\b", dn)
    if not m:
        # also accept forms like '_level1', 'level1', or 'level 1' in dataName/display
        m = re.search(r"(?:_level[_\-]?|\blevel\s*[_\-]?\s*)([1-6])\b", dn)
    if m:
        lvl = int(m.group(1))
        # Provide concrete, short guidance and examples so the model uses
        # tier-appropriate wording rather than generic rewrites.
        level_hint = (
            f"\n\nNOTE: This project is Level {lvl} of 6 in a progression. Use wording that reflects the tier. "
            "Begin the summary with a short tier descriptor (one word) or leading adjective to indicate level: "
            "Level 1 -> 'Basic', Level 2-3 -> 'Improved' or 'Enhanced', Level 4-5 -> 'Advanced' or 'Optimized', Level 6 -> 'State-of-the-art'. "
            "Examples: \n  Level 1: 'Basic water optimization improves material efficiency.' \n  Level 6: 'State-of-the-art water optimization applies advanced heuristics to maximize material efficiency.' "
            "Keep the final summary concise (single line) and do not include reasoning."
        )
    else:
        # detect mk I..VI (e.g. _mkI, _mki) and variants like _mk_I or _mk-I
        m2 = re.search(r"_mk[_\-]?(i|ii|iii|iv|v|vi)\b", dn)
        if m2:
            # map roman to number for message clarity
            roman = m2.group(1).upper()
            roman_map = {"I":1,"II":2,"III":3,"IV":4,"V":5,"VI":6}
            num = roman_map.get(roman, None)
            if num:
                level_hint = (
                    f"\n\nNOTE: This project is Mark {roman} of VI in a progression. Use wording that reflects the tier. "
                    "Begin the summary with a short tier descriptor (one word) or leading adjective to indicate mark: "
                    "Mark I -> 'Basic', Mark II-III -> 'Improved' or 'Enhanced', Mark IV-V -> 'Advanced' or 'Optimized', Mark VI -> 'State-of-the-art'. "
                    "Examples: \n  Mark I: 'Basic micro-missile bay provides simple swarming capability.' \n  Mark VI: 'State-of-the-art micro-missile bay delivers best-in-class swarming performance.' "
                    "Keep the final summary concise (single line) and do not include reasoning."
                )

    prompt = (
        "You are an assistant that rewrites short project summaries for a game. "
        "Given the project display name and current summary, return an improved, concise summary (one or two sentences) "
        "that preserves meaning, is in English, and fits a UI tooltip. Return ONLY the new summary text with no headings."
        " Do NOT include any chain-of-thought, step-by-step reasoning, analysis, or internal deliberation. "
        "Output must be a single line containing only the final summary.\n\n"
        f"Project name: {display}\n"
        f"Current summary: {s}\n\n"
        "New summary:" + level_hint
    )
    return prompt


def make_strict_prompt(display: str, current_summary: Optional[str], data_name: Optional[str] = None) -> str:
    """Stricter prompt used for retries when model emits reasoning/artifacts.

    This reminds the model explicitly that any chain-of-thought or meta
    commentary will be rejected and that output must be a single-line
    summary only.
    """
    base = make_prompt(display, current_summary, data_name)
    extra = (
        "\n\nIMPORTANT: If your previous response included any internal\n"
        "reasoning, chain-of-thought, or commentary (for example: '<think>',\n"
        "'Okay, now', 'I will', numbered steps, or analysis), do NOT repeat it.\n"
        "Return exactly one short English sentence or two (single line) that is\n"
        "the final summary. Any extra text will be rejected.\n"
        "If you must, refuse with a single line: 'Unable to produce summary.'"
    )
    return base + extra


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
    # strip leading labels often emitted by some servers (e.g. "IMPORTANT:")
    cleaned = re.sub(r"^\s*(?:IMPORTANT|NOTE|FINAL(?: ANSWER)?|FINAL CHOICE|FINAL)[:\-—\s]+", "", cleaned, flags=re.IGNORECASE)
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


def extract_text_from_resp_json(obj: object) -> Optional[str]:
    """Recursively search a JSON-response for a plausible generated text string.

    Heuristics:
    - Prefer keys in the priority list (response, text, output, result, content, message)
    - If a value is a string and looks like JSON, try parsing and recurse
    - For lists, search their elements
    - Accept the first string >= 20 chars that does not look like a JSON wrapper
    """
    priority_keys = [
        "response",
        "text",
        "output",
        "result",
        "content",
        "message",
        "completion",
        "generated_text",
        "generation",
        "generations",
        "choices",
    ]

    def is_plausible_string(s: str) -> bool:
        ss = s.strip()
        if len(ss) < 20:
            return False
        # avoid returning JSON wrappers as strings
        if ss.startswith("{") and "\"model\"" in ss:
            return False
        return True

    def recurse(x: object) -> Optional[str]:
        if x is None:
            return None
        if isinstance(x, str):
            # if string looks like embedded JSON, try to parse it and recurse
            s = x.strip()
            if (s.startswith("{") or s.startswith("[")):
                try:
                    parsed = json.loads(s)
                    return recurse(parsed)
                except Exception:
                    pass
            if is_plausible_string(s):
                return s
            return None

        if isinstance(x, dict):
            # try priority keys first
            for k in priority_keys:
                if k in x:
                    v = x[k]
                    # some APIs nest message/content: {choices:[{message:{content:...}}]}
                    res = recurse(v)
                    if res:
                        return res

            # otherwise iterate keys
            for v in x.values():
                res = recurse(v)
                if res:
                    return res
            return None

        if isinstance(x, list):
            for item in x:
                res = recurse(item)
                if res:
                    return res
            return None

        return None

    try:
        res = recurse(obj)
        if res:
            return res
        # fallback: collect all string leaves and return the longest plausible one
        leaves: List[str] = []

        def collect_strings(y: object):
            if y is None:
                return
            if isinstance(y, str):
                leaves.append(y.strip())
                return
            if isinstance(y, dict):
                for vv in y.values():
                    collect_strings(vv)
                return
            if isinstance(y, list):
                for it in y:
                    collect_strings(it)
                return

        collect_strings(obj)
        # filter and pick the longest plausible string
        plausible = [s for s in leaves if is_plausible_string(s)]
        if plausible:
            # prefer longest (often full generated output)
            return max(plausible, key=len)
        return None
    except Exception:
        return None


def parse_ndjson_responses(text: str) -> Optional[str]:
    """Parse newline-delimited JSON streaming responses and join their 'response' fields.

    Many Ollama servers stream tokens as separate JSON objects with a 'response' key.
    This function collects those in order and returns the joined string if found.
    """
    if not text:
        return None
    # Collect small token fragments from NDJSON streaming responses.
    # Some Ollama deployments stream tokens under different keys ("response",
    # "thinking", "text", "output", ...). We collect string fragments per
    # key and then pick the best assembled buffer.
    if not text:
        return None
    buffers: Dict[str, List[str]] = {}
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            j = json.loads(ln)
        except Exception:
            # not JSON — skip
            continue
        if not isinstance(j, dict):
            continue
        for k, v in j.items():
            if isinstance(v, str):
                buffers.setdefault(k, []).append(v)

    if not buffers:
        return None

    # priority order for selecting which buffer to use
    priority = ["response", "text", "output", "result", "content", "message", "thinking"]
    for key in priority:
        if key in buffers:
            combined = "".join(buffers[key]).strip()
            if combined:
                return combined

    # fallback: pick the longest assembled string among buffers
    longest = None
    best_len = 0
    for parts in buffers.values():
        cand = "".join(parts).strip()
        if cand and len(cand) > best_len:
            longest = cand
            best_len = len(cand)
    return longest


def looks_suspicious(candidate: str) -> bool:
    """Return True if the candidate looks like reasoning/meta-text instead of a summary.

    Uses simple heuristics: presence of words/phrases commonly used in analysis or
    instructions, very short/very long length, or line containing markup.
    """
    if not candidate:
        return True
    low = candidate.lower()
    # common reasoning/analysis indicators
    bad_tokens = [
        "<think>", "thinking", "i will", "i need", "i will", "i'm going to",
        "okay,", "okay ", "now i", "as an ai", "final answer", "analysis",
        "process", "steps", "step ", "1.", "2.", "three", "because",
        "here's", "here is", "note:", "note -", "--","->",
    ]
    for t in bad_tokens:
        if t in low:
            return True
    # markup-like output
    if any(ch in candidate for ch in "*[]#<>" ):
        return True
    # require reasonable length for a UI tooltip: at least 20 chars, not absurdly long
    if len(candidate) < 20 or len(candidate) > 300:
        return True
    return False


def contains_token_artifacts(s: str) -> bool:
    """Detect model token artifacts like <unused41>, <bos>, <mask>, etc.

    Returns True if the string contains many angle-bracketed token markers or
    obviously tokenized fragments which indicate the model returned internal
    token names rather than natural language.
    """
    if not s:
        return False
    # common tokens: <unusedNN>, <bos>, <mask>, <pad>, <unk>, <nl>, etc.
    # generic heuristic: count angle-bracketed tokens and compare to total words
    toks = re.findall(r"<[^>\s]{2,}>", s)
    # also detect common token word patterns that may lack brackets
    toks2 = re.findall(r"\bunused\d+\b", s, flags=re.IGNORECASE)
    # detect repeated angle-bracket clusters like <x><y><z>
    cluster = re.search(r"(?:<[^>\s]{2,}>){3,}", s)
    if not toks:
        if not toks2 and not cluster:
            return False
    # if there are several tokens or they make up a large fraction, treat as artifacts
    if len(toks) + len(toks2) >= 3 or cluster:
        return True
    words = re.findall(r"\w+", s)
    if words:
        if (len(toks) + len(toks2)) / max(1, len(words)) > 0.25:
            return True
    return False


def strip_token_artifacts(s: str) -> str:
    """Remove common token artifacts to try to recover readable text.

    This strips angle-bracketed tokens and collapses multiple whitespace.
    """
    if not s:
        return s
    # remove angle-bracket tokens
    out = re.sub(r"<[^>\s]{2,}>", " ", s)
    # remove standalone 'unusedNN' tokens that may be present without brackets
    out = re.sub(r"\bunused\d+\b", " ", out, flags=re.IGNORECASE)
    # collapse repeated non-word sequences like '... <mask> ...'
    out = re.sub(r"\s+", " ", out)
    return out.strip()


def contains_bracket_tag(s: str) -> bool:
    """Return True if the string is or contains short bracketed tags like [multimodal]."""
    if not s:
        return False
    # match a lone bracket token or many bracket tokens making up most of text
    tags = re.findall(r"\[[^\]]+\]", s)
    if not tags:
        return False
    # if the entire string is a single bracket tag (possibly with surrounding space)
    if re.fullmatch(r"\s*\[[^\]]+\]\s*", s):
        return True
    # if tags are many and make up a large fraction of the content, treat as taggy
    non_ws = re.sub(r"\s+", "", s)
    tag_chars = sum(len(t) for t in tags)
    if tag_chars / max(1, len(non_ws)) > 0.25:
        return True
    return False


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
    # default timeout increased to 10 minutes for slow remote endpoints
    p.add_argument("--timeout", type=int, default=600, help="Timeout seconds for each ollama call")
    p.add_argument("--dry-run", action="store_true", help="Do not write file; just print intended updates")
    p.add_argument("--health-check", action="store_true", help="Enable pre-flight Ollama health check (disabled by default)")
    p.add_argument("--commit-every", type=int, default=1, help="Write updates to the EN file every N entries (default 1). Set to 0 to write only at end of run.)")
    p.add_argument("--retries", type=int, default=2, help="Number of retry attempts when output looks like chain-of-thought")
    p.add_argument("--ollama", help="Ollama server URL (overrides OLLAMA_URL env var), e.g. http://localhost:11434")
    p.add_argument("--save-diff", action="store_true", help="Store a unified diff of the changes in scripts/storage/<service>/")
    p.add_argument("--storage-service", help="Name of the service to use for storage subfolder (defaults to host from --ollama)")
    p.add_argument("--min-http-length", type=int, default=10, help="Minimum length (chars) to accept HTTP responses without strict suspicious check")
    p.add_argument("--keep-runs", type=int, default=3, help="Number of past run folders to keep in scripts/storage/<service>/")
    p.add_argument("--max-extraction-size", type=int, default=200000, help="Maximum bytes to incrementally write to extracted_*.txt while streaming (prevents unbounded growth)")
    p.add_argument("--compact", action="store_true", default=True, help="Compact per-entry output: single-line summary per entry and final table summary (default)")
    p.add_argument("--debug", action="store_true", help="Verbose debug output (raw saves, HTTP details). Overrides compact")
    p.add_argument("--width", type=int, help="Desired output width for concise lines (columns). If omitted the script will try to use terminal width.")
    args = p.parse_args(argv)

    enpath = args.en
    # Effective Ollama server we'll attempt to use (param > env > default)
    effective_ollama = args.ollama or os.environ.get("OLLAMA_URL") or "http://localhost:11434"
    # wire debug and compact-only flags
    global DEBUG, COMPACT_ONLY
    DEBUG = bool(args.debug)
    COMPACT_ONLY = bool(args.compact)
    global OUTPUT_WIDTH
    if args.width:
        OUTPUT_WIDTH = int(args.width)
    else:
        # try to detect terminal width, otherwise None
        try:
            OUTPUT_WIDTH = shutil.get_terminal_size().columns
        except Exception:
            OUTPUT_WIDTH = None

    # print initial info (always show)
    info(f"Using Ollama server: {effective_ollama}")
    info(f"Using model: {args.model}")
    dbg("Will attempt Ollama HTTP API first, fall back to ollama CLI if HTTP fails.")

    # Prepare storage run directory so all artifacts for this run land together.
    if args.storage_service:
        service_name = args.storage_service
    else:
        try:
            service_name = os.path.splitext(os.path.basename(__file__))[0]
        except Exception:
            service_name = "service"

    run_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # short random suffix so multiple runs in same second are distinct
    import uuid

    run_id = f"{run_ts}_{uuid.uuid4().hex[:6]}"
    storage_run_dir = os.path.join("scripts", "storage", service_name, run_id)
    os.makedirs(storage_run_dir, exist_ok=True)
    info(f"Storage run directory: {storage_run_dir}")
    # pre-flight health check to detect tokenized or malformed outputs
    def health_check_ollama(model: str, ollama_url: str, timeout: int = 10, tries: int = 3) -> Tuple[bool, Dict[str, Any]]:
        """Run a small canonical prompt against the Ollama HTTP API and
        compute simple quality metrics. Try a non-streaming POST first,
        then fall back to streaming attempts if needed. Returns (ok, details).
        """
        endpoint = ollama_url.rstrip("/")
        if not endpoint.endswith("/api/generate"):
            endpoint = endpoint + "/api/generate"
        prompt = "Say: Hello world."
        last_raw = ""
        last_extracted = ""
        token_frac = None
        printable = None

        body = {"model": model, "prompt": prompt, "temperature": 0.0, "top_p": 1.0, "top_k": 1, "presence_penalty": 0.0}

        # 1) Try a quick non-streaming POST first — many servers return full
        # body instead of streaming NDJSON and this is the most deterministic
        # check.
        try:
            nr = requests.post(endpoint, json=body, timeout=(3, max(5, timeout)), stream=False)
            last_raw = nr.text or ""
            last_extracted = parse_ndjson_responses(last_raw) or (nr.text or "")
            toks = re.findall(r"<[^>\\s]{2,}>", last_raw) + re.findall(r"\\bunused\\d+\\b", last_raw, flags=re.IGNORECASE)
            words = re.findall(r"\\w+", last_extracted)
            token_frac = len(toks) / max(1, len(words))
            printable = sum(1 for ch in last_extracted if ch.isalnum() or ch.isspace()) / max(1, len(last_extracted)) if last_extracted else 0.0
            details = {"method": "non-stream", "status_code": getattr(nr, 'status_code', None), "token_frac": token_frac, "printable": printable, "raw": last_raw, "extracted": last_extracted}
            # if non-stream returned readable text, consider that authoritative
            if token_frac <= 0.2 and printable >= 0.5 and len(words) >= 1:
                return True, details
            # otherwise, try streaming attempts (server may behave differently when streaming)
        except Exception:
            # fall through to streaming attempts
            last_raw = ""
            last_extracted = ""

        # 2) Streaming attempts: try up to `tries` times to collect NDJSON lines
        for attempt in range(1, tries + 1):
            try:
                r = requests.post(endpoint, json=body, timeout=(3, timeout), stream=True)
                raw_lines: List[str] = []
                start_ts = time.monotonic()
                for ln in r.iter_lines(decode_unicode=True):
                    if (time.monotonic() - start_ts) > timeout:
                        break
                    if ln is None:
                        continue
                    line = ln.strip()
                    if not line:
                        continue
                    raw_lines.append(line)
                    if len(raw_lines) >= 40:
                        break
                last_raw = "\n".join(raw_lines)
                details_small: Dict[str, Any] = {}
                extracted = parse_ndjson_responses(last_raw) or ""
                if not extracted:
                    # fallback to a non-streaming POST to capture full body
                    try:
                        nr2 = requests.post(endpoint, json=body, timeout=(3, max(5, timeout)), stream=False)
                        last_raw = nr2.text or last_raw
                        details_small = {"status_code": getattr(nr2, 'status_code', None), "headers": dict(getattr(nr2, 'headers', {}))}
                        extracted = parse_ndjson_responses(last_raw) or (nr2.text or "")
                    except Exception:
                        try:
                            extracted = r.text or last_raw
                        except Exception:
                            extracted = last_raw
                        details_small = {"status_code": getattr(r, 'status_code', None)}
                last_extracted = extracted
                toks = re.findall(r"<[^>\\s]{2,}>", last_raw) + re.findall(r"\\bunused\\d+\\b", last_raw, flags=re.IGNORECASE)
                words = re.findall(r"\\w+", last_extracted)
                token_frac = len(toks) / max(1, len(words))
                printable = sum(1 for ch in last_extracted if ch.isalnum() or ch.isspace()) / max(1, len(last_extracted)) if last_extracted else 0.0
                details = {"attempt": attempt, "method": "stream", "token_frac": token_frac, "printable": printable, "raw": last_raw, "extracted": last_extracted}
                if details_small:
                    details.update(details_small)
                if token_frac <= 0.2 and printable >= 0.5 and len(words) >= 1:
                    return True, details
            except Exception:
                last_raw = ""
                last_extracted = ""
                continue

        return False, {"attempts": tries, "raw": last_raw, "extracted": last_extracted, "token_frac": token_frac, "printable": printable}

    health_manifest = {"health_checked": False, "ok": None, "details": None}
    if args.health_check:
        ok, info_d = health_check_ollama(args.model, effective_ollama, timeout=min(10, args.timeout), tries=2)
        health_manifest["health_checked"] = True
        health_manifest["ok"] = bool(ok)
        health_manifest["details"] = info_d
        if not ok:
            # save diagnostic files for later inspection
            ts_h = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_dir = os.path.join("scripts", "logs")
            os.makedirs(log_dir, exist_ok=True)
            fname = os.path.join(log_dir, f"ollama_health_{ts_h}.txt")
            try:
                with open(fname, "w", encoding="utf-8") as fh:
                    fh.write(f"Ollama health check failed for model={args.model} at {effective_ollama}\n")
                    fh.write(json.dumps(info_d, ensure_ascii=False, indent=2))
                info(f"Ollama health check failed; details saved to {fname}")
            except Exception:
                info("Ollama health check failed; unable to write diagnostics file")
            # also save copies inside the run storage dir
            try:
                with open(os.path.join(storage_run_dir, f"health_raw_{ts_h}.txt"), "w", encoding="utf-8") as hf:
                    hf.write(info_d.get("raw", ""))
                with open(os.path.join(storage_run_dir, f"health_extracted_{ts_h}.txt"), "w", encoding="utf-8") as hf2:
                    hf2.write(info_d.get("extracted", ""))
            except Exception:
                pass
            # warn but continue (no auto-fallback per your request)
            print(f"WARNING: Ollama health check failed for {effective_ollama}; check {fname}", file=sys.stderr)
    # persist health manifest into the run folder so each run records whether
    # a health check was attempted and its outcome (helps automation traceability)
    try:
        manifest_path = os.path.join(storage_run_dir, "health_summary.json")
        with open(manifest_path, "w", encoding="utf-8") as mf:
            json.dump(health_manifest, mf, ensure_ascii=False, indent=2)
        dbg(f"Wrote health summary to: {manifest_path}")
    except Exception:
        pass

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

    total = end_idx - start_idx
    # commit bookkeeping
    commit_every = int(args.commit_every)
    first_backup_created = False
    first_backup_path: Optional[str] = None
    last_commit_count = 0
    for seq, i in enumerate(range(start_idx, end_idx), start=1):
        name, display, summary, display_idx, summary_idx = entries[i]
        if display is None:
            dbg(f"Skipping {name}: no displayName found")
            continue

        # Try generating, with retries if the model emits reasoning/meta-text
        attempts = 0
        new_summary = ""
        last_out = ""
        while attempts <= args.retries:
            attempts += 1
            prompt = make_prompt(display, summary, name) if attempts == 1 else make_strict_prompt(display, summary, name)
            try:
                out, source = call_ollama(
                    args.model,
                    prompt,
                    args.temperature,
                    args.top_p,
                    args.top_k,
                    args.presence_penalty,
                    timeout=args.timeout,
                    ollama_url=args.ollama,
                    storage_service=args.storage_service,
                    storage_run_dir=storage_run_dir,
                    max_extraction_size=args.max_extraction_size,
                )
            except RuntimeError as e:
                print(f"Error generating for {name}: {e}", file=sys.stderr)
                return 3

            last_out = out
            # sanitize result: keep single-line, strip surrounding quotes
            out_line = extract_final_summary(out)
            out_line = out_line.strip('"')

            # If the model returned token artifact fragments like <unused41>,
            # try to strip them and re-extract a cleaner summary before
            # deciding if the output is suspicious.
            try:
                if contains_token_artifacts(out) or contains_token_artifacts(out_line):
                    dbg(f"Token artifacts detected for {name}; attempting to strip tokens and re-extract.")
                    cleaned = strip_token_artifacts(out)
                    cleaned_line = extract_final_summary(cleaned).strip('"')
                    # also detect bracketed tags like [multimodal] which some
                    # servers emit; strip those too and re-extract.
                    if contains_bracket_tag(cleaned) and not contains_token_artifacts(cleaned_line):
                        cleaned = re.sub(r"\[[^\]]+\]", " ", cleaned)
                        cleaned_line = extract_final_summary(cleaned).strip('"')
                    # prefer cleaned candidate if it looks plausible
                    if cleaned_line and not looks_suspicious(cleaned_line):
                        out_line = cleaned_line
                        out = cleaned
                        dbg(f"Recovered cleaned summary for {name}: '{out_line[:120]}'")
                    else:
                        # if HTTP source and cleaned is reasonably long, accept it
                        if source == "http" and cleaned_line and len(cleaned_line) >= args.min_http_length:
                            out_line = cleaned_line
                            out = cleaned
                            dbg(f"Accepted cleaned HTTP summary for {name}: '{out_line[:120]}'")
            except Exception:
                pass

            # If the HTTP path produced this output, be more permissive: accept
            # reasonably short but valid-looking summaries from the HTTP API.
            # However, avoid accepting tokenized or bracket-tag outputs as-is.
            if (
                source == "http"
                and len(out_line) >= args.min_http_length
                and not (contains_token_artifacts(out_line) or contains_bracket_tag(out_line))
            ):
                new_summary = out_line
                break

            if not looks_suspicious(out_line):
                new_summary = out_line
                break
            else:
                dbg(f"Suspicious output for {name} on attempt {attempts}: '{out_line[:80]}'")
                if attempts > args.retries:
                    dbg(f"Giving up on {name} after {attempts} attempts; leaving unchanged.")
                    new_summary = summary or ""
                    break
                dbg(f"Retrying {name} (strict prompt)...")
        summary_key = f"TIProjectTemplate.summary.{name}="

        if summary_idx is not None and summary_idx >= 0:
            # replace existing line
            new_lines[summary_idx] = f"{summary_key}{new_summary}\n"
        else:
            # insert after display_idx
            insert_at = display_idx + 1 if display_idx >= 0 else len(new_lines)
            new_lines.insert(insert_at, f"{summary_key}{new_summary}\n")

        updated.append((name, summary or "", new_summary))
        # Compact output per entry (default) or verbose if debug
        if args.compact and not args.debug:
            status = "OK" if new_summary and new_summary != (summary or "") else "FAILED"
            line = concise_line(seq, total, summary or "", new_summary, status)
            # compact-only mode should only print the concise line
            print(line)
        else:
            dbg(f"Updated: {name}")

        # Commit (write) logic: write the EN file every `commit_every` entries
        if commit_every != 0 and (seq % commit_every == 0 or seq == total):
            # determine which entries were included in this commit
            commit_entries = updated[last_commit_count:]
            last_commit_count = len(updated)
            ts_commit = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                if args.dry_run:
                    info(f"Dry-run: would write EN file at seq={seq} (would include {len(commit_entries)} entries)")
                else:
                    # create backup on first commit
                    if not first_backup_created and os.path.exists(enpath):
                        try:
                            first_backup_path = backup_file(enpath)
                            first_backup_created = True
                            info(f"Created backup: {first_backup_path}")
                        except Exception as e:
                            info(f"Failed to create backup before first commit: {e}")
                    # atomic write
                    try:
                        safe_write(enpath, new_lines)
                        info(f"Wrote EN file after seq={seq}")
                    except Exception as e:
                        info(f"Failed to write EN file at seq={seq}: {e}")
                    # write per-commit metadata into run folder
                    try:
                        meta = {
                            "timestamp": ts_commit,
                            "seq": seq,
                            "entries_in_commit": [ {"name": n, "old": old, "new": new} for (n, old, new) in commit_entries ],
                            "backup": first_backup_path,
                        }
                        commit_name = f"commit_{seq:04d}.json"
                        commit_path = os.path.join(storage_run_dir, commit_name)
                        with open(commit_path, "w", encoding="utf-8") as cf:
                            json.dump(meta, cf, ensure_ascii=False, indent=2)
                        info(f"Saved commit metadata: {commit_path}")
                    except Exception:
                        pass
            except Exception:
                pass

    next_idx = end_idx
    next_name = entries[next_idx][0] if next_idx < len(entries) else ""

    # Final per-run summary counts
    total_processed = len(updated)
    success_count = sum(1 for (_n, old, new) in updated if new and new != (old or ""))
    unchanged_count = sum(1 for (_n, old, new) in updated if new == (old or ""))
    failed_count = total_processed - success_count - unchanged_count
    # print a compact table summary (always print, but keep verbose details in debug)
    # In compact-only mode we intentionally suppress the final summary so
    # output remains exactly one concise line per entry. If DEBUG is enabled
    # we still emit debug information.
    if DEBUG:
        dbg(f"Processed {total_processed} entries: Success={success_count}, Unchanged={unchanged_count}, Failed={failed_count}")
        if failed_count > 0:
            dbg("Failed entries:", [n for (n, old, new) in updated if not new or new == (old or "")])
    else:
        if not COMPACT_ONLY:
            print(f"Processed {total_processed} entries: Success={success_count}, Unchanged={unchanged_count}, Failed={failed_count}")
            if failed_count > 0:
                failed_names = [n for (n, old, new) in updated if not new or new == (old or "")]
                print("Failed entries:", ", ".join(failed_names))

    # If requested, save a unified diff of original -> new file under scripts/storage/<service>/
    if args.save_diff:
        # derive service name: explicit flag > script basename > 'service'
        if args.storage_service:
            service_name = args.storage_service
        else:
            try:
                script_basename = os.path.splitext(os.path.basename(__file__))[0]
                service_name = script_basename or "service"
            except Exception:
                service_name = "service"

        # store diffs/metadata inside the run folder so each run is self-contained
        storage_dir = os.path.join("scripts", "storage", service_name)
        os.makedirs(storage_dir, exist_ok=True)
        # ensure run dir exists
        os.makedirs(storage_run_dir, exist_ok=True)
        # cleanup old runs: keep only the most recent N run folders
        try:
            runs = sorted([
                d for d in os.listdir(storage_dir) if os.path.isdir(os.path.join(storage_dir, d))
            ])
            # runs are named with timestamp so sort keeps chronological order
            keep = args.keep_runs
            if len(runs) > keep:
                to_remove = runs[:-keep]
                for r in to_remove:
                    path_r = os.path.join(storage_dir, r)
                    try:
                        # remove files in dir then the dir
                        for fn in os.listdir(path_r):
                            fp = os.path.join(path_r, fn)
                            try:
                                os.remove(fp)
                            except Exception:
                                pass
                        os.rmdir(path_r)
                        info(f"Removed old run storage: {path_r}")
                    except Exception as e:
                        info(f"Failed to remove old run {path_r}: {e}")
        except Exception:
            pass
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        # sanitize model for filename
        safe_model = re.sub(r"[^A-Za-z0-9_.-]", "_", args.model)
        # derive host part for filename (ollama host or 'local')
        try:
            parsed = urllib.parse.urlparse(effective_ollama)
            host = parsed.hostname or parsed.path or "local"
        except Exception:
            host = "local"
        safe_host = re.sub(r"[^A-Za-z0-9_.-]", "_", host)
        diff_name = f"{safe_host}_{safe_model}_{ts}.diff"
        diff_path = os.path.join(storage_run_dir, diff_name)
        # only write if there are actual differences
        changed = lines != new_lines
        if changed:
            ud = difflib.unified_diff(lines, new_lines, fromfile=enpath, tofile=enpath, lineterm="\n")
            try:
                with open(diff_path, "w", encoding="utf-8") as df:
                    df.writelines(ud)
                info(f"Saved diff to: {diff_path}")
            except Exception as e:
                info(f"Failed to save diff to {diff_path}: {e}")
        else:
            info("No changes detected; no diff written.")

        # write companion JSON metadata + raw contents for easier parsing
        meta = {
            "timestamp": ts,
            "script": os.path.basename(__file__),
            "service": service_name,
            "ollama": effective_ollama,
            "host": host,
            "model": args.model,
            "changed": changed,
            "diff_file": diff_name if changed else None,
            "updated_entries": [{"name": n, "old": old, "new": new} for (n, old, new) in updated],
            "original_file": enpath,
        }
        json_name = f"{safe_host}_{safe_model}_{ts}.json"
        json_path = os.path.join(storage_run_dir, json_name)
        try:
            # include raw contents of original/new only when changed to avoid huge files
            if changed:
                meta["original_text"] = "".join(lines)
                meta["new_text"] = "".join(new_lines)
            with open(json_path, "w", encoding="utf-8") as jf:
                json.dump(meta, jf, ensure_ascii=False, indent=2)
            info(f"Saved metadata JSON to: {json_path}")
        except Exception as e:
            info(f"Failed to save metadata JSON to {json_path}: {e}")

    if args.dry_run:
        info("Dry-run enabled; no file was changed.")
        for name, old, new in updated:
            info(f"Would update {name}:\n  - old: {truncate(old,120)}\n  - new: {truncate(new,120)}")
        # Always print the next dataName to stdout so callers can resume from it
        if next_name:
            print(next_name)
        return 0

    # backup and write
    bak = backup_file(enpath)
    try:
        safe_write(enpath, new_lines)
    except Exception as e:
        print(f"Failed to write updated file: {e}", file=sys.stderr)
        print(f"Backup saved as: {bak}")
        return 4

    info(f"Backup created: {bak}")
    for name, old, new in updated:
        info(f"Wrote: {name}")
    # Print the next dataName (one line) so the caller can resume from here.
    if next_name:
        print(next_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
