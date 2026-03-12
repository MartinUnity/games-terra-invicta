"""Prompt builder helpers extracted from ai_worker.py to keep the main script small."""
from __future__ import annotations

from typing import Dict, List, Optional
import os


def build_fill_prompt(template: dict, chosen_effect: Optional[str], research_cost: int) -> str:
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


def build_localization_prompt(candidate: Optional[dict], tieffects_map: Optional[dict] = None) -> str:
    # Safely extract candidate fields; avoid calling .get on a None candidate.
    if not candidate:
        dn = "Project_Unknown"
        fn = "Unknown Project"
        cat = "Unknown"
        rc = 0
        effs: list = []
        prereqs: list = []
    else:
        dn = candidate.get("dataName", "Project_Unknown")
        fn = candidate.get("friendlyName", "Unknown Project")
        cat = candidate.get("techCategory", "Unknown")
        rc = candidate.get("researchCost", 0)
        effs = candidate.get("effects", []) or []
        prereqs = candidate.get("prereqs", []) or []

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


def build_prompt(requirements_md: str, prompt_template: str) -> str:
    base = ""
    if prompt_template and os.path.exists(prompt_template):
        try:
            with open(prompt_template, "r", encoding="utf-8") as f:
                base += f.read() + "\n\n"
        except Exception:
            pass
    base += "You are an assistant that must return exactly one JSON object only (no surrounding text)."
    base += "\nFollow the rules and constraints in the following requirements document:\n\n"
    base += requirements_md or ""
    base += "\n\nReturn only the JSON candidate object that fits the schema described above."
    base += '\nImportant: include an "effects" array containing one existing effect ID (string) that exactly matches an entry in /home/martin/Games/TerraInvicta/templates/TIEffectTemplate.json. Do NOT invent new effect IDs or full effect objects. If you cannot pick an existing effect, return { "error": "explanation" }.'
    base += '\n\nSTRICT WRAPPER: Output MUST be exactly three lines:\n<json>\n<the JSON object on one or more lines>\n</json>\nNo other text is allowed before or after these tags. If you cannot follow this format, return { "error": "reason" } inside the wrapper.'

    base += "\n\nEXAMPLES (must be followed exactly):"
    base += "\nValid - single-line JSON inside wrapper:" \
        + "\n<json> {\"dataName\": \"Project_Example\", \"friendlyName\": \"Example\", \"techCategory\": \"Energy\", \"researchCost\": 100, \"prereqs\": [], \"effects\": [\"Effect_Example\"]} </json>"
    base += "\nValid - multi-line JSON inside wrapper:" \
        + "\n<json>\n{\n  \"dataName\": \"Project_Example\",\n  \"friendlyName\": \"Example\",\n  \"techCategory\": \"Energy\",\n  \"researchCost\": 100,\n  \"prereqs\": [],\n  \"effects\": [\"Effect_Example\"]\n}\n</json>"
    base += "\nInvalid - any additional commentary or tags outside the wrapper is not allowed.\nIf you cannot produce a valid candidate, return exactly this wrapper with an error object inside:\n<json>{\"error\": \"explain why\"}</json>"

    base += "\n\nSHORT INSTRUCTION (if you are a smaller/local model): Return ONLY the three-line wrapper above containing a single JSON object. If you are unable to comply, return the error object inside the wrapper."
    return base


def build_simplified_fill_prompt(chosen_effect: Optional[str] = None, research_cost: int = 0) -> str:
    """Very small, strict fallback prompt for the fill step.

    This prompt asks the model to return exactly a three-line wrapper with
    a single JSON object containing `friendlyName` and optional `shortDescription`.
    """
    # Keep this prompt extremely short and prescriptive to help small/local models
    # obey the wrapper and return strict JSON.
    lines = [
        "Return ONLY the exact three-line wrapper shown below and nothing else.",
        "<json>",
        '{"friendlyName": "Example Name", "shortDescription": "A concise optional subtitle."}',
        "</json>",
    ]
    # Provide minimal context that may help the model choose an appropriate name.
    if chosen_effect:
        lines.insert(1, f"Effect: {chosen_effect}")
    if research_cost:
        lines.insert(1, f"Target researchCost: {research_cost}")
    # Constraints to encourage concise, relevant names
    lines.insert(1, "Constraints: friendlyName 3-40 characters; shortDescription optional, max 120 chars.")
    return "\n".join(lines)


def build_simplified_localization_prompt() -> str:
    """Very small, strict fallback prompt for localization generation.

    Asks for a three-line wrapper containing a single key `shortDescription`.
    """
    # Very small, strict prompt asking only for the JSON wrapper with a shortDescription.
    # Enforce character length to help downstream consumers and validation.
    return "\n".join([
        "Return ONLY the exact three-line wrapper shown below and nothing else.",
        "<json>",
        '{"shortDescription": "A concise, technical 120-200 character description appropriate for a project."}',
        "</json>",
    ])
