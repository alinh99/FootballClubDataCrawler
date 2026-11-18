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
from v4.crawler.phase.phase2 import process_phase2
from v4.storage import (
    atomic_pickle_dump, async_append_csv_rows_safe,
    async_append_basic_csv_rows, flush_csv_basic_writer, safe_load_pickle, close_all_csv_writers,
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
    dry_run: bool = False,
    limit: int = 0,
    max_booking_urls: int = 0
) -> List[ClubRow]:
    """
    Process a single city combo.
    Phase 1: Write ALL available club info from recommendation API immediately.
    Phase 2: Fetch detailed info and write to detail CSV (for any missing fields).
    """
    combo_key = f"{city}__{play_with}__{age}"
    limiter = AdaptiveLimiter(MAX_CONCURRENT_REQUESTS, min_concurrent=5, max_concurrent=MAX_CONCURRENT_LIMIT)
    api_general_info_data = await fetch_recommendation_pages(city, dry_run, limit)

    # Extract ALL fields from recommendation API response
    clubs_data = extract_full_club_data_from_recommendation(api_general_info_data)
    if not clubs_data:
        return []

    # ===== PHASE 1: Write ALL available club info from recommendation API immediately =====
    basic_rows: List[BasicClubRow] = []
    club_ids_to_fetch_detail: List[str] = []

    # Combo fields that should NOT be overwritten by API response
    combo_fields = {"City", "PlayWith", "Age", "ClubId"}

    for club_data in clubs_data:
        club_id = club_data.get("ClubId", "")

        # Build basic row with ACTUAL combo values
        basic_row: BasicClubRow = {
            "City": city,
            "PlayWith": play_with,
            "Age": age,
            "ClubId": club_id,
            "Source": "recommendation",
        }
        # Add all fields from recommendation response EXCEPT combo fields
        for key, value in club_data.items():
            if key not in combo_fields:
                basic_row[key] = value

        basic_rows.append(basic_row)
        club_ids_to_fetch_detail.append(club_id)

    if basic_rows:
        await async_append_basic_csv_rows(basic_rows)
        await flush_csv_basic_writer()
        logger.info(f"[{city}] Phase 1: Written {len(basic_rows)} basic club rows (Age={age}, PlayWith={play_with})")

    # ===== PHASE 2: Fetch detailed info and write to detail CSV =====
    # Use phase2 module which reads from clubs_basic.csv and processes sequentially
    # Apply limit to club_ids_to_fetch_detail to respect the global club limit
    if limit > 0:
        club_ids_to_fetch_detail = club_ids_to_fetch_detail[:limit]
        logger.info(f"[{city}] Phase 2: Limited to {len(club_ids_to_fetch_detail)} clubs (limit={limit})")

    rows_to_save = await process_phase2(
        city=city,
        age=age,
        play_with=play_with,
        clubs_data=clubs_data,  # for backward compatibility
        club_ids_to_fetch_detail=club_ids_to_fetch_detail,
        stats=stats,
        club_cache=club_cache,
        dry_run=dry_run,
        max_booking_urls=max_booking_urls
    )
    return rows_to_save


async def process_combo_with_retry(
    city: CityName,
    age: int,
    play_with: int,
    stats: StatsDict,
    club_cache: ClubCache,
    processed_combos_global: Set[str],
    dry_run: bool = False,
    limit: int = 0,
    max_booking_urls: int = 0,
    max_retries: int = TOTAL_RETRIES
) -> Tuple[List[ClubRow], bool]:
    """
    Process a single combo with retry logic.
    Returns (rows, success_flag)
    """
    combo_key = f"{city}__{play_with}__{age}"

    for attempt in range(1, max_retries + 1):
        try:
            rows = await process_combo_async(city, age, play_with, stats, club_cache, dry_run, limit, max_booking_urls)
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
    max_booking_urls: int,
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
    logger.info(f"[{city}] process_city_combos_concurrent started with {len(pending_combos)} combos, limit={limit}")
    semaphore = asyncio.Semaphore(MAX_COMBO_CONCURRENCY)

    async def process_one_combo(age: int, play_with: int):
        combo_key = f"{city}__{play_with}__{age}"
        logger.info(f"[{city}] process_one_combo called for Age={age}, PW={play_with}")

        # Check if already processed
        if combo_key in processed_combos_global:
            with shared_lock:
                shared_counter.value += 1
            pbar.update(1)
            logger.info(f"[{city}] SKIP: Age={age}, PW={play_with} (already done)")
            return

        logger.info(f"[{city}] START: Age={age}, PW={play_with}")
        async with semaphore:
            logger.info(f"[{city}] Acquired semaphore for Age={age}, PW={play_with}")
            # Check limit before processing
            if limit > 0 and clubs_saved_counter:
                with clubs_saved_lock:
                    if clubs_saved_counter.value >= limit:
                        logger.info(f"[{city}] Limit reached before processing, returning")
                        return

            logger.info(f"[{city}] Calling process_combo_with_retry for Age={age}, PW={play_with}")
            rows, success = await process_combo_with_retry(
                city, age, play_with, stats, club_cache, processed_combos_global, dry_run, limit, max_booking_urls
            )
            logger.info(f"[{city}] process_combo_with_retry returned: success={success}, rows={len(rows) if rows else 0}")

            if success and rows:
                # Check limit again before saving
                if limit > 0 and clubs_saved_counter:
                    with clubs_saved_lock:
                        if clubs_saved_counter.value >= limit:
                            logger.info(f"[{city}] Limit reached after processing, returning")
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
            with shared_lock:
                shared_counter.value += 1
            logger.info(f"[{city}] process_one_combo finished for Age={age}, PW={play_with}")

    # Create tasks for all combos
    logger.info(f"[{city}] Creating {len(pending_combos)} tasks")
    tasks = [process_one_combo(age, play_with) for age, play_with in pending_combos]
    logger.info(f"[{city}] Awaiting gather...")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(f"[{city}] Gather completed, results: {results}")
    # Check for exceptions
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"[{city}] Task {i} raised exception: {result}", exc_info=result)


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
    max_booking_urls = args.get("max_booking_urls", 0)

    start = time.time()
    logger.info(f"Process start for city {city}, combos={len(pending_combos)}, dry_run={dry_run}, limit={limit}, max_booking_urls={max_booking_urls}, combo_concurrency={MAX_COMBO_CONCURRENCY}")

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
            max_booking_urls=max_booking_urls,
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