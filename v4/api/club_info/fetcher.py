"""
Club Info API fetching for v4 crawler.
"""
import asyncio
import random
import logging
from typing import Dict, Any, Optional, List

from curl_cffi import AsyncSession

from v4.config import (
    API_CLUB_INFO_URL,
    KEY_CLUB_INFO_AND_RECOMMENDATION_INFO,
    TOTAL_RETRIES, RATE_LIMIT_SLEEP
)
from v4.models import AdaptiveLimiter
from v4.types import ClubId, CityName, ClubRow, StatsDict, ClubCache
from v4.utils.logging import log_error_with_context

from .payload import build_club_info_payload, build_club_info_headers
from .contact_fetcher import fetch_contact_info
from .booking_scraper import scrape_booking_url_for_contact
from .builder import build_club_row

logger = logging.getLogger(__name__)


async def fetch_club_info(
    client: AsyncSession,
    club_id: ClubId,
    age: int,
    play_with: int,
    city: CityName,
    limiter: AdaptiveLimiter,
    stats: StatsDict,
    club_cache: ClubCache,
    dry_run: bool = False,
    latitude: float = 51.5074,
    longitude: float = -0.1278,
    week_days: str = "1,2,3,4,5,6,7",
    disability_option: int = 3,
    disability_type: Optional[List[Dict]] = None,
    school_year: str = "",
    football_type: str = "U10",
    search_id: Optional[str] = None,
    recommendation_data_list: Optional[List[Dict[str, Any]]] = None,
    max_booking_urls: int = 0
) -> Optional[ClubRow]:
    """
    Fetch detailed club information from the club info API.

    Additional parameters from recommendation data:
    - latitude: Latitude for location-based search
    - longitude: Longitude for location-based search
    - week_days: Comma-separated week days (e.g., "1,2,3,4,5,6,7")
    - disability_option: Disability option filter
    - disability_type: List of disability types
    - school_year: School year filter
    - football_type: Football type string (e.g., "U10")
    - search_id: Unique search identifier
    """
    import uuid
    if disability_type is None:
        disability_type = []
    if search_id is None:
        search_id = str(uuid.uuid4())

    # ===== CLUB CACHE: Return cached data if available =====
    if club_id in club_cache:
        cached_row = club_cache[club_id]
        # Verify cached row matches requested club_id (duplicate checking only)
        if (isinstance(cached_row, dict)
            and cached_row.get("ClubId") == club_id):
            stats["skipped_cache"] += 1
            logger.info(f"[CACHE HIT] Club {club_id} found in cache, skipping API call")
            return cached_row
        else:
            # Invalid cache entry or ClubId mismatch, remove it
            cached_club_id = cached_row.get("ClubId") if isinstance(cached_row, dict) else None
            logger.warning(f"[CACHE INVALID] Club {club_id}: cached={cached_club_id}, removing")
            del club_cache[club_id]

    payload = build_club_info_payload(
        club_id=club_id,
        age=age,
        play_with=play_with,
        disability_type=disability_type,
        disability_option=disability_option,
        football_type=football_type,
        week_days=week_days,
        latitude=latitude,
        longitude=longitude,
        school_year=school_year,
    )

    headers_base = build_club_info_headers()

    async with limiter.sem:
        for attempt in range(TOTAL_RETRIES):
            try:
                if dry_run:
                    await asyncio.sleep(random.uniform(0.01, 0.06))
                    data = {
                        "ClubName": f"DRY_{city}_{club_id}",
                        "AddressLine1": f"Addr {club_id}",
                        "City": city,
                        "PostCode": "DRY",
                        "ClubCounty": "DryCounty",
                        "TeamsInfo": {"FootballType": ["5-a-side"], "Gender": [], "DisabilityType": []},
                        "TeamsCount": random.randint(1, 5),
                        "WgsClubId": None,
                        "ClubId": club_id,
                    }
                    contact_data = {}
                    booking_contact = {}
                else:
                    headers = {
                        **headers_base,
                        "User-Agent": f"sb/{random.randint(1, 1000)}",
                        "Ocp-Apim-Subscription-Key": KEY_CLUB_INFO_AND_RECOMMENDATION_INFO
                    }
                    resp = await client.post(API_CLUB_INFO_URL, json=payload, headers=headers, timeout=300.0)
                    if resp.status_code in (400, 401, 403):
                        # 400 Bad Request (e.g., invalid ClubId), 401/403 auth failures - don't retry
                        raise Exception(f"Client error ({resp.status_code}): {resp.text[:200]}")
                    if resp.status_code in (429, 500, 502, 503, 504):
                        await limiter.record_failure()
                        log_error_with_context(
                            logger, f"Server error ({resp.status_code}) for Club {club_id}",
                            city=city, club_id=club_id, attempt=attempt+1
                        )
                        stats["rate_limited"] += 1
                        if attempt + 1 == TOTAL_RETRIES:
                            log_error_with_context(
                                logger, f"Max retries reached for Club {club_id}",
                                city=city, club_id=club_id, attempt=attempt+1
                            )
                        # Exponential backoff for 429: 60s, 120s, 240s... capped at 5 min
                        if resp.status_code == 429:
                            sleep_time = min(RATE_LIMIT_SLEEP * (2 ** attempt) + random.random() * 5, 300.0)
                        else:
                            sleep_time = RATE_LIMIT_SLEEP + random.random() * 5
                        await asyncio.sleep(sleep_time)
                        continue
                    resp.raise_for_status()
                    # Validate JSON
                    content_type = resp.headers.get("Content-Type", "")
                    if "application/json" not in content_type or not resp.content:
                        raise Exception(f"Invalid response ({resp.status_code}, {content_type}): {resp.text[:200]}")
                    data = resp.json()
                    await limiter.record_success()

                    club_name = (data.get("ClubName", "") or data.get("OrganizationName", "") or "").strip()
                    contact_data = {}
                    wgs_id = data.get("WgsClubId")
                    if wgs_id:
                        contact_data = await fetch_contact_info(client, wgs_id)

                    # --- Scrape BookingURL for additional contact info ---
                    booking_url = data.get("BookingURL", "") or data.get("BookingUrl", "") or ""
                    booking_contact = {}
                    if booking_url:
                        try:
                            booking_contact = await scrape_booking_url_for_contact(booking_url, client)
                        except Exception as e:
                            logger.warning(f"[BOOKING SCRAPE] Error for club {club_id}: {e}")

                club_name = (data.get("ClubName", "") or data.get("OrganizationName", "") or "").strip()
                if not club_name:
                    stats["no_name"] += 1
                    return None

                # Build row with all data
                row = build_club_row(
                    city=city,
                    play_with=play_with,
                    age=age,
                    club_name=club_name,
                    data=data,
                    contact_data=contact_data,
                    booking_contact=booking_contact,
                    week_days=week_days,
                    latitude=latitude,
                    longitude=longitude,
                    school_year=school_year,
                    football_type=football_type,
                    disability_option=disability_option,
                    search_id=search_id,
                    club_id=club_id,
                )

                # ===== CLUB CACHE: Store successful result =====
                # Store all successful results (duplicate checking only)
                club_cache[club_id] = row
                logger.info(f"[CACHE STORE] Club {club_id} cached successfully")
                stats["success"] += 1
                return row

            except Exception as exception_error:
                error_str = str(exception_error)
                # Check if it's a 400 error - try fallback with recommendation data + BookingURL scraping
                if "Client error (400)" in error_str:
                    stats["other_errors"] += 1
                    logger.info(f"[{city}] Club {club_id}: 400 Bad Request - trying fallback with recommendation data + BookingURL")

                    # ===== FALLBACK: Use recommendation_data_list to build club row =====
                    if recommendation_data_list:
                        try:
                            # Use first entry for basic info
                            fallback_data = recommendation_data_list[0]

                            # Get club name from recommendation data (ClubName or OrganizationName)
                            # Handle NaN/float values from pandas
                            import math
                            def safe_get_str(data_dict, key, default=""):
                                val = data_dict.get(key, default)
                                if val is None:
                                    return default
                                if isinstance(val, float) and math.isnan(val):
                                    return default
                                return str(val).strip()

                            club_name = safe_get_str(fallback_data, "ClubName") or safe_get_str(fallback_data, "OrganizationName")

                            if not club_name:
                                logger.warning(f"[{city}] Club {club_id}: No club name in fallback data, skipping")
                                return None

                            # Collect ALL booking URLs from ALL recommendation data entries
                            booking_urls = []
                            for rec_data in recommendation_data_list:
                                booking_url = rec_data.get("BookingURL", "") or rec_data.get("BookingUrl", "") or ""
                                if booking_url and booking_url.strip():
                                    booking_urls.append(booking_url.strip())

                            # Limit booking URLs if max_booking_urls is set
                            if max_booking_urls > 0:
                                booking_urls = booking_urls[:max_booking_urls]

                            # Scrape booking URLs for contact info
                            booking_contact = {}
                            if booking_urls:
                                try:
                                    from .booking_scraper import scrape_multiple_booking_urls
                                    booking_contact = await scrape_multiple_booking_urls(booking_urls, client)
                                except Exception as e:
                                    logger.warning(f"[BOOKING SCRAPE] Error for club {club_id}: {e}")

                            # Build row with recommendation data + scraped contact info
                            row = build_club_row(
                                city=city,
                                play_with=play_with,
                                age=age,
                                club_name=club_name,
                                data=fallback_data,  # Use recommendation data as base
                                contact_data={},     # No WGS contact data available
                                booking_contact=booking_contact,
                                week_days=fallback_data.get("WeekDays", "1,2,3,4,5,6,7"),
                                latitude=fallback_data.get("Latitude", 51.5074),
                                longitude=fallback_data.get("Longitude", -0.1278),
                                school_year=fallback_data.get("SchoolYear", ""),
                                football_type=fallback_data.get("FootballType", "U10"),
                                disability_option=fallback_data.get("Disabilityoption", 3),
                                search_id=fallback_data.get("SearchId", None),
                                club_id=str(club_id),  # Use the original club_id (could be 0)
                            )

                            # Cache and return
                            club_cache[club_id] = row
                            logger.info(f"[CACHE STORE] Club {club_id} cached successfully via fallback")
                            stats["success"] += 1
                            return row

                        except Exception as fallback_error:
                            logger.warning(f"[{city}] Club {club_id}: Fallback failed: {fallback_error}")

                    logger.warning(f"[{city}] Club {club_id}: 400 Bad Request - skipping (no retry)")
                    return None

                stats["other_errors"] += 1
                club_name = (data.get("ClubName", "") or data.get("OrganizationName", "") or "").strip() if 'data' in locals() and isinstance(data, dict) else "Unknown"
                log_error_with_context(
                    logger, f"Exception in fetch_club_info: {exception_error}",
                    city=city, club_id=club_id, club_name=club_name, attempt=attempt+1, error=exception_error
                )
                await asyncio.sleep(min(0.5 * (2 ** attempt) + random.random(), 10.0))
        stats["failed"] += 1
        return None