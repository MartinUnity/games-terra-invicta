#!/usr/bin/env python3
"""
Generate docs/Projects_Outline.md with a mermaid dependency map.

Usage: run from repository root:
    python3 docs/generate_projects_outline.py

This script reads `Mods/TIProjectTemplate.json` and scans `Mods/*.json`
for `requiredProjectName` references, then writes `docs/Projects_Outline.md`.
"""
import glob
import json
import os
import pathlib
from collections import OrderedDict

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODS = ROOT / "Mods"
PROJECTS_FILE = MODS / "TIProjectTemplate.json"
EFFECTS_FILE = MODS / "TIEffectTemplate.json"
OUT_MD = ROOT / "docs" / "Projects_Outline.md"

PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]


def safe_id(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s)


def find_required(obj):
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "requiredProjectName":
                if isinstance(v, list):
                    results.extend(v)
                else:
                    results.append(v)
            else:
                results.extend(find_required(v))
    elif isinstance(obj, list):
        for it in obj:
            results.extend(find_required(it))
    return results


def collect_projects():
    with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
        projects = json.load(f)
    idx = OrderedDict()
    for p in projects:
        dn = p.get("dataName")
        fn = p.get("friendlyName") or dn
        idx[dn] = {
            "dataName": dn,
            "friendlyName": fn,
            "researchCost": p.get("researchCost"),
            "prereqs": p.get("prereqs") or [],
            "effects": p.get("effects") or [],
            "techCategory": p.get("techCategory") or "Uncategorized",
            "mods": [],
        }
    return idx


def scan_mods(idx):
    for path in sorted(glob.glob(str(MODS / "*.json"))):
        if os.path.basename(path) == "TIProjectTemplate.json":
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        reqs = find_required(data)
        for r in reqs:
            if r in idx:
                idx[r]["mods"].append(os.path.relpath(path, ROOT))
            else:
                idx.setdefault(
                    r,
                    {
                        "dataName": r,
                        "friendlyName": r,
                        "researchCost": None,
                        "prereqs": [],
                        "effects": [],
                        "techCategory": "Uncategorized",
                        "mods": [os.path.relpath(path, ROOT)],
                    },
                )


def build_category_map(idx):
    cats = OrderedDict()
    for p in idx.values():
        cat = p.get("techCategory") or "Uncategorized"
        if cat not in cats:
            cats[cat] = None
    # assign colors from palette
    for i, cat in enumerate(cats.keys()):
        cats[cat] = PALETTE[i % len(PALETTE)]
    return cats


