"""
Phase 2: Fetch detailed info and write to detail CSV.
"""
import asyncio
import logging
from typing import List, Dict, Any
from collections import defaultdict

from curl_cffi import AsyncSession

from v4.types import CityName, ClubRow, StatsDict, ClubCache
from v4.models import AdaptiveLimiter
from v4.config import MAX_CONCURRENT_REQUESTS, MAX_CONCURRENT_LIMIT
from v4.api import fetch_club_info
from v4.storage import async_append_csv_rows_safe, load_clubs_basic_by_combo

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
    max_booking_urls: int = 0
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

    # Group by ClubId to get ALL entries for each club (including duplicates with different BookingURLs)
    clubs_by_id: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for club in clubs_from_csv:
        club_id = club.get("ClubId", "")
        if club_id is not None and club_id != "":
            clubs_by_id[club_id].append(club)

    # Use unique club_ids for processing (deduplicate club_ids_to_fetch_detail)
    unique_club_ids = list(dict.fromkeys(club_ids_to_fetch_detail))
    total_clubs = len(unique_club_ids)

    if total_clubs > 0:
        logger.info(f"[{city}] Phase 2: Starting detailed fetch for {total_clubs} unique clubs")

    limiter = AdaptiveLimiter(MAX_CONCURRENT_REQUESTS, min_concurrent=5, max_concurrent=MAX_CONCURRENT_LIMIT)

    if dry_run:
        client = None
    else:
        client = AsyncSession(impersonate="chrome120", timeout=300.0)

    try:
        if client:
            async with client:
                tasks = []
                for idx, club_id in enumerate(unique_club_ids, 1):
                    # Get ALL recommendation data entries for this club_id from CSV
                    club_data_list = clubs_by_id.get(club_id, [])
                    # if not club_data_list:
                    #     logger.warning(f"[{city}] Phase 2: No basic data found for ClubId={club_id}, skipping")
                    #     continue

                    # Use first entry for latitude, longitude, etc.
                    first_club_data = club_data_list[0]
                    pct = idx / total_clubs * 100
                    logger.info(f"[{city}] Phase 2: Processing club {idx}/{total_clubs} ({pct:.1f}%) (ClubId={club_id}, {len(club_data_list)} entries)")
                    tasks.append(
                        fetch_club_info(
                            client, club_id, 0, play_with, city, limiter, stats, club_cache, dry_run,
                            latitude=first_club_data.get("Latitude", 51.5074),
                            longitude=first_club_data.get("Longitude", -0.1278),
                            week_days=first_club_data.get("WeekDays", "1,2,3,4,5,6,7"),
                            disability_option=first_club_data.get("Disabilityoption", 3),
                            disability_type=first_club_data.get("DisabilityType", []),
                            school_year=first_club_data.get("SchoolYear", ""),
                            football_type=first_club_data.get("FootballType", "U10"),
                            search_id=first_club_data.get("SearchId", None),
                            # Pass ALL recommendation data entries for this club to scrape ALL booking URLs
                            recommendation_data_list=club_data_list,
                            max_booking_urls=max_booking_urls
                        )
                    )
                raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            # Dry run - client is None, fetch_club_info handles this internally
            tasks = []
            for idx, club_id in enumerate(unique_club_ids, 1):
                club_data_list = clubs_by_id.get(club_id, [])
                if not club_data_list:
                    logger.warning(f"[{city}] Phase 2: No basic data found for ClubId={club_id}, skipping")
                    continue

                first_club_data = club_data_list[0]
                pct = idx / total_clubs * 100
                logger.info(f"[{city}] Phase 2: Processing club {idx}/{total_clubs} ({pct:.1f}%) (ClubId={club_id}, {len(club_data_list)} entries)")
                tasks.append(
                    fetch_club_info(
                        client, club_id, 0, play_with, city, limiter, stats, club_cache, dry_run,
                        latitude=first_club_data.get("Latitude", 51.5074),
                        longitude=first_club_data.get("Longitude", -0.1278),
                        week_days=first_club_data.get("WeekDays", "1,2,3,4,5,6,7"),
                        disability_option=first_club_data.get("Disabilityoption", 3),
                        disability_type=first_club_data.get("DisabilityType", []),
                        school_year=first_club_data.get("SchoolYear", ""),
                        football_type=first_club_data.get("FootballType", "U10"),
                        search_id=first_club_data.get("SearchId", None),
                        # Pass ALL recommendation data entries for this club to scrape ALL booking URLs
                        recommendation_data_list=club_data_list,
                        max_booking_urls=max_booking_urls
                    )
                )
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in raw_results:
            if isinstance(r, dict):
                rows_to_save.append(r)

    finally:
        # Close client if it was created (only for non-dry-run)
        if client:
            await client.close()

    return rows_to_save