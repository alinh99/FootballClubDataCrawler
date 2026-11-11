"""
Club Info API for v4 crawler: fetch detailed club information.
"""
import asyncio
import random
import logging
from typing import Dict, List, Optional, Set

from curl_cffi import AsyncSession
from fake_useragent import UserAgent

from v4.config import (
    API_CLUB_INFO_URL, API_CLUB_CONTACT_URL,
    KEY_CLUB_INFO_AND_RECOMMENDATION_INFO, KEY_CLUB_CONTACT_INFO,
    RATE_LIMIT_SLEEP, TOTAL_RETRIES
)
from v4.models import AdaptiveLimiter
from v4.types import (
    CityName, ClubId, ClubRow, StatsDict, ClubInfoPayload, ClubCache
)
from v4.utils.logging import log_error_with_context

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
    search_id: Optional[str] = None
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
        # Verify cached row has the required fields and matches requested club_id
        # Use "is not None" to handle ClubId=0 correctly (0 is falsy but valid)
        cached_club_id = cached_row.get("ClubId") if isinstance(cached_row, dict) else None
        if (isinstance(cached_row, dict)
            and cached_club_id is not None
            and cached_club_id == club_id):  # Ensure cached ClubId matches requested
            stats["skipped_cache"] += 1
            logger.info(f"[CACHE HIT] Club {club_id} found in cache, skipping API call")
            return cached_row
        else:
            # Invalid cache entry or ClubId mismatch, remove it
            logger.warning(f"[CACHE INVALID] Club {club_id}: cached={cached_club_id}, removing")
            del club_cache[club_id]

    payload: ClubInfoPayload = {
        "ClubId": club_id,
        "Age": age,
        "PlayWith": play_with,
        "DisabilityType": disability_type,
        "Disabilityoption": disability_option,
        "FootballType": football_type,
        "WeekDays": week_days,
        "Latitude": latitude,
        "Longitude": longitude,
        "SchoolYear": school_year,
    }

    headers_base = {
        "Accept": "application/json; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "User-Agent": UserAgent().random,
        "Ocp-Apim-Subscription-Key": KEY_CLUB_INFO_AND_RECOMMENDATION_INFO,
        "Host": "hcdeapimngt1.azure-api.net",
        "Origin": "https://find.englandfootball.com",
        "Referer": "https://find.englandfootball.com/",
        "Sec-Fetch-Site": "same-site",
    }

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
                else:
                    headers = {
                        **headers_base,
                        "User-Agent": f"sb/{random.randint(1, 1000)}",
                        "Ocp-Apim-Subscription-Key": KEY_CLUB_INFO_AND_RECOMMENDATION_INFO
                    }
                    resp = await client.post(API_CLUB_INFO_URL, json=payload, headers=headers, timeout=300.0)
                    if resp.status_code in (401, 403):
                        raise Exception(f"Auth failed ({resp.status_code}): Check API key")
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

                    club_name = (data.get("ClubName", "") or "").strip()
                    contact_data = {}
                    wgs_id = data.get("WgsClubId")
                    if wgs_id:
                        try:
                            contact_base = API_CLUB_CONTACT_URL
                            contact_resp = await client.get(
                                f"{contact_base}/{wgs_id}/clubcontact",
                                headers={
                                    "Ocp-Apim-Subscription-Key": KEY_CLUB_CONTACT_INFO,
                                    "User-Agent": f"scraper-bot/{random.randint(1, 1000)}"
                                },
                                timeout=300.0
                            )
                            if contact_resp.status_code == 200:
                                content_type = contact_resp.headers.get("Content-Type", "")
                                if "application/json" in content_type and contact_resp.content:
                                    contact_data = contact_resp.json()
                                else:
                                    logger.warning(f"Contact API non-JSON ({contact_resp.status_code}): {contact_resp.text[:100]}")
                        except Exception as e:
                            logger.info(f"Contact API error for {wgs_id}: {e}")

                club_name = (data.get("ClubName", "") or "").strip()
                if not club_name:
                    stats["no_name"] += 1
                    return None

                teams_info = data.get("TeamsInfo", {}) or {}
                football_types_list = []
                football_types_list.extend(teams_info.get("FootballType", []) or [])
                football_types_list.extend(teams_info.get("Gender", []) or [])
                football_types_list.extend(teams_info.get("DisabilityType", []) or [])

                # Build row with all recommendation fields included
                row: ClubRow = {
                    "City": city,
                    "PlayWith": play_with,
                    "Age": age,
                    "Club Name": club_name,
                    "Club Address": ", ".join(filter(None, [
                        data.get("AddressLine1", ""),
                        data.get("City", ""),
                        data.get("PostCode", "")
                    ])),
                    "Accredited To": data.get("ClubCounty", "") or "",
                    "Football Types": ", ".join(filter(None, football_types_list)),
                    "Team Numbers": data.get("TeamsCount", 0) or 0,
                    "Contact Name": contact_data.get("individualName", "") or "",
                    "Contact Phone": contact_data.get("phone", "") or  data.get("TelephoneNumber", "") or "",
                    "Contact Email": contact_data.get("email", "") or data.get("EmailAddress", "") or "",
                    "Contact Website": contact_data.get("website", "") or data.get("Website", "") or "",
                    # Recommendation fields from payload
                    "WeekDays": week_days,
                    "Latitude": latitude,
                    "Longitude": longitude,
                    "SchoolYear": school_year,
                    "FootballType": football_type,
                    "DisabilityOption": disability_option,
                    "SearchId": search_id,
                    # Additional fields from API response
                    "WgsClubId": data.get("WgsClubId", "") or "",
                    "ClubId": data.get("ClubId", club_id) or club_id,
                    "GroundName": data.get("GroundName", "") or "",
                }

                # ===== CLUB CACHE: Store successful result =====
                # Only cache if we have a valid club_id (not 0, None, empty)
                # and the response contains a valid ClubId to avoid collisions
                response_club_id = data.get("ClubId", club_id)
                if club_id and response_club_id not in (0, None, "", "0"):
                    club_cache[club_id] = row
                    logger.info(f"[CACHE STORE] Club {club_id} cached successfully")
                elif club_id in (0, None, "", "0"):
                    logger.warning(f"[CACHE SKIP] Invalid club_id={club_id}, not caching to avoid collisions")
                else:
                    logger.warning(f"[CACHE SKIP] Response ClubId={response_club_id} invalid, not caching")
                stats["success"] += 1
                return row

            except Exception as exception_error:
                stats["other_errors"] += 1
                club_name = (data.get("ClubName", "") or "").strip() if 'data' in locals() and isinstance(data, dict) else "Unknown"
                log_error_with_context(
                    logger, f"Exception in fetch_club_info: {exception_error}",
                    city=city, club_id=club_id, club_name=club_name, attempt=attempt+1, error=exception_error
                )
                await asyncio.sleep(min(0.5 * (2 ** attempt) + random.random(), 10.0))
        stats["failed"] += 1
        return None