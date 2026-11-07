"""
Combo building utilities for v4 crawler.
"""
from typing import List, Set, Tuple

from v4.types import CityName


def build_pending_combos_for_city(city: CityName, existing_combo_set: Set[str]) -> List[Tuple[int, int]]:
    """
    API uses Age=0 and PlayWith=4 (from website default payload) - returns all clubs.
    Only one combo per city needed.
    """
    pending: List[Tuple[int, int]] = []
    key = f"{city}__0"  # Single combo per city (age=0, play_with=default)
    if key not in existing_combo_set:
        pending.append((0, 0))  # age=0, play_with=0 (using defaults from payload)
    return pending