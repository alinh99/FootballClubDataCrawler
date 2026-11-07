"""
Main entry point for v4 crawler.
"""
import argparse
import logging
import sys
import os
from typing import List

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from v4.config import LOG_FILE
from v4.storage import load_cities
from v4.crawler import run_crawler
from v4.types import CityName


def setup_logging() -> None:
    """Setup logging configuration."""
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    # Also log to console
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(console)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Football Club Data Crawler v4 - Async API")
    parser.add_argument("--dry-run", action="store_true", help="Run without making API calls")
    parser.add_argument("--limit", type=int, default=0, help="Max clubs to fetch (0 = unlimited)")
    parser.add_argument("--max-combos", type=int, default=0, help="Max city combos to process (0 = all)")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint (default: auto)")
    return parser.parse_args()


def main() -> int:
    setup_logging()
    logger = logging.getLogger(__name__)

    args = parse_args()

    # Load cities
    cities: List[CityName] = load_cities()
    if not cities:
        logger.error("No cities found. Run city_crawling.py first.")
        return 1

    # Apply max_combos limit
    if args.max_combos > 0:
        cities = cities[:args.max_combos]

    logger.info(f"Total cities to process: {len(cities)}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Max clubs limit: {args.limit if args.limit > 0 else 'unlimited'}")
    logger.info(f"Max combos: {args.max_combos if args.max_combos > 0 else 'all'}")

    # Run crawler
    try:
        run_crawler(cities, args.dry_run, args.limit, args.max_combos)
        logger.info("=" * 60)
        logger.info("✅ Crawl completed successfully")
        logger.info("=" * 60)
        return 0
    except KeyboardInterrupt:
        logger.info("Crawl interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Crawl failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())