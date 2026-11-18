"""
Combo processor for v4 crawler: process a single city combo (age, play_with).
"""
import asyncio
import logging
from typing import List, Tuple, Any

from v4.types import CityName, ClubRow, StatsDict, ClubCache
from v4.api import fetch_recommendation_pages, extract_full_club_data_from_recommendation
from v4.crawler.phase import process_phase1, process_phase2
from v4.storage import close_csv_basic_writer

logger = logging.getLogger(__name__)


async def process_combo_async(
    city: CityName,
    age: int,
    play_with: int,
    stats: StatsDict,
    club_cache: ClubCache,
    dry_run: bool = False,
    limit: int = 0
) -> List[ClubRow]:
    """
    Process a single city combo.
    Phase 1: Write ALL available club info from recommendation API immediately.
    Phase 2: Fetch detailed info and write to detail CSV (for any missing fields).
    """
    combo_key = f"{city}__{play_with}__{age}"
    # Pass limit to recommendation fetcher to stop early when enough clubs collected
    api_general_info_data = await fetch_recommendation_pages(city, dry_run, limit)

    # Extract ALL fields from recommendation API response
    clubs_data = extract_full_club_data_from_recommendation(api_general_info_data)
    if not clubs_data:
        return []

    # ===== PHASE 1: Write ALL available club info from recommendation API immediately =====
    club_ids_to_fetch_detail = await process_phase1(city, age, play_with, clubs_data)

    # Close basic CSV writer to ensure ALL data is flushed to disk before Phase 2 reads it
    await close_csv_basic_writer()

    # ===== PHASE 2: Fetch detailed info and write to detail CSV =====
    # Only fetch detail for clubs that need additional info not in recommendation
    rows_to_save = await process_phase2(
        city, age, play_with, clubs_data, club_ids_to_fetch_detail, stats, club_cache, dry_run
    )
    return rows_to_save