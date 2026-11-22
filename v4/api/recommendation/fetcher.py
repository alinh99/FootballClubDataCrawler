"""
Recommendation API page fetching for v4 crawler.
"""
import asyncio
import random
import logging
import json as _json
from typing import List, Optional, Dict, Any

from curl_cffi import requests as curl_requests

from v4.config import (
    API_CLUB_RECOMMENDATION_URL,
    KEY_CLUB_INFO_AND_RECOMMENDATION_INFO,
    RATE_LIMIT_SLEEP,
    TOTAL_RETRIES
)
from v4.types import CityName, RecommendationResponse
from v4.utils.logging import log_error_with_context
from v4.eta import PhaseETACalculator

from .payload import build_recommendation_payload, build_page_payload
from .extractor import extract_clubids_from_recommendation, get_cnt_opportunity

logger = logging.getLogger(__name__)


# Recommendation API retry settings (uses TOTAL_RETRIES from .env)
RECOMMENDATION_MAX_BACKOFF = 60.0  # Cap at 60 seconds
RECOMMENDATION_DELAY_BETWEEN_PAGES = 1.0  # 1s delay between pages when no error


def fetch_page_sync(client: curl_requests.Session, city: CityName, page_number: int, base_payload: Dict[str, Any]) -> Optional[RecommendationResponse]:
    """
    Fetch a single page of results synchronously (for use in thread pool).
    Includes retry logic with exponential backoff for 429/5xx errors.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
        "Ocp-Apim-Subscription-Key": KEY_CLUB_INFO_AND_RECOMMENDATION_INFO
    }
    payload = build_page_payload(base_payload, page_number)

    for attempt in range(TOTAL_RETRIES):
        try:
            logger.info(f"[{city}] → Fetching page {page_number} (attempt {attempt+1})...")
            logger.info(f"[{city}] → API URL: {API_CLUB_RECOMMENDATION_URL}")
            logger.debug(f"[{city}] → Payload: {payload}")
            resp = client.post(API_CLUB_RECOMMENDATION_URL, json=payload, headers=headers)
            # Handle status codes
            if resp.status_code == 204:
                return None
            if resp.status_code in (401, 403):
                raise Exception(f"Auth failed ({resp.status_code}): Check API key. Response: {resp.text[:200]}")
            if resp.status_code in (429, 500, 502, 503, 504):
                raise Exception(f"Server error ({resp.status_code}): {resp.text[:200]}")
            resp.raise_for_status()
            # Validate JSON response
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" not in content_type:
                raise Exception(f"Non-JSON response ({resp.status_code}, {content_type}): {resp.text[:200]}")
            if not resp.content:
                raise Exception(f"Empty response ({resp.status_code})")
            try:
                return resp.json()
            except _json.JSONDecodeError as je:
                raise Exception(f"Invalid JSON: {je}. Response: {resp.text[:200]}")
        except Exception as e:
            error_str = str(e)
            # Don't retry auth errors
            if "Auth failed" in error_str:
                raise
            # Retry 429 with exponential backoff capped at 60s
            if "Server error (429)" in error_str:
                sleep_time = min(RATE_LIMIT_SLEEP * (2 ** attempt) + random.random() * 5, RECOMMENDATION_MAX_BACKOFF)
            else:
                # Other server errors: shorter backoff
                sleep_time = RATE_LIMIT_SLEEP + random.random() * 5
            if attempt + 1 < TOTAL_RETRIES:
                logger.warning(f"[{city}] Page {page_number} attempt {attempt+1} failed: {e}. Retrying in {sleep_time:.1f}s...")
                import time
                time.sleep(sleep_time)
                continue
            else:
                log_error_with_context(
                    logger, f"Page {page_number} max retries reached: {e}",
                    city=city, page=page_number, attempt=attempt+1
                )
                raise


async def fetch_recommendation_pages(city: CityName, dry_run: bool = False, limit: int = 0) -> List[RecommendationResponse]:
    """
    Fetch all pages of club recommendations for a city.
    Uses parallel batch fetching for speed.
    Returns list of API response objects.

    Args:
        city: City name
        dry_run: If True, return mock data
        limit: Max clubs to fetch (0 = unlimited). Stops fetching when this many clubs collected.
    """
    if dry_run:
        return [{"RecommendationClubCartDto": [{"ClubId": f"DRY_{city}_{i}"} for i in range(25)], "FootballType": "DRY"}]

    loop = asyncio.get_event_loop()
    base_payload = build_recommendation_payload(city)
    page_size = base_payload["PageSize"]  # 50
    PARALLEL_PAGE_BATCH = 3  # Fetch 3 pages concurrently

    # Create a single session to reuse for all page fetches (connection pooling)
    session = curl_requests.Session(impersonate="chrome120", timeout=120.0)

    try:
        all_results: List[RecommendationResponse] = []
        page = 1
        total_pages: Optional[int] = None
        cnt_opportunity: int = 0
        clubs_fetched: int = 0

        # Check if we've already reached the limit
        if limit > 0 and clubs_fetched >= limit:
            logger.info(f"[{city}] Limit reached ({limit}), stopping")
            return all_results

        async def fetch_pages_batch(start_page: int, batch_size: int) -> List[Any]:
            """Fetch multiple pages concurrently."""
            tasks = [
                loop.run_in_executor(None, fetch_page_sync, session, city, start_page + i, base_payload)
                for i in range(batch_size)
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)

        # First, fetch page 1 to get CntOpportunity
        result = await loop.run_in_executor(None, fetch_page_sync, session, city, 1, base_payload)
        if result is None:
            logger.info(f"[{city}] Page 1: 204 No Content - no pages")
            return all_results

        if result:
            all_results.append(result)
            clubs_in_page = extract_clubids_from_recommendation([result]) if isinstance(result, dict) else extract_clubids_from_recommendation(result)
            clubs_fetched += len(clubs_in_page)

            if isinstance(result, dict):
                cnt_opportunity = result.get("CntOpportunity", 0)
                if cnt_opportunity > 0:
                    total_pages = (cnt_opportunity + page_size - 1) // page_size
                    logger.info(f"[{city}] Total clubs: {cnt_opportunity}, PageSize: {page_size} → {total_pages} pages")
                    logger.info(f"[{city}] Progress: {clubs_fetched}/{cnt_opportunity} clubs fetched ({clubs_fetched/cnt_opportunity*100:.1f}%)")

        # Phase 1 ETA calculator (clubs level)
        phase1_eta = PhaseETACalculator(total_combos=1)
        if cnt_opportunity > 0:
            phase1_eta.start_phase1(cnt_opportunity)
        else:
            # Estimate if we don't have count yet
            phase1_eta.start_phase1(page_size * (total_pages or 10))

        # Check limit after page 1
        if limit > 0 and clubs_fetched >= limit:
            logger.info(f"[{city}] Limit reached ({limit}) after page 1, stopping")
            phase1_eta.update_phase1(clubs_fetched)
            phase1_eta.log_phase1(logger, city, force=True)
            return all_results

        # Small delay after page 1 before fetching remaining pages
        await asyncio.sleep(RECOMMENDATION_DELAY_BETWEEN_PAGES)

        # Fetch remaining pages in parallel batches
        page = 2
        while True:
            if total_pages and page > total_pages:
                logger.info(f"[{city}] Reached total pages ({total_pages}) - stopping")
                break

            # Check limit before fetching next batch
            if limit > 0 and clubs_fetched >= limit:
                logger.info(f"[{city}] Limit reached ({clubs_fetched}/{limit}), stopping")
                break

            batch_size = min(PARALLEL_PAGE_BATCH, total_pages - page + 1) if total_pages else PARALLEL_PAGE_BATCH
            batch_results = await fetch_pages_batch(page, batch_size)

            batch_completed = 0
            for i, result in enumerate(batch_results):
                current_page = page + i
                if isinstance(result, Exception):
                    logger.warning(f"[{city}] Page {current_page}: Error - {result}")
                    continue
                if result is None:
                    # 204 No Content - no more pages
                    logger.info(f"[{city}] Page {current_page}: 204 No Content - no more pages")
                    phase1_eta.update_phase1(clubs_fetched)
                    phase1_eta.log_phase1(logger, city, force=True)
                    return all_results
                if result:
                    all_results.append(result)
                    clubs_in_page = extract_clubids_from_recommendation([result]) if isinstance(result, dict) else extract_clubids_from_recommendation(result)
                    clubs_fetched += len(clubs_in_page)
                    batch_completed += 1

                    # Log progress
                    if cnt_opportunity > 0:
                        logger.info(f"[{city}] Progress: {clubs_fetched}/{cnt_opportunity} clubs fetched ({clubs_fetched/cnt_opportunity*100:.1f}%)")
                    else:
                        logger.info(f"[{city}] Fetched {clubs_fetched} clubs so far")

                    # Update Phase 1 ETA
                    phase1_eta.update_phase1(clubs_fetched)
                    phase1_eta.log_phase1(logger, city, force=False)

                    # Fallback check if no CntOpportunity
                    if total_pages is None and len(clubs_in_page) < page_size:
                        logger.info(f"[{city}] Page {current_page}: Got {len(clubs_in_page)} clubs (< {page_size}) - last page (fallback)")
                        phase1_eta.update_phase1(clubs_fetched)
                        phase1_eta.log_phase1(logger, city, force=True)
                        return all_results

            if batch_completed == 0:
                logger.info(f"[{city}] No results in batch starting at page {page} - stopping")
                break

            page += batch_size

            # Small delay between page requests to avoid rate limiting
            await asyncio.sleep(RECOMMENDATION_DELAY_BETWEEN_PAGES)

        phase1_eta.update_phase1(clubs_fetched)
        phase1_eta.log_phase1(logger, city, force=True)
        logger.info(f"[{city}] Completed fetching {len(all_results)} pages, {clubs_fetched} clubs total")
        return all_results
    finally:
        session.close()