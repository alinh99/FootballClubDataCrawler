"""
Phase 2: Fetch detailed info and write to detail CSV.
"""
import asyncio
import logging
from typing import List, Dict, Any, Set
from collections import defaultdict
import json
import os

from curl_cffi import AsyncSession

from v4.types import CityName, ClubRow, StatsDict, ClubCache
from v4.models import AdaptiveLimiter
from v4.config import MAX_CONCURRENT_REQUESTS, MAX_CONCURRENT_LIMIT
from v4.api import fetch_club_info
from v4.storage import async_append_csv_rows_safe, load_clubs_basic_by_combo
from v4.eta import PhaseETACalculator, ETACalculator

logger = logging.getLogger(__name__)


async def process_phase2(
    city: CityName,
    age: int,
    play_with: int,
    clubs_data: List[Dict[str, Any]],  # unused, kept for backward compatibility
    club_ids_to_fetch_detail: List[str],
    stats: StatsDict,
    club_cache: ClubCache,
    dry_run: bool = False,
    max_booking_urls: int = 0,
    raise_on_fetch_error: bool = False
) -> List[ClubRow]:
    """
    Phase 2: Fetch detailed info and write to detail CSV.

    Reads clubs from clubs_basic.csv (written by Phase 1) filtered by city, age, play_with.
    Scrapes ALL booking URLs for each club (same club may appear multiple times in basic CSV).
    Only duplicate check on ClubId at the end.
    """
    rows_to_save: List[ClubRow] = []

    # Load ALL clubs from clubs_basic.csv for this combo
    clubs_from_csv = load_clubs_basic_by_combo(city, age, play_with)
    if not clubs_from_csv:
        logger.warning(f"[{city}] Phase 2: No clubs found in clubs_basic.csv for Age={age}, PlayWith={play_with}")
        return rows_to_save

    # Process ALL entries from basic CSV without ClubId deduplication
    # Each row in clubs_basic.csv will trigger a detail fetch
    clubs_to_process = [club for club in clubs_from_csv]
    total_clubs = len(clubs_to_process)

    # Helper to safely extract values (handle NaN/float from pandas/CSV)
    import math
    def safe_get_str(data_dict, key, default=""):
        val = data_dict.get(key, default)
        if val is None:
            return default
        if isinstance(val, float) and math.isnan(val):
            return default
        return str(val).strip()

    def safe_get_float(data_dict, key, default=0.0):
        val = data_dict.get(key, default)
        if val is None:
            return default
        if isinstance(val, float) and math.isnan(val):
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def safe_get_int(data_dict, key, default=0):
        val = data_dict.get(key, default)
        if val is None:
            return default
        if isinstance(val, float) and math.isnan(val):
            return default
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    # Load already crawled clubs from checkpoint (new_checkpoint.json) for skip logic
    crawled_club_names: Set[str] = set()
    crawled_booking_urls: Set[str] = set()
    checkpoint_path = "storage/new_checkpoint.json"
    if os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, 'r', encoding='utf-8') as f:
                checkpoint = json.load(f)
            club_cache_list = checkpoint.get("club_cache", [])
            for entry in club_cache_list:
                club_name = entry.get("Club Name", "").strip()
                if club_name:
                    crawled_club_names.add(club_name)
                booking_venue = entry.get("BookingVenue", "").strip()
                if booking_venue:
                    crawled_booking_urls.add(booking_venue)
                booking_address = entry.get("BookingAddress", "").strip()
                if booking_address:
                    crawled_booking_urls.add(booking_address)
                booking_url = entry.get("BookingURL", "").strip()
                if booking_url:
                    crawled_booking_urls.add(booking_url)
            logger.info(f"[{city}] Phase 2: Loaded {len(crawled_club_names)} crawled club names and {len(crawled_booking_urls)} crawled booking URLs from checkpoint")
        except Exception as e:
            logger.warning(f"[{city}] Phase 2: Failed to load checkpoint for skip logic: {e}")
    else:
        logger.info(f"[{city}] Phase 2: No checkpoint found at {checkpoint_path}, skipping crawl check")

    # Calculate total booking URLs across all clubs for shared ETA
    total_booking_urls = 0
    for club in clubs_to_process:
        booking_url = safe_get_str(club, "BookingURL") or safe_get_str(club, "BookingUrl") or ""
        if booking_url:
            total_booking_urls += 1
    # Apply max_booking_urls limit if set
    if max_booking_urls > 0:
        total_booking_urls = min(total_booking_urls, max_booking_urls * total_clubs)

    # Phase 2 ETA calculator (for clubs)
    phase2_eta = PhaseETACalculator(total_combos=1)
    phase2_eta.start_phase2(total_clubs)

    # Shared ETA calculator for booking URLs across all clubs
    booking_eta = ETACalculator(total_booking_urls, "booking URLs") if total_booking_urls > 0 else None
    if booking_eta:
        logger.info(f"[{city}] Phase 2: Starting booking URL scraping for {total_booking_urls} URLs across {total_clubs} clubs")

    if total_clubs > 0:
        logger.info(f"[{city}] Phase 2: Starting detailed fetch for {total_clubs} clubs (no dedup)")

    limiter = AdaptiveLimiter(MAX_CONCURRENT_REQUESTS, min_concurrent=5, max_concurrent=MAX_CONCURRENT_LIMIT)

    if dry_run:
        client = None
    else:
        client = AsyncSession(impersonate="chrome120", timeout=300.0)

    try:
        if client:
            async with client:
                tasks = []
                for idx, club in enumerate(clubs_to_process, 1):
                    club_id = safe_get_str(club, "ClubId", "")
                    # Use club data for latitude, longitude, etc.
                    first_club_data = club
                    pct = idx / total_clubs * 100
                    logger.info(f"[{city}] Phase 2: Processing club {idx}/{total_clubs} ({pct:.1f}%) (ClubId={club_id})")
                    tasks.append(
                        fetch_club_info(
                            client, club_id, 0, play_with, city, limiter, stats, club_cache, dry_run,
                            latitude=safe_get_float(first_club_data, "Latitude", 51.5074),
                            longitude=safe_get_float(first_club_data, "Longitude", -0.1278),
                            week_days=safe_get_str(first_club_data, "WeekDays", "1,2,3,4,5,6,7"),
                            disability_option=safe_get_int(first_club_data, "Disabilityoption", 3),
                            disability_type=first_club_data.get("DisabilityType", []),
                            school_year=safe_get_str(first_club_data, "SchoolYear", ""),
                            football_type=safe_get_str(first_club_data, "FootballType", "U10"),
                            search_id=safe_get_str(first_club_data, "SearchId", None),
                            # Pass recommendation data for this club to scrape ALL booking URLs
                            recommendation_data_list=[first_club_data],
                            max_booking_urls=max_booking_urls,
                            booking_eta=booking_eta,
                            crawled_club_names=crawled_club_names,
                            crawled_booking_urls=crawled_booking_urls
                        )
                    )
                raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            # Dry run - client is None, fetch_club_info handles this internally
            tasks = []
            for idx, club in enumerate(clubs_to_process, 1):
                club_id = safe_get_str(club, "ClubId", "")
                pct = idx / total_clubs * 100
                logger.info(f"[{city}] Phase 2: Processing club {idx}/{total_clubs} ({pct:.1f}%) (ClubId={club_id})")
                tasks.append(
                    fetch_club_info(
                        client, club_id, 0, play_with, city, limiter, stats, club_cache, dry_run,
                        latitude=safe_get_float(club, "Latitude", 51.5074),
                        longitude=safe_get_float(club, "Longitude", -0.1278),
                        week_days=safe_get_str(club, "WeekDays", "1,2,3,4,5,6,7"),
                        disability_option=safe_get_int(club, "Disabilityoption", 3),
                        disability_type=club.get("DisabilityType", []),
                        school_year=safe_get_str(club, "SchoolYear", ""),
                        football_type=safe_get_str(club, "FootballType", "U10"),
                        search_id=safe_get_str(club, "SearchId", None),
                        # Pass recommendation data for this club to scrape ALL booking URLs
                        recommendation_data_list=[club],
                        max_booking_urls=max_booking_urls,
                        booking_eta=booking_eta,
                        crawled_club_names=crawled_club_names,
                        crawled_booking_urls=crawled_booking_urls
                    )
                )
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Update Phase 2 ETA progress
        successful_results = [r for r in raw_results if isinstance(r, dict)]
        phase2_eta.update_phase2(len(successful_results))
        phase2_eta.log_phase2(logger, city, force=True)

        failures = [result for result in raw_results if isinstance(result, Exception)]
        if failures:
            if raise_on_fetch_error:
                # Retrying callers must not treat partial results as a completed combo.
                raise RuntimeError(
                    f"Phase 2 failed for {len(failures)} club fetch(es) in {city}"
                ) from failures[0]
            logger.error(
                f"[{city}] Phase 2: {len(failures)} club fetch(es) failed; "
                "returning successful club rows"
            )

        # Non-retrying callers still receive successful rows when another club
        # fetch fails, rather than losing the entire combo's successful results.
        rows_to_save.extend(result for result in raw_results if isinstance(result, dict))

    finally:
        # Close client if it was created (only for non-dry-run)
        if client:
            await client.close()

    return rows_to_save