def generate_mermaid(idx, cats, effects_map=None):
    lines = ["```mermaid", "graph LR"]
    # define nodes for projects: put project nodes first
    for dn, info in idx.items():
        node = safe_id(dn)
        # build label with research cost and (optional) mapped effects
        label_lines = [info["friendlyName"]]
        label_lines.append(f"cost: {info['researchCost']}")
        # map effects if available
        effs = info.get("effects") or []
        if isinstance(effs, list) and effects_map:
            mapped = []
            for e in effs:
                if isinstance(e, str) and e in effects_map:
                    meta = effects_map[e]
                    op = meta.get("operation")
                    val = meta.get("value")
                    ctxs = meta.get("contexts") or []
                    # human readable formatting: show only the final formatted value
                    name = ctxs[0] if ctxs else e
                    try:
                        if op == "Additive":
                            if isinstance(val, int):
                                display = f"{val}"
                            else:
                                display = f"{val*100:.0f}%"
                            desc = f"{name}: {display}"
                        elif op == "Multiplicative":
                            # multiplicative values like 1.03 -> +3%
                            try:
                                change = (val - 1.0) * 100.0
                                sign = "+" if change > 0 else ""
                                display = f"{sign}{change:.1f}%"
                                desc = f"{name}: {display}"
                            except Exception:
                                desc = f"{name}: ×{val}"
                        elif op == "IncreaseToValue" or op == "IncreaseTo":
                            if isinstance(val, int):
                                display = f"{val}"
                            else:
                                display = f"{val*100:.0f}%"
                            desc = f"{name}: set to {display}"
                        else:
                            # fallback: format floats as percent, ints as number
                            if isinstance(val, int):
                                display = f"{val}"
                            else:
                                display = f"{val*100:.0f}%"
                            desc = f"{name}: {display}"
                    except Exception:
                        desc = f"{name}: {val}"
                    mapped.append(desc)
            # include up to 3 effect descriptions to keep label compact
            for md in mapped[:3]:
                label_lines.append(md)
        # assemble label (always set, even if no effects_map provided)
        label = "<br>".join(label_lines)
        lines.append(f'{node}["{label}"]')
        # add class assignment line later
    # prereq nodes: ensure they exist as targets
    for dn, info in idx.items():
        for pr in info["prereqs"]:
            pid = safe_id(pr)
            if pr not in idx:
                lines.append(f'{pid}["{pr}"]')
            # Edge direction: project --> prereq (so projects are left)
            lines.append(f"{safe_id(dn)} --> {pid}")
    # mod nodes and edges
    for dn, info in idx.items():
        for m in info["mods"]:
            node_id = "Mod_" + safe_id(os.path.splitext(os.path.basename(m))[0])
            label = os.path.basename(m)
            lines.append(f'{node_id}["{label}"]')
            lines.append(f"{node_id} --> {safe_id(dn)}")
    # classDefs for categories
    for cat, color in cats.items():
        cls = "cat_" + safe_id(cat)
        lines.append(f"classDef {cls} fill:{color},stroke:#333,color:#fff;")
    # assign classes to project nodes
    for dn, info in idx.items():
        cls = "cat_" + safe_id(info.get("techCategory") or "Uncategorized")
        lines.append(f"class {safe_id(dn)} {cls};")
    lines.append("```")
    return "\n".join(lines)


def collect_effects():
    effects = {}
    try:
        with open(EFFECTS_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
    except Exception:
        return effects
    for e in items:
        dn = e.get("dataName")
        if not dn:
            continue
        effects[dn] = {
            "operation": e.get("operation"),
            "value": e.get("value"),
            "contexts": e.get("contexts") or [],
        }
    return effects


def write_docs(idx, mermaid, cats):
    out = []
    out.append("# Projects Outline")
    out.append("")
    out.append("This document is generated by `docs/generate_projects_outline.py`.")
    out.append("")
    out.append("## Categories & Colors")
    out.append("")
    # Render a small mermaid legend with colored boxes per category
    out.append("```mermaid")
    out.append("graph LR")
    for cat, color in cats.items():
        lid = "LEG_" + safe_id(cat)
        out.append(f'{lid}["{cat}"]')
    # classDefs for legend
    for cat, color in cats.items():
        cls = "cat_" + safe_id(cat)
        out.append(f"classDef {cls} fill:{color},stroke:#333,color:#fff;")
    # assign classes to legend nodes
    for cat in cats.keys():
        lid = "LEG_" + safe_id(cat)
        cls = "cat_" + safe_id(cat)
        out.append(f"class {lid} {cls};")
    out.append("```")
    out.append("")
    out.append("## Dependency Map")
    out.append("")
    out.append(mermaid)
    out.append("\n---\n")
    # per-project sections
    for dn, info in idx.items():
        out.append(f"## {info['friendlyName']} — {dn}")
        out.append("")
        out.append(f"- **researchCost**: {info['researchCost']}")
        out.append(f"- **techCategory**: {info.get('techCategory')}")
        out.append(f"- **prereqs**: {json.dumps(info['prereqs'], ensure_ascii=False)}")
        out.append(f"- **effects**: {json.dumps(info['effects'], ensure_ascii=False)}")
        if info["mods"]:
            out.append("- **referenced by mods**:")
            for m in info["mods"]:
                out.append(f"  - {m}")
        else:
            out.append("- **referenced by mods**: []")
        out.append("")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def main():
    idx = collect_projects()
    scan_mods(idx)
    cats = build_category_map(idx)
    effects_map = collect_effects()
    mermaid = generate_mermaid(idx, cats, effects_map)
    write_docs(idx, mermaid, cats)
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
