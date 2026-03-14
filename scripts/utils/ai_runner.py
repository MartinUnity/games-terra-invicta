"""Orchestration runner moved out of scripts/ai_worker.py.

Contains the main run_cycle(args) function that performs template selection,
calls the model, stages candidates, optionally generates localization and
auto-applies to Mods. Imports helper utilities from ai_worker_helpers and
ai_prompts with import fallbacks so the script can be executed from different
working directories.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import sys
from datetime import datetime, timezone
from typing import Any, Optional, cast, Dict, List

# compute repo root and ai-worker dir relative to this file
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AI_DIR = os.path.join(ROOT, "ai-worker")

# import helpers (try short path first)
try:
    from utils.ai_worker_helpers import (
        load_text,
        minimal_validate,
        write_staged,
        backup_staged,
        apply_candidate_to_mods,
        load_project_templates,
        collect_tieffects,
        load_effect_whitelist,
        effect_matches_whitelist,
        is_penalty_effect,
        roll_research_cost,
        generate_and_extract,
        estimate_base_cost,
        find_project_by_friendlyname,
        next_level_for_base,
        build_leveled_candidate,
    )
    from utils.ai_prompts import build_fill_prompt, build_localization_prompt, build_prompt
    from utils.ai_selection import select_template_and_effect
except Exception:
    from scripts.utils.ai_worker_helpers import (
        load_text,
        minimal_validate,
        write_staged,
        backup_staged,
        apply_candidate_to_mods,
        load_project_templates,
        collect_tieffects,
        load_effect_whitelist,
        effect_matches_whitelist,
        is_penalty_effect,
        roll_research_cost,
        generate_and_extract,
        estimate_base_cost,
        find_project_by_friendlyname,
        next_level_for_base,
        build_leveled_candidate,
    )
    from scripts.utils.ai_prompts import build_fill_prompt, build_localization_prompt, build_prompt
    from scripts.utils.ai_selection import select_template_and_effect


def run_cycle(args) -> dict:
    """Run a single generation cycle using provided `args` (same API as scripts/ai_worker.py).

    Returns a result dict with keys: candidate_path, valid, errors.
    """
    staging_root = getattr(args, "staging_dir", os.path.join(AI_DIR, "staging"))
    candidate_path: Optional[str] = None
    # shared candidate variable (typed for static checkers)
    candidate: Dict[str, Any] = {}
    # ensure mod_projects exists for static analyzers and downstream logic
    mod_projects: List[Any] = []
    requirements_md = load_text(os.path.join(AI_DIR, "requirements.md"))
    prompt_template = load_text(os.path.join(AI_DIR, "prompt_templates.md"))
    project_template_path = "/home/martin/Games/TerraInvicta/templates/TIProjectTemplate.json"
    tieffect_path = "/home/martin/Games/TerraInvicta/templates/TIEffectTemplate.json"
    projects = load_project_templates(project_template_path)
    tieffects_map = collect_tieffects(tieffect_path)
    # Prefer an explicit whitelist file to avoid parsing unrelated lines in requirements.md.
    wl_file = os.path.join(AI_DIR, "effect_whitelist.txt")
    if os.path.exists(wl_file):
        whitelist = load_effect_whitelist(wl_file)
    else:
        # fallback for compatibility: parse the requirements.md if no whitelist file present
        whitelist = load_effect_whitelist(os.path.join(AI_DIR, "requirements.md"))

    template, chosen_effect = select_template_and_effect(
        projects,
        tieffects_map,
        whitelist,
        category=cast(Optional[str], getattr(args, "category", None)),
        require_prereq=True,
    )

    def has_prereqs(t: Any) -> bool:
        # protect against t being None or non-dict
        return isinstance(t, dict) and isinstance(t.get("prereqs"), list) and bool(t.get("prereqs"))

    if not has_prereqs(template):
        max_template_attempts = 10
        found = False
        for _ in range(max_template_attempts):
            t, e = select_template_and_effect(
                projects, tieffects_map, whitelist, category=cast(Optional[str], getattr(args, "category", None)), require_prereq=True
            )
            if has_prereqs(t):
                template, chosen_effect = t, e
                found = True
                break
        if not found:
            try:
                logpath = os.path.join(AI_DIR, "generation_issues.log")
                with open(logpath, "a", encoding="utf-8") as lf:
                    lf.write(
                        f"{datetime.now(timezone.utc).isoformat()} - failed to find template with prereqs after {max_template_attempts} attempts; proceeding with fallback template {template.get('dataName')!r}\n"
                    )
            except Exception:
                pass
            print(
                "WARNING: no template with prereqs found after multiple attempts; proceeding with current template",
                file=sys.stderr,
            )

    existing_data_names = set()
    for p in projects:
        if isinstance(p, dict) and "dataName" in p:
            existing_data_names.add(p["dataName"])
    mods_path = os.path.join(ROOT, "Mods", "TIProjectTemplate.json")
    if os.path.exists(mods_path):
        mod_projects = load_project_templates(mods_path)
        for mp in mod_projects:
            if isinstance(mp, dict) and "dataName" in mp:
                existing_data_names.add(mp["dataName"])
        # include user Mods/TIProjectTemplate.json projects when estimating base costs
        try:
            # avoid duplicating entries by dataName
            mod_map = {mp.get("dataName"): mp for mp in mod_projects if isinstance(mp, dict) and mp.get("dataName")}
            projects = [p for p in projects if not (isinstance(p, dict) and p.get("dataName") in mod_map)] + list(mod_map.values())
        except Exception:
            pass

    # ensure mod_projects variable exists for later use
    if 'mod_projects' not in locals():
        mod_projects = []

    if template is None:
        prompt = build_prompt(requirements_md, prompt_template)
        print("Calling model", args.model)
        try:
            probe_wait = getattr(args, "probe_wait", 6.0)
            retry_sleep_base = getattr(args, "retry_sleep_base", 0.25)
            out, candidate = generate_and_extract(
                args.model,
                prompt,
                temperature=args.temperature,
                ollama_url=getattr(args, "ollama_url", None),
                attempts=2,
                simplified_prompt=None,
                ai_dir=AI_DIR,
                debug=getattr(args, "debug", False),
                probe_wait=probe_wait,
                retry_sleep_base=retry_sleep_base,
            )
        except Exception:
            candidate = {"error": "model output not JSON"}
            out = ""

        # ensure candidate is a dict for downstream processing
        if not isinstance(candidate, dict):
            candidate = {}

        # enforce defaults copied from original script
        # type as dict for static checkers
        candidate = cast(Dict[str, Any], candidate)
        candidate.setdefault("AI_techRole", "None")
        candidate.setdefault("AI_criticalTech", False)
        candidate.setdefault("AI_projectRole", "SpaceResources")
        candidate.setdefault("oneTimeGlobally", False)
        candidate.setdefault("repeatable", False)
        candidate.setdefault("resourcesGranted", [])
        candidate.setdefault("factionAvailableChance", random.randint(20, 100))
        if "initialUnlockChance" not in candidate:
            candidate["initialUnlockChance"] = random.randint(1, 20)
        if "deltaUnlockChance" not in candidate:
            candidate["deltaUnlockChance"] = random.randint(1, 10)
        candidate.setdefault("maxUnlockChance", random.randint(20, 100))

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
        }
        candidate_path = write_staged(candidate, staging_root, raw_output=out, meta=meta)
        result = {"candidate_path": candidate_path, "valid": ok, "errors": errors}
        # candidate_path returned by write_staged is a str; guard in case of unexpected None
        if candidate_path is not None:
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
        # prune staging/backups/debug files to keep disk usage bounded
        try:
            from utils.ai_worker_helpers import prune_dir, prune_debug_log

            prune_dir(staging_root, keep=200)
            prune_dir(args.backup_dir, keep=200)
            prune_debug_log(os.path.join(AI_DIR, "debug_logs.txt"), keep_blocks=200)
        except Exception:
            try:
                from scripts.utils.ai_worker_helpers import prune_dir, prune_debug_log

                prune_dir(staging_root, keep=200)
                prune_dir(args.backup_dir, keep=200)
                prune_debug_log(os.path.join(AI_DIR, "debug_logs.txt"), keep_blocks=200)
            except Exception:
                pass
        return result

    # template must be non-None here (we returned earlier if it was); assert for static checkers
    assert template is not None
    # Estimate a base cost informed by existing projects/effects, then roll
    try:
        base_est = estimate_base_cost(template, chosen_effect, projects)
    except Exception:
        base_est = cast(Any, template).get("researchCost", cast(Any, template).get("cost", 1000))
    target_cost = roll_research_cost(base_est)
    attempts = max(1, getattr(args, "attempts", 3))
    last_errors: List[str] = []
    promotion_count = 0
    final_candidate: Optional[Dict[str, Any]] = None
    final_ok = False
    final_meta: Optional[Dict[str, Any]] = None
    for attempt in range(attempts):
        small_prompt = build_fill_prompt(template, chosen_effect, target_cost)
        try:
            # use a simplified strict prompt as a fallback to improve JSON extraction
            from utils.ai_prompts import build_simplified_fill_prompt

            simplified = build_simplified_fill_prompt(chosen_effect, target_cost)
        except Exception:
            from scripts.utils.ai_prompts import build_simplified_fill_prompt

            simplified = build_simplified_fill_prompt(chosen_effect, target_cost)

        try:
            # pass probe_wait and retry_sleep_base from CLI args if provided
            probe_wait = getattr(args, "probe_wait", 6.0)
            retry_sleep_base = getattr(args, "retry_sleep_base", 0.25)
            out, small = generate_and_extract(
                args.model,
                small_prompt,
                temperature=args.temperature,
                ollama_url=getattr(args, "ollama_url", None),
                attempts=2,
                simplified_prompt=simplified,
                ai_dir=AI_DIR,
                debug=getattr(args, "debug", False),
                probe_wait=probe_wait,
                retry_sleep_base=retry_sleep_base,
            )
        except Exception:
            small = {"error": "model output not JSON"}
            out = ""

        # ensure candidate is typed as a dict[str, Any] for downstream setdefault calls
        candidate = {}
        candidate = cast(Dict[str, Any], candidate)
        fname = small.get("friendlyName") if isinstance(small, dict) else None
        if not fname or not isinstance(fname, str):
            last_errors.append("model did not return a valid friendlyName")
            continue
        data_name = "Project_" + "".join([c if c.isalnum() else "_" for c in fname.replace(" ", "_")])
        if data_name in existing_data_names:
            # attempt to find the base project by friendlyName and create a leveled
            # candidate (II..V) instead of re-calling the model. This follows
            # docs/add_projects_with_levels.md behavior.
            try:
                base = find_project_by_friendlyname(projects + mod_projects, fname)
            except Exception:
                base = None
            if base is not None:
                # determine next available level (cap at V)
                base_dn = base.get("dataName") or ""
                lvl = next_level_for_base(base_dn, projects + mod_projects, cap=5)
                if lvl is None:
                    last_errors.append(f"max level reached for base project: {base.get('dataName')}")
                    continue
                # build derived candidate and write staged file
                try:
                    derived = build_leveled_candidate(base, lvl, model_rolls=None, tieffects_map=tieffects_map)
                    # meta should record derivation
                    meta = {
                        "derived_from": base.get("dataName"),
                        "derived_level": lvl,
                        "original_friendlyName": fname,
                        "model": args.model,
                    }
                    candidate_path = write_staged(derived, staging_root, raw_output=out, meta=meta)
                    result = {"candidate_path": candidate_path, "valid": True, "errors": []}
                    print("Wrote staged candidate (derived level) to", candidate_path)
                    if args.backup_dir:
                        try:
                            b = backup_staged(staging_root, args.backup_dir)
                            print("Backed up staging to", b)
                        except Exception as e:
                            print("Backup failed:", e)
                    return result
                except Exception as e:
                    last_errors.append(f"failed to build derived candidate: {e}")
                    continue
            else:
                last_errors.append(f"dataName already exists: {data_name}")
                continue
        candidate["dataName"] = data_name
        candidate["friendlyName"] = fname
        candidate["techCategory"] = template.get("techCategory", "Unknown")
        candidate["researchCost"] = target_cost
        prereqs = []
        prereq_blacklist = {
            "Project_Exotics",
            "Project_SaltWaterCoreReactorI",
            "Project_TheirSignatures",
            "Project_PlatformCore",
            "Project_SolarCollector",
            "Project_Liquid-FuelRockets",
            "Project_InertialConfinementFusionReactorI",
        }
        tpl_prereqs = template.get("prereqs") if isinstance(template.get("prereqs"), list) else []
        if tpl_prereqs:
            for _ in range(10):
                cand = random.choice(tpl_prereqs)
                if cand not in prereq_blacklist:
                    prereqs = [cand]
                    break
            if not prereqs:
                try:
                    logpath = os.path.join(AI_DIR, "generation_issues.log")
                    with open(logpath, "a", encoding="utf-8") as lf:
                        lf.write(
                            f"{datetime.now(timezone.utc).isoformat()} - all template.prereqs blacklisted for template={template.get('dataName')!r}; tpl_prereqs={tpl_prereqs!r}\n"
                        )
                except Exception:
                    pass
                prereqs = [random.choice(tpl_prereqs)]
        candidate["prereqs"] = prereqs
        if not candidate["prereqs"]:
            try:
                logpath = os.path.join(AI_DIR, "generation_issues.log")
                with open(logpath, "a", encoding="utf-8") as lf:
                    lf.write(
                        f"{datetime.now(timezone.utc).isoformat()} - empty prereqs for template: {template.get('dataName')!r} template_prereqs={template.get('prereqs')!r}\n"
                    )
            except Exception:
                pass
            print(f"WARNING: generated candidate with empty prereqs (template={template.get('dataName')})", file=sys.stderr)

        candidate["effects"] = [chosen_effect] if chosen_effect else []
        candidate.setdefault("AI_techRole", "None")
        candidate.setdefault("AI_criticalTech", False)
        candidate.setdefault("AI_projectRole", "SpaceResources")
        candidate.setdefault("oneTimeGlobally", False)
        candidate.setdefault("repeatable", False)
        candidate.setdefault("resourcesGranted", [])
        candidate.setdefault("factionAvailableChance", random.randint(20, 100))
        if "initialUnlockChance" not in candidate:
            candidate["initialUnlockChance"] = random.randint(1, 20)
        if "deltaUnlockChance" not in candidate:
            candidate["deltaUnlockChance"] = random.randint(1, 10)
        candidate.setdefault("maxUnlockChance", random.randint(20, 100))

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
        candidate_path = write_staged(candidate, staging_root, raw_output=out, meta=meta)
        result = {"candidate_path": candidate_path, "valid": ok, "errors": errors}
        if candidate_path is not None:
            with open(candidate_path + ".result.json", "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
        # if the candidate we wrote included effect upgrades, mirror them into the meta file
        try:
            candidate_full = None
            with open(candidate_path, "r", encoding="utf-8") as cf:
                candidate_full = json.load(cf)
            upgrades = candidate_full.get("__derived_effect_upgrades") if isinstance(candidate_full, dict) else None
            if upgrades:
                meta_path = candidate_path + ".meta.json"
                try:
                    if os.path.exists(meta_path):
                        with open(meta_path, "r", encoding="utf-8") as mf:
                            m = json.load(mf)
                    else:
                        m = {}
                    m["derived_effect_upgrades"] = upgrades
                    with open(meta_path, "w", encoding="utf-8") as mf:
                        json.dump(m, mf, indent=2)
                except Exception:
                    pass
        except Exception:
            pass
        print("Wrote staged candidate to", candidate_path)
        if ok:
            final_candidate = candidate
            final_ok = True
            final_meta = meta
            # count promotions if present in the staged file
            try:
                cp = candidate_path
                if cp and os.path.exists(cp):
                    with open(cp, "r", encoding="utf-8") as cf:
                        cfj = json.load(cf)
                    ups = cfj.get("__derived_effect_upgrades") if isinstance(cfj, dict) else None
                    if ups and isinstance(ups, list):
                        promotion_count += len(ups)
            except Exception:
                pass
            break
        else:
            last_errors.extend(errors)

    if args.backup_dir:
        try:
            b = backup_staged(staging_root, args.backup_dir)
            print("Backed up staging to", b)
        except Exception as e:
            print("Backup failed:", e)
    # prune staging/backups/debug files to keep disk usage bounded
    try:
        from utils.ai_worker_helpers import prune_dir, prune_debug_log

        prune_dir(staging_root, keep=200)
        prune_dir(args.backup_dir, keep=200)
        prune_debug_log(os.path.join(AI_DIR, "debug_logs.txt"), keep_blocks=200)
    except Exception:
        try:
            from scripts.utils.ai_worker_helpers import prune_dir, prune_debug_log

            prune_dir(staging_root, keep=200)
            prune_dir(args.backup_dir, keep=200)
            prune_debug_log(os.path.join(AI_DIR, "debug_logs.txt"), keep_blocks=200)
        except Exception:
            pass

    if final_ok:
        # final_candidate is set when final_ok is True; help static analyzers by asserting it here
        assert final_candidate is not None
        # candidate_path should be set when final_ok is True (we wrote staged file earlier)
        assert candidate_path is not None
        fc = final_candidate
        cp = cast(str, candidate_path)
        if getattr(args, "generate_localization", False):
            loc_ok = False
            loc_errors = []
            for la in range(max(1, getattr(args, "loc_attempts", 3))):
                # use the asserted non-None final candidate variable
                loc_prompt = build_localization_prompt(fc, tieffects_map)
                try:
                    # build a tiny fallback simplified prompt for localization
                    try:
                        from utils.ai_prompts import build_simplified_localization_prompt

                        simplified_loc = build_simplified_localization_prompt()
                    except Exception:
                        from scripts.utils.ai_prompts import build_simplified_localization_prompt

                        simplified_loc = build_simplified_localization_prompt()

                    loc_out, loc_obj = generate_and_extract(
                        args.model,
                        loc_prompt,
                        temperature=args.temperature,
                        ollama_url=getattr(args, "ollama_url", None),
                        attempts=1,
                        simplified_prompt=simplified_loc,
                        ai_dir=AI_DIR,
                        debug=getattr(args, "debug", False),
                        probe_wait=getattr(args, "probe_wait", 6.0),
                        retry_sleep_base=getattr(args, "retry_sleep_base", 0.25),
                    )
                except Exception:
                    loc_obj = {"error": "model output not JSON"}
                    loc_out = ""

                if isinstance(loc_obj, dict) and "shortDescription" in loc_obj and isinstance(loc_obj["shortDescription"], str):
                    loc_lines = []
                    # final_candidate guaranteed non-None by the earlier assert (use fc)
                    dn = fc.get("dataName")
                    fn = fc.get("friendlyName")
                    loc_lines.append(f"TIProjectTemplate.displayName.{dn}={fn}")
                    loc_lines.append(f"TIProjectTemplate.summary.{dn}={loc_obj['shortDescription']}")
                    loc_dest = os.path.join(os.path.dirname(cp), "localization.txt")
                    with open(loc_dest, "w", encoding="utf-8") as lf:
                        lf.write("\n".join(loc_lines) + "\n")
                    loc_ok = True
                    break
                else:
                    loc_errors.append(str(loc_obj))

            try:
                meta_path = cp + ".meta.json"
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

        if getattr(args, "dry_run", False) and getattr(args, "print_output", False):
            try:
                to_print = final_candidate if final_candidate else candidate
                print("\n--- Generated candidate (staged) ---")
                print(json.dumps(to_print, indent=2, ensure_ascii=False))
                loc_path = os.path.join(os.path.dirname(cp), "localization.txt")
                if os.path.exists(loc_path):
                    print("\n--- Localization ---")
                    with open(loc_path, "r", encoding="utf-8") as lf:
                        print(lf.read().strip())
            except Exception:
                pass

        if getattr(args, "auto_apply", False):
            if getattr(args, "dry_run", False):
                print("Auto-apply requested but skipped because --dry-run is set.")
            else:
                # ensure final_candidate is present before attempting to apply
                assert final_candidate is not None
                mods_path = os.path.join(ROOT, "Mods", "TIProjectTemplate.json")
                mods_loc_path = os.path.join(ROOT, "Mods", "Localization", "en", "TIProjectTemplate.en")
                loc_staging = os.path.join(os.path.dirname(cp), "localization.txt")
                if os.path.exists(loc_staging):
                    try:
                        with open(loc_staging, "r", encoding="utf-8") as lf:
                            loc_text = lf.read()
                    except Exception:
                        loc_text = ""
                else:
                    # use fc (final candidate) which is asserted non-None
                    dn = fc.get("dataName")
                    fn = fc.get("friendlyName")
                    loc_text = f"TIProjectTemplate.displayName.{dn}={fn}\nTIProjectTemplate.summary.{dn}=\n"
                ok, apply_errors = apply_candidate_to_mods(final_candidate, loc_text, mods_path, mods_loc_path, args.backup_dir)
                if ok:
                    print("Auto-applied candidate to Mods and localization (backups created).")
                else:
                    print("Auto-apply failed:", apply_errors)
        return {"candidate_path": candidate_path, "valid": True, "errors": []}
    # report promotion_count in the non-success case as well via result errors/log
    if promotion_count > 0:
        last_errors.append(f"promotions_detected={promotion_count}")
    return {"candidate_path": candidate_path if not final_candidate else None, "valid": False, "errors": last_errors}
