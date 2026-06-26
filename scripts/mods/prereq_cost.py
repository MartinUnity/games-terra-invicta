"""Calculate total prereq cost for projects/techs and suggest prereq chains."""
from __future__ import annotations

import argparse
import json
import sys
from itertools import chain
from pathlib import Path

# Directories (scripts/mods/ -> workspace root)
_WORKSPACE = Path(__file__).resolve().parent.parent.parent
MODS_DIR = _WORKSPACE / "Mods"
GAME_DIR = _WORKSPACE / "Game-ModsDir"


def load_templates(directory: Path, ext: str = ".json") -> dict[str, dict]:
    """Load all project/tech templates from a directory."""
    result: dict[str, dict] = {}
    for fp in chain(directory.glob("*ProjectTemplate.json"), directory.glob("*TechTemplate.json")):
        try:
            with fp.open("r", encoding="utf-8") as f:
                items = json.load(f)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "dataName" in item:
                        result[item["dataName"]] = item
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return result


def build_registry() -> dict[str, dict]:
    """Merge mod and game templates (mod takes priority)."""
    registry: dict[str, dict] = {}
    registry.update(load_templates(GAME_DIR))
    registry.update(load_templates(MODS_DIR))
    return registry


def get_all_prereqs(name: str, registry: dict[str, dict], visited: set[str] | None = None) -> set[str]:
    """Recursively collect all transitive prereqs (including altPrereq*)."""
    if visited is None:
        visited = set()
    if name in visited:
        return set()
    visited.add(name)
    item = registry.get(name)
    if not item:
        return set()
    prereqs: set[str] = set()
    for p in item.get("prereqs", []):
        prereqs.add(p)
        prereqs.update(get_all_prereqs(p, registry, visited))
    for k, v in item.items():
        if k.startswith("altPrereq") and isinstance(v, str):
            prereqs.add(v)
            prereqs.update(get_all_prereqs(v, registry, visited))
    return prereqs


def calc_cost(name: str, registry: dict[str, dict]) -> tuple[int, list[tuple[str, int]]]:
    """Calculate total prereq cost. Returns (total_cost, [(name, cost), ...])."""
    prereqs = get_all_prereqs(name, registry)
    items: list[tuple[str, int]] = []
    total = 0
    for p in sorted(prereqs):
        item = registry.get(p)
        if item:
            cost = item.get("researchCost", 0)
            total += cost
            items.append((p, cost))
    self_item = registry.get(name)
    self_cost = self_item.get("researchCost", 0) if self_item else 0
    items.insert(0, (f"{name} (self)", self_cost))
    total += self_cost
    return total, items


def cmd_cost(args: argparse.Namespace, registry: dict[str, dict]) -> None:
    """Show total prereq cost for a given project/tech."""
    name = args.name
    if name not in registry:
        # Try fuzzy match
        candidates = [k for k in registry if name.lower() in k.lower()]
        if candidates:
            print(f"Exact match not found. Did you mean one of:")
            for c in candidates[:5]:
                print(f"  {c}")
        else:
            print(f"Error: '{name}' not found in any template.")
        sys.exit(1)

    total, items = calc_cost(name, registry)
    item = registry[name]
    cat = item.get("techCategory", "N/A")
    print(f"Project:   {item.get('friendlyName', name)}")
    print(f"Category:  {cat}")
    print(f"Self cost: {item.get('researchCost', 0)}")
    print(f"Prereqs:   {len(get_all_prereqs(name, registry))} transitive")
    print(f"Total cost: {total}")
    if args.verbose:
        print()
        print(f"  {'Component':<50} {'Cost':>8}")
        print(f"  {'-'*50} {'-'*8}")
        for comp, cost in items:
            print(f"  {comp:<50} {cost:>8,}")
        print(f"  {'-'*50} {'-'*8}")
        print(f"  {'TOTAL':<50} {total:>8,}")


def cmd_compare(args: argparse.Namespace, registry: dict[str, dict]) -> None:
    """Compare total prereq costs of two or more projects/techs."""
    print(f"  {'Project':<50} {'Self':>8} {'Total':>10} {'Ratio':>8}")
    print(f"  {'-'*50} {'-'*8} {'-'*10} {'-'*8}")
    totals: list[tuple[str, int, int]] = []
    for name in args.names:
        if name not in registry:
            print(f"  Warning: '{name}' not found, skipping.")
            continue
        total, items = calc_cost(name, registry)
        self_cost = registry[name].get("researchCost", 0)
        totals.append((name, self_cost, total))
        print(f"  {name:<50} {self_cost:>8,} {total:>10,} {'--':>8}")

    # Add ratios relative to the minimum
    if totals:
        min_total = min(t for _, _, t in totals)
        print()
        for name, _, total in totals:
            ratio = f"{total / min_total:.1f}x" if min_total > 0 else "--"
            print(f"  {name:<50} ratio: {ratio:>7} of cheapest")


