"""
Combo building utilities for v4 crawler.
"""
from typing import List, Set, Tuple

from v4.types import CityName


# Age range: 5 to 69 (as specified by user)
AGE_GROUPS = list(range(5, 70))
# PlayWith: 4 = all football types (from website default)
PLAY_WITH_OPTIONS = [4]


def build_pending_combos_for_city(city: CityName, existing_combo_set: Set[str]) -> List[Tuple[int, int]]:
    """
    Build combos for each age 5-69 with PlayWith=4 (all football types).
    Each (age, play_with) combination is a separate API call.
    """
    pending: List[Tuple[int, int]] = []
    for age in AGE_GROUPS:
        for play_with in PLAY_WITH_OPTIONS:
            key = f"{city}__{play_with}__{age}"
            if key not in existing_combo_set:
                pending.append((age, play_with))
    return pending