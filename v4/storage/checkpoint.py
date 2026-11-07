"""
Checkpoint utilities for v4 crawler: save/load checkpoints for resume capability.
"""
from typing import Tuple

from v4.config import CACHE_FILE, PROCESSED_FILE
from v4.storage.pickle_utils import safe_load_pickle, atomic_pickle_dump
from v4.types import ClubCache, ProcessedCombos


def save_checkpoint(club_cache: ClubCache, processed_combos: ProcessedCombos) -> None:
    """Save checkpoint for resume capability."""
    atomic_pickle_dump(club_cache, CACHE_FILE)
    atomic_pickle_dump(processed_combos, PROCESSED_FILE)


def load_checkpoint() -> Tuple[ClubCache, ProcessedCombos]:
    """Load checkpoint for resume capability."""
    club_cache = safe_load_pickle(CACHE_FILE, {})
    processed_combos = safe_load_pickle(PROCESSED_FILE, set())
    return club_cache, processed_combos