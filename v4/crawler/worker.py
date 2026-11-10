"""
Worker functions for v4 crawler: process cities and combos.
"""
import asyncio
import time
import random
import logging
from tqdm import tqdm
from typing import Any, Dict, List, Set

from multiprocessing.managers import ValueProxy
from multiprocessing.synchronize import Lock as LockProxy

from v4.config import MAX_CONCURRENT_REQUESTS, MAX_CONCURRENT_LIMIT, TOTAL_RETRIES
from v4.models import AdaptiveLimiter
from v4.api import fetch_recommendation_pages, fetch_club_info, extract_full_club_data_from_recommendation
from v4.storage import (
    atomic_pickle_dump, async_append_csv_rows_safe,
    async_append_basic_csv_rows, safe_load_pickle, close_all_csv_writers
)
from v4.types import (
    CityName, ClubRow, BasicClubRow, StatsDict, WorkerArgs, ProcessedCombos
)
from v4.crawler.logging import log_error_with_context

logger = logging.getLogger(__name__)


async def process_combo_async(
    city: CityName,
    stats: StatsDict,
    dry_run: bool = False
) -> List[ClubRow]:
    """
    Process a single city combo (now just one combo per city with defaults).
    Phase 1: Write ALL available club info from recommendation API immediately.
    Phase 2: Fetch detailed info and write to detail CSV (for any missing fields).
    """
    combo_key = f"{city}__0"
    limiter = AdaptiveLimiter(MAX_CONCURRENT_REQUESTS, min_concurrent=5, max_concurrent=MAX_CONCURRENT_LIMIT)
    api_general_info_data = await fetch_recommendation_pages(city, dry_run)

    # Extract ALL fields from recommendation API response
    clubs_data = extract_full_club_data_from_recommendation(api_general_info_data)
    if not clubs_data:
        return []

    # ===== PHASE 1: Write ALL available club info from recommendation API immediately =====
    basic_rows: List[BasicClubRow] = []
    club_ids_to_fetch_detail: List[str] = []

    for club_data in clubs_data:
        club_id = club_data.get("ClubId", "")
        if not club_id:
            continue

        # Build basic row with ALL fields from recommendation API
        basic_row: BasicClubRow = {
            "City": city,
            "PlayWith": 4,
            "Age": 0,
            "ClubId": club_id,
            "Source": "recommendation",
        }
        # Add all fields from recommendation response
        for key, value in club_data.items():
            if key != "ClubId":  # Already added above
                basic_row[key] = value

        basic_rows.append(basic_row)
        club_ids_to_fetch_detail.append(club_id)

    if basic_rows:
        await async_append_basic_csv_rows(basic_rows)
        logger.info(f"[{city}] Phase 1: Written {len(basic_rows)} basic club rows to CSV (all recommendation fields)")

    # ===== PHASE 2: Fetch detailed info and write to detail CSV =====
    # Only fetch detail for clubs that need additional info not in recommendation
    rows_to_save: List[ClubRow] = []

    from curl_cffi import AsyncSession
    async with AsyncSession(impersonate="chrome120", timeout=300.0) as client:
        tasks = []
        for club_id in club_ids_to_fetch_detail:
            # Find the club data from recommendation to extract additional fields
            club_data = next((c for c in clubs_data if c.get("ClubId") == club_id), {})
            tasks.append(
                fetch_club_info(
                    client, club_id, 0, 4, city, limiter, stats, dry_run,
                    latitude=club_data.get("Latitude", 51.5074),
                    longitude=club_data.get("Longitude", -0.1278),
                    week_days=club_data.get("WeekDays", "1,2,3,4,5,6,7"),
                    disability_option=club_data.get("Disabilityoption", 3),
                    disability_type=club_data.get("DisabilityType", []),
                    school_year=club_data.get("SchoolYear", ""),
                    football_type=club_data.get("FootballType", "U10"),
                    search_id=club_data.get("SearchId", None)
                )
            )
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in raw_results:
        if isinstance(r, dict):
            rows_to_save.append(r)
    return rows_to_save


