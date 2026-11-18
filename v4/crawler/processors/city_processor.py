"""
City processor for v4 crawler: process all combos for a single city.
"""
import asyncio
import logging
from typing import List, Tuple, Any

from v4.types import CityName, ClubRow, StatsDict, ClubCache
from v4.config import AGE_GROUPS, PLAY_WITH_OPTIONS
from v4.api import fetch_recommendation_pages
from v4.crawler.phase import process_phase1, process_phase2
from v4.storage import close_csv_basic_writer

logger = logging.getLogger(__name__)


def setup_worker_logging(city: CityName) -> None:
    """Configure logging for worker processes."""
    import sys
    from v4.main import FlushingFileHandler, FlushingStreamHandler

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # File handler with flushing
    log_file = f"logs/crawler_{city}.log"
    file_handler = FlushingFileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(file_formatter)

    # Console handler with flushing
    console_handler = FlushingStreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    console_handler.setFormatter(console_formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


async def process_city_async(
    city: CityName,
    stats: StatsDict,
    club_cache: ClubCache,
    dry_run: bool = False,
    limit: int = 0
) -> List[ClubRow]:
    """
    Process all combos (age, play_with) for a single city.

    Returns all club rows for this city.
    """
    setup_worker_logging(city)
    logger.info(f"[{city}] Starting city processing (Age groups: {AGE_GROUPS}, PlayWith: {PLAY_WITH_OPTIONS})")

    all_rows: List[ClubRow] = []

    for play_with in PLAY_WITH_OPTIONS:
        for age in AGE_GROUPS:
            try:
                rows = await process_combo_async(city, age, play_with, stats, club_cache, dry_run, limit)
                all_rows.extend(rows)
            except Exception as e:
                logger.error(f"[{city}] Error processing Age={age}, PlayWith={play_with}: {e}", exc_info=True)

    logger.info(f"[{city}] Completed city processing: {len(all_rows)} total clubs")
    return all_rows


# Import here to avoid circular import
from .combo_processor import process_combo_async