def cmd_suggest(args: argparse.Namespace, registry: dict[str, dict]) -> None:
    """Suggest additional prereqs to reach a target total cost."""
    name = args.name
    if name not in registry:
        print(f"Error: '{name}' not found in any template.")
        sys.exit(1)

    current_total, _ = calc_cost(name, registry)
    existing_prereqs = get_all_prereqs(name, registry) | {name}
    target = args.target

    if current_total >= target:
        print(f"Current total cost ({current_total:,}) already meets target ({target:,}).")
        return

    gap = target - current_total
    print(f"Current cost: {current_total:,}")
    print(f"Target cost:  {target:,}")
    print(f"Gap:          {gap:,}")
    print()

    # Filter candidates: not already in the chain, have a researchCost
    category_filter = args.category
    candidates: list[tuple[str, int, str]] = []
    for k, v in registry.items():
        if k in existing_prereqs:
            continue
        cost = v.get("researchCost", 0)
        if cost <= 0:
            continue
        cat = v.get("techCategory", "")
        if category_filter and cat != category_filter:
            continue
        candidates.append((k, cost, cat))

    if not candidates:
        print("No candidate prereqs found.")
        return

    # Sort by cost descending for greedy fill
    candidates.sort(key=lambda x: x[1], reverse=True)

    # Greedy: pick items that fit, aiming for the target gap
    selected: list[tuple[str, int, str]] = []
    remaining = gap
    for k, cost, cat in candidates:
        if cost <= remaining and remaining > 0:
            selected.append((k, cost, cat))
            remaining -= cost
        if remaining <= 0:
            break

    if not selected:
        # If greedy found nothing (all items too large), pick the best single fit
        best = [(k, c, cat) for k, c, cat in candidates if c <= gap]
        if best:
            selected = best[:1]
            remaining = gap - selected[0][1]
        else:
            print("No prereqs small enough to fit the gap. Consider a lower target.")
            return

    selected_cost = sum(c for _, c, _ in selected)
    new_total = current_total + selected_cost

    print(f"Suggested additions ({len(selected)} items, cost {selected_cost:,}):")
    print(f"  {'Component':<50} {'Cost':>8} {'Category':<20}")
    print(f"  {'-'*50} {'-'*8} {'-'*20}")
    for k, cost, cat in selected:
        print(f"  {k:<50} {cost:>8,} {cat:<20}")
    print(f"  {'-'*50} {'-'*8}")
    print(f"  {'New total':<50} {new_total:>8,}")
    print(f"  (Target: {target:,}, over/under: {new_total - target:+,})")

    if args.output_json:
        out = {
            "project": name,
            "current_total": current_total,
            "target": target,
            "suggested_prereqs": [{"dataName": k, "cost": c, "category": cat} for k, c, cat in selected],
            "new_total": new_total,
        }
        print(f"\nJSON output:")
        print(json.dumps(out, indent=2))


def cmd_chain(args: argparse.Namespace, registry: dict[str, dict]) -> None:
    """Show the full prereq chain (direct prereqs only) for a project/tech."""
    name = args.name
    if name not in registry:
        print(f"Error: '{name}' not found in any template.")
        sys.exit(1)

    item = registry[name]
    direct = item.get("prereqs", [])
    alts = {k: v for k, v in item.items() if k.startswith("altPrereq")}
    all_prereqs = get_all_prereqs(name, registry)

    print(f"Project: {item.get('friendlyName', name)}")
    print(f"Direct prereqs ({len(direct)}):")
    for p in direct:
        self_cost = registry.get(p, {}).get("researchCost", 0)
        total, _ = calc_cost(p, registry)
        cat = registry.get(p, {}).get("techCategory", "?")
        print(f"  {p:<50} cost={self_cost:>6,}  total_chain={total:>8,}  [{cat}]")

    if alts:
        print(f"\nAlternate prereqs:")
        for k, v in alts.items():
            self_cost = registry.get(v, {}).get("researchCost", 0)
            total, _ = calc_cost(v, registry)
            cat = registry.get(v, {}).get("techCategory", "?")
            print(f"  {k}={v:<48} cost={self_cost:>6,}  total_chain={total:>8,}  [{cat}]")

    print(f"\nTotal transitive prereqs: {len(all_prereqs)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calculate and compare prereq costs for Terra Invicta projects/techs."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # cost subcommand
    p_cost = sub.add_parser("cost", help="Show total prereq cost for a project/tech")
    p_cost.add_argument("name", help="Project or tech dataName")
    p_cost.add_argument("-v", "--verbose", action="store_true", help="Show breakdown")

    # compare subcommand
    p_comp = sub.add_parser("compare", help="Compare costs of multiple projects/techs")
    p_comp.add_argument("names", nargs="+", help="Project or tech dataNames to compare")

    # suggest subcommand
    p_sug = sub.add_parser("suggest", help="Suggest prereqs to reach a target cost")
    p_sug.add_argument("name", help="Base project/tech dataName")
    p_sug.add_argument("--target", type=int, required=True, help="Target total cost")
    p_sug.add_argument("--category", help="Filter suggestions by techCategory")
    p_sug.add_argument("--output-json", action="store_true", help="Output suggestions as JSON")

    # chain subcommand
    p_chain = sub.add_parser("chain", help="Show direct prereq chain for a project/tech")
    p_chain.add_argument("name", help="Project or tech dataName")

    args = parser.parse_args()
    registry = build_registry()

    commands = {
        "cost": cmd_cost,
        "compare": cmd_compare,
        "suggest": cmd_suggest,
        "chain": cmd_chain,
    }
    commands[args.command](args, registry)


if __name__ == "__main__":
    main()
