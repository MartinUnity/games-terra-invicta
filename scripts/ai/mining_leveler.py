"""Helpers to map researchCost -> mining bonus level suffix (_lvl1.._lvl6).

This module centralizes the thresholds used to pick a _lvlN suffix so the
same rules are used by one-off fixes and by the automatic project generator.
"""
from __future__ import annotations

from typing import Optional

# Thresholds (inclusive upper bounds) for levels 1..6. These match the
# quantile buckets used when the one-off patch was generated.
# level 1: rc <= 650
# level 2: rc <= 2243
# level 3: rc <= 6040
# level 4: rc <= 13206
# level 5: rc <= 22309
# level 6: else
LEVEL_UPPER_BOUNDS = [650, 2243, 6040, 13206, 22309]


def level_for_cost(research_cost: int | float | None) -> int:
    """Return level 1..6 for a research_cost number. Defaults to 3 when cost is missing.

    The function accepts ints or floats; non-numeric or None falls back to level 3
    (middle ground) to avoid biasing new projects too low or too high.
    """
    try:
        if research_cost is None:
            return 3
        rc = float(research_cost)
    except Exception:
        return 3

    for idx, ub in enumerate(LEVEL_UPPER_BOUNDS, start=1):
        if rc <= ub:
            return idx
    return 6


def apply_mining_level_suffix(effect_name: str, research_cost: int | float | None) -> str:
    """If effect_name looks like a mining bonus without a _lvl suffix,
    return the name appended with the appropriate _lvlN suffix based on research_cost.
    Otherwise return effect_name unchanged.
    """
    if not effect_name or not isinstance(effect_name, str):
        return effect_name
    low = effect_name.lower()
    # quick checks to match the grep pipeline used originally
    if "effect_mining" not in low or "bonus" not in low:
        return effect_name
    if "_lvl" in low:
        return effect_name

    lvl = level_for_cost(research_cost)
    return f"{effect_name}_lvl{lvl}"
