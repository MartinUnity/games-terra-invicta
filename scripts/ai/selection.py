"""Selection utilities for choosing project templates and effects."""
from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple, Optional


def select_template_and_effect(
    projects: List[Any], tieffects_map: Dict[str, List[str]], whitelist: List[str], category: Optional[str] = None, require_prereq: bool = False
) -> Tuple[Any, Optional[str]]:
    # pick a category if not provided
    candidates = projects
    if category:
        # ensure safe comparison when project entries may be non-dict
        candidates = [p for p in projects if isinstance(p, dict) and p.get("techCategory") == category]
    if not candidates:
        candidates = projects
    if not candidates:
        return (None, None)
    # Prefer templates that have a non-empty prereqs list when requested
    if require_prereq:
        pref = [p for p in candidates if isinstance(p, dict) and isinstance(p.get("prereqs"), list) and p.get("prereqs")]
        if pref:
            template = random.choice(pref)
        else:
            template = random.choice(candidates)
    else:
        template = random.choice(candidates)

    chosen_effect = None
    if isinstance(template, dict):
        # look for keys that look like effects
        for k, v in template.items():
            if isinstance(v, str) and v.startswith("Effect_"):
                if (
                    v in tieffects_map
                ):
                    chosen_effect = v
                    break
        # maybe template has an effects array
        if not chosen_effect:
            for v in template.values():
                if isinstance(v, list):
                    for it in v:
                        if isinstance(it, str) and it.startswith("Effect_") and it in tieffects_map:
                            chosen_effect = it
                            break
                    if chosen_effect:
                        break

    # fallback: random tieffect
    if not chosen_effect and tieffects_map:
        valid = [e for e in tieffects_map.keys()]
        if valid:
            chosen_effect = random.choice(valid)
        else:
            chosen_effect = None
    return (template, chosen_effect)
