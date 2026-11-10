"""
Worker functions for v4 crawler: process cities and combos.
"""
import asyncio
import time
import random
import logging
from tqdm import tqdm
from typing import Any, Dict, List, Set, Tuple

from multiprocessing.managers import ValueProxy
from multiprocessing.synchronize import Lock as LockProxy

from v4.config import MAX_CONCURRENT_REQUESTS, MAX_CONCURRENT_LIMIT, TOTAL_RETRIES, MAX_COMBO_CONCURRENCY
from v4.models import AdaptiveLimiter
from v4.api import fetch_recommendation_pages, fetch_club_info, extract_full_club_data_from_recommendation
from v4.storage import (
    atomic_pickle_dump, async_append_csv_rows_safe,
    async_append_basic_csv_rows, safe_load_pickle, close_all_csv_writers,
    save_checkpoint_json
)
from v4.types import (
    CityName, ClubRow, BasicClubRow, StatsDict, WorkerArgs, ProcessedCombos, ClubCache
)
from v4.crawler.logging import log_error_with_context
from v4.crawler.logging_setup import setup_worker_logging, get_worker_logger

# Setup logging for this worker process
setup_worker_logging()
logger = get_worker_logger(__name__)


async def process_combo_async(
    city: CityName,
    age: int,
    play_with: int,
    stats: StatsDict,
    club_cache: ClubCache,
    dry_run: bool = False
) -> List[ClubRow]:
    """
    Process a single city combo.
    Phase 1: Write ALL available club info from recommendation API immediately.
    Phase 2: Fetch detailed info and write to detail CSV (for any missing fields).
    """
    combo_key = f"{city}__{play_with}__{age}"
    limiter = AdaptiveLimiter(MAX_CONCURRENT_REQUESTS, min_concurrent=5, max_concurrent=MAX_CONCURRENT_LIMIT)
    api_general_info_data = await fetch_recommendation_pages(city, age, play_with, dry_run)

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

        # Build basic row with ACTUAL combo values
        basic_row: BasicClubRow = {
            "City": city,
            "PlayWith": play_with,
            "Age": age,
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
        logger.info(f"[{city}] Phase 1: Written {len(basic_rows)} basic club rows (Age={age}, PlayWith={play_with})")

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
                    client, club_id, age, play_with, city, limiter, stats, club_cache, dry_run,
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


async def process_combo_with_retry(
    city: CityName,
    age: int,
    play_with: int,
    stats: StatsDict,
    club_cache: ClubCache,
    processed_combos_global: Set[str],
    dry_run: bool = False,
    max_retries: int = TOTAL_RETRIES
) -> Tuple[List[ClubRow], bool]:
    """
    Process a single combo with retry logic.
    Returns (rows, success_flag)
    """
    combo_key = f"{city}__{play_with}__{age}"

    for attempt in range(1, max_retries + 1):
        try:
            rows = await process_combo_async(city, age, play_with, stats, club_cache, dry_run)
            return rows, True
        except Exception as e:
            log_error_with_context(
                logger, f"City {city} Age={age} PW={play_with} attempt {attempt} failed: {e}",
                city=city, age=age, play_with=play_with, attempt=attempt, error=e, level="warning"
            )
            if attempt < max_retries:
                sleep_time = min(0.5 * (2 ** attempt) + random.random(), 10.0)
                await asyncio.sleep(sleep_time)
            else:
                log_error_with_context(
                    logger, f"City {city} Age={age} PW={play_with} max retries reached",
                    city=city, age=age, play_with=play_with, attempt=attempt, error=e, level="error"
                )
    return [], False


async def process_city_combos_concurrent(
    city: CityName,
    pending_combos: List[Tuple[int, int]],
    stats: StatsDict,
    club_cache: ClubCache,
    processed_combos_global: ProcessedCombos,
    dry_run: bool,
    limit: int,
    clubs_saved_counter: Any,
    clubs_saved_lock: Any,
    shared_counter: Any,
    shared_lock: Any,
    pbar: tqdm
) -> None:
    """
    Process multiple combos concurrently for a city.
    Uses semaphore to limit concurrent combos.
    """
    semaphore = asyncio.Semaphore(MAX_COMBO_CONCURRENCY)

    async def process_one_combo(age: int, play_with: int):
        combo_key = f"{city}__{play_with}__{age}"

        # Check if already processed
        if combo_key in processed_combos_global:
            async with shared_lock:
                shared_counter.value += 1
            pbar.update(1)
            logger.info(f"[{city}] SKIP: Age={age}, PW={play_with} (already done)")
            return

        logger.info(f"[{city}] START: Age={age}, PW={play_with}")
        async with semaphore:
            # Check limit before processing
            if limit > 0 and clubs_saved_counter:
                async with clubs_saved_lock:
                    if clubs_saved_counter.value >= limit:
                        return

            rows, success = await process_combo_with_retry(
                city, age, play_with, stats, club_cache, processed_combos_global, dry_run
            )

            if success and rows:
                # Check limit again before saving
                if limit > 0 and clubs_saved_counter:
                    async with clubs_saved_lock:
                        if clubs_saved_counter.value >= limit:
                            return
                        remaining = limit - clubs_saved_counter.value
                        if len(rows) > remaining:
                            rows = rows[:remaining]
                        clubs_saved_counter.value += len(rows)

                await async_append_csv_rows_safe(rows)

                # mark combo done ONLY on success
                processed_combos_global.add(combo_key)

                # Save checkpoint after EACH combo for maximum resume capability
                try:
                    atomic_pickle_dump(processed_combos_global, "storage/processed_combos.pkl")
                    atomic_pickle_dump(club_cache, "storage/club_cache.pkl")
                    save_checkpoint_json(
                        processed_combos=processed_combos_global,
                        club_cache=club_cache,
                        stats=stats,
                        current_city=city,
                        current_combo=(age, play_with),
                        pending_cities=None
                    )
                except Exception as e:
                    log_error_with_context(
                        logger, f"Failed to dump checkpoint: {e}",
                        city=city, error=e, level="warning"
                    )
                logger.info(f"[{city}] DONE: Age={age}, PW={play_with} → {len(rows)} clubs saved")
            else:
                stats["failed"] += 1
                logger.warning(f"City {city} Age={age} PW={play_with} combo failed — NOT marking as done, will retry next run")

            pbar.update(1)
            async with shared_lock:
                shared_counter.value += 1

    # Create tasks for all combos
    tasks = [process_one_combo(age, play_with) for age, play_with in pending_combos]
    await asyncio.gather(*tasks, return_exceptions=True)


def process_city_worker(args: WorkerArgs) -> Dict[str, Any]:
    """
    Worker function that runs in a separate process.
    Each worker creates its own asyncio event loop.
    Processes multiple combos concurrently within the city.
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
    logger.info(f"Process start for city {city}, combos={len(pending_combos)}, dry_run={dry_run}, limit={limit}, combo_concurrency={MAX_COMBO_CONCURRENCY}")

    processed_combos_global = safe_load_pickle("storage/processed_combos.pkl", set()) or set()
    club_cache = safe_load_pickle("storage/club_cache.pkl", {}) or {}

    stats: StatsDict = {"success": 0, "failed": 0, "http_errors": 0, "other_errors": 0,
             "rate_limited": 0, "skipped_cache": 0, "no_name": 0}

    total = len(pending_combos)
    pbar = tqdm(total=total, desc=f"City: {city}", ncols=120, position=1, leave=False)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(process_city_combos_concurrent(
            city=city,
            pending_combos=pending_combos,
            stats=stats,
            club_cache=club_cache,
            processed_combos_global=processed_combos_global,
            dry_run=dry_run,
            limit=limit,
            clubs_saved_counter=clubs_saved_counter,
            clubs_saved_lock=clubs_saved_lock,
            shared_counter=shared_counter,
            shared_lock=shared_lock,
            pbar=pbar
        ))

    finally:
        # Checkpoint already saved after each combo, but save final state
        try:
            atomic_pickle_dump(processed_combos_global, "storage/processed_combos.pkl")
            atomic_pickle_dump(club_cache, "storage/club_cache.pkl")
            save_checkpoint_json(
                processed_combos=processed_combos_global,
                club_cache=club_cache,
                stats=stats,
                current_city=city,
                current_combo=(pending_combos[-1][0], pending_combos[-1][1]) if pending_combos else (0, 4),
                pending_cities=None
            )
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