def process_city_worker(args: WorkerArgs) -> Dict[str, Any]:
    """
    Worker function that runs in a separate process.
    Each worker creates its own asyncio event loop.
    """
    city = args.get("city", "Unknown")
    pending_combos = args.get("pending_combos", [])
    dry_run = args.get("dry_run", False)
    shared_counter = args.get("shared_counter")
    shared_lock = args.get("shared_lock")
    clubs_saved_counter = args.get("clubs_saved_counter")
    clubs_saved_lock = args.get("clubs_saved_lock")
    limit = args.get("limit", 0)

    start = time.time()
    logger.info(f"Process start for city {city}, combos={len(pending_combos)}, dry_run={dry_run}, limit={limit}")

    processed_combos_global = safe_load_pickle("storage/processed_combos.pkl", set()) or set()
    processed_combos_buffer: ProcessedCombos = set()

    stats: StatsDict = {"success": 0, "failed": 0, "http_errors": 0, "other_errors": 0,
             "rate_limited": 0, "skipped_cache": 0, "no_name": 0}

    total = len(pending_combos)
    pbar = tqdm(total=total, desc=f"City: {city}", ncols=120, position=1, leave=False)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        for (age, play_with) in pending_combos:
            # Check limit before processing combo
            if limit > 0 and clubs_saved_counter and clubs_saved_lock:
                with clubs_saved_lock:
                    if clubs_saved_counter.value >= limit:
                        logger.info(f"Limit of {limit} clubs reached, stopping city {city}")
                        break

            combo_key = f"{city}__0"  # Single combo per city
            if combo_key in processed_combos_global:
                pbar.set_postfix_str("skip")
                pbar.update(1)
                # Update shared counter
                if shared_counter and shared_lock:
                    with shared_lock:
                        shared_counter.value += 1
                continue

            attempt = 0
            rows: List[ClubRow] = []
            while attempt < TOTAL_RETRIES:
                attempt += 1
                try:
                    rows = loop.run_until_complete(process_combo_async(
                        city,
                        stats,
                        dry_run=dry_run
                    ))
                    break
                except Exception as e:
                    log_error_with_context(
                        logger, f"City {city} attempt {attempt} failed: {e}",
                        city=city, attempt=attempt, error=e, level="warning"
                    )
                    time.sleep(min(0.5 * (2 ** attempt) + random.random(), 10.0))
                    if attempt < TOTAL_RETRIES:
                        time.sleep(1 + random.random())

            if rows:
                # Check limit again before saving
                if limit > 0 and clubs_saved_counter and clubs_saved_lock:
                    with clubs_saved_lock:
                        if clubs_saved_counter.value >= limit:
                            logger.info(f"Limit of {limit} clubs reached before saving, stopping city {city}")
                            break
                        # Calculate how many we can save
                        remaining = limit - clubs_saved_counter.value
                        if len(rows) > remaining:
                            rows = rows[:remaining]
                        clubs_saved_counter.value += len(rows)

                loop.run_until_complete(async_append_csv_rows_safe(rows))
            else:
                stats["failed"] += 1

            # mark combo done
            processed_combos_buffer.add(combo_key)
            if len(processed_combos_buffer) >= 20:
                processed_combos_global.update(processed_combos_buffer)
                try:
                    atomic_pickle_dump(processed_combos_global, "storage/processed_combos.pkl")
                except Exception as e:
                    log_error_with_context(
                        logger, f"Failed to dump processed_combos: {e}",
                        city=city, error=e, level="warning"
                    )
                processed_combos_buffer.clear()

            pbar.update(1)
            # Update shared counter
            if shared_counter and shared_lock:
                with shared_lock:
                    shared_counter.value += 1

    finally:
        if processed_combos_buffer:
            processed_combos_global.update(processed_combos_buffer)
        try:
            atomic_pickle_dump(processed_combos_global, "storage/processed_combos.pkl")
        except Exception as e:
            log_error_with_context(
                logger, f"Final dump failed: {e}",
                city=city, error=e, level="warning"
            )
        # Close all CSV writers to flush any remaining queued rows
        loop.run_until_complete(close_all_csv_writers())
        loop.close()
        pbar.close()

    elapsed = time.time() - start
    logger.info(f"Process done for city {city} elapsed {elapsed:.1f}s stats={stats}")
    return {"city": city, "elapsed": elapsed, "stats": stats, "combos_done": len(pending_combos)}