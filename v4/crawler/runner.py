"""
Main crawler runner for v4: orchestrates multiprocessing + asyncio.
"""
import time
import logging
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import Manager
from multiprocessing.managers import ValueProxy
from multiprocessing.synchronize import Lock as LockProxy
from tqdm import tqdm
from typing import Any, Dict, List

from v4.config import MAX_PROCESSES, MAX_CONCURRENT_REQUESTS, CSV_FILE
from v4.storage import (
    load_existing_output_info, safe_load_pickle, save_summary_csv
)
from v4.eta import ETACalculator
from v4.types import CityName, StatsDict, WorkerArgs
from v4.crawler.worker import process_city_worker
from v4.crawler.combos import build_pending_combos_for_city
from v4.crawler.logging import log_error_with_context

logger = logging.getLogger(__name__)


def run_crawler(
    cities: List[CityName],
    dry_run: bool = False,
    limit: int = 0,
    max_combos: int = 0
) -> None:
    """
    Run the crawler for multiple cities using multiprocessing + asyncio.
    """
    # Load cities và combo đã crawl
    _, combos_from_csv = load_existing_output_info()
    processed_from_pickle = safe_load_pickle("storage/processed_combos.pkl", set()) or set()
    existing_combo_set = set().union(combos_from_csv, processed_from_pickle)

    start_time = time.time()
    start_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"🚀 Crawl started at {start_dt}")

    # Build per-city pending combos with limits
    city_args: List[WorkerArgs] = []
    total_pending_combos = 0
    combos_added = 0

    for city in cities:
        pending = build_pending_combos_for_city(city, existing_combo_set)
        if pending:
            # Apply max_combos limit
            if max_combos > 0:
                remaining = max_combos - combos_added
                if remaining <= 0:
                    break
                pending = pending[:remaining]
                combos_added += len(pending)
            else:
                combos_added += len(pending)

            city_args.append({"city": city, "pending_combos": pending, "dry_run": dry_run})
            total_pending_combos += len(pending)
        else:
            logger.info(f"City {city} already fully completed, skipping.")

    if not city_args:
        print("No pending combos — everything is complete.")
        return

    print(f"\n{'='*60}")
    print(f"CRAWL OVERVIEW")
    print(f"{'='*60}")
    print(f"Total cities to process: {len(city_args)}")
    print(f"Total pending combos: {total_pending_combos:,}")
    print(f"Max processes: {MAX_PROCESSES}")
    print(f"Concurrent requests/process: {MAX_CONCURRENT_REQUESTS}")
    print(f"Dry run: {dry_run}")
    if limit > 0:
        print(f"Club limit: {limit}")
    if max_combos > 0:
        print(f"Max combos: {max_combos}")
    print(f"{'='*60}\n")

    # Shared counter for overall progress
    manager = Manager()
    shared_counter: ValueProxy[int] = manager.Value('i', 0)
    shared_lock: LockProxy = manager.Lock()

    # Shared counter for club limit
    clubs_saved_counter: ValueProxy[int] = manager.Value('i', 0)
    clubs_saved_lock: LockProxy = manager.Lock()

    # ETA Calculator
    eta_calc = ETACalculator(total_pending_combos)

    # Overall stats
    overall_stats: StatsDict = {
        "total_fetched": 0,
        "saved": 0,
        "skipped_name": 0,
        "skipped_other": 0,
    }
    failed_cities: List[CityName] = []

    # Run multiprocessing with overall progress bar
    with ProcessPoolExecutor(max_workers=min(MAX_PROCESSES, len(city_args))) as executor:
        # Submit all jobs
        future_to_city: Dict[Any, CityName] = {}
        for arg in city_args:
            arg["shared_counter"] = shared_counter
            arg["shared_lock"] = shared_lock
            arg["clubs_saved_counter"] = clubs_saved_counter
            arg["clubs_saved_lock"] = clubs_saved_lock
            arg["limit"] = limit
            future = executor.submit(process_city_worker, arg)
            future_to_city[future] = arg["city"]

        # Overall progress bar
        overall_pbar = tqdm(total=total_pending_combos, desc="Overall", ncols=120, position=0)

        last_completed = 0
        start_overall = time.time()

        for fut in as_completed(future_to_city):
            city = future_to_city[fut]
            try:
                res = fut.result()
                logger.info(f"City finished: {res['city']} elapsed {res['elapsed']:.1f}s")

                stats = res.get("stats", {})
                overall_stats["total_fetched"] += stats.get("success", 0)
                overall_stats["saved"] += stats.get("success", 0)
                overall_stats["skipped_name"] += stats.get("skipped_name", 0)
                overall_stats["skipped_other"] += stats.get("skipped_cache", 0) + stats.get("no_name", 0) + stats.get("other_errors", 0)

                if stats.get("failed", 0) > 0:
                    # Only mark as failed if there are REAL errors (not just empty combos)
                    real_errors = stats.get("http_errors", 0) + stats.get("other_errors", 0)
                    if real_errors > 0:
                        failed_cities.append(res['city'])
            except Exception as e:
                log_error_with_context(
                    logger, f"City worker process failed: {e}",
                    city=city, error=e, level="error"
                )
                failed_cities.append(city)
                # Continue to next city - don't hang on retries

            # Update overall progress bar with shared counter
            while True:
                with shared_lock:
                    current = shared_counter.value
                if current > last_completed:
                    delta = current - last_completed
                    overall_pbar.update(delta)
                    last_completed = current
                    eta_calc.update(current)
                    # Update postfix with ETA
                    overall_pbar.set_postfix_str(
                        f"Rate: {eta_calc.get_rate_str()} | ETA: {eta_calc.get_eta_str()} | {eta_calc.get_progress_str()}"
                    )
                else:
                    break

        overall_pbar.close()

    # Summary and final stats
    elapsed = time.time() - start_time
    hours, remainder = divmod(int(elapsed), 3600)
    minutes, seconds = divmod(remainder, 60)
    end_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(
        f"[FINAL TOTAL STATS] Fetched: {overall_stats['total_fetched']}, "
        f"Saved: {overall_stats['saved']}, "
        f"Skipped (Same City): {overall_stats['skipped_name']}, "
        f"Skipped (Other): {overall_stats['skipped_other']}"
    )

    if failed_cities:
        logger.warning(f"⚠️ {len(failed_cities)} cities failed: {', '.join(failed_cities)}")
    else:
        logger.info("✅ All cities completed successfully without errors.")

    logger.info(f"✅ Crawl completed successfully in {hours:02d}:{minutes:02d}:{seconds:02d}")
    logger.info(f"🏁 End time: {end_dt}")

    # ===== FINAL DEDUPLICATION: Drop duplicate rows ignoring specific columns =====
    logger.info("Starting final deduplication pass...")
    try:
        import pandas as pd
        df = pd.read_csv(CSV_FILE)
        original_count = len(df)
        # Columns to ignore when checking for duplicates
        ignore_cols = {"City", "PlayWith", "Age", "Latitude", "Longitude"}
        # Use all columns except ignored ones as the subset for deduplication
        subset_cols = [c for c in df.columns if c not in ignore_cols]
        df_deduped = df.drop_duplicates(subset=subset_cols)
        deduped_count = len(df_deduped)
        removed_count = original_count - deduped_count
        if removed_count > 0:
            df_deduped.to_csv(CSV_FILE, index=False)
            logger.info(f"Final deduplication: removed {removed_count} duplicate rows (ignoring {ignore_cols}) ({original_count} → {deduped_count})")
        else:
            logger.info(f"Final deduplication: no duplicates found ({original_count} rows)")
    except Exception as e:
        logger.warning(f"Final deduplication failed: {e}")

    # Save summary CSV
    save_summary_csv(cities, overall_stats, failed_cities, start_dt, elapsed)

    print(f"\n{'='*60}")
    print(f"DONE in {hours:02d}:{minutes:02d}:{seconds:02d}")
    print(f"Fetched: {overall_stats['total_fetched']:,} | Saved: {overall_stats['saved']:,}")
    print(f"Skipped (dup): {overall_stats['skipped_name']:,} | Other: {overall_stats['skipped_other']:,}")
    if failed_cities:
        print(f"Failed cities: {len(failed_cities)}")
    print(f"{'='*60}\n")