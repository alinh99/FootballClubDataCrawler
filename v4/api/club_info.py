"""
Club Info API for v4 crawler: fetch detailed club information.
"""
import asyncio
import random
import logging
from typing import Dict, Optional, Set

from curl_cffi import AsyncSession
from fake_useragent import UserAgent

from v4.config import (
    API_CLUB_INFO_URL, API_CLUB_CONTACT_URL,
    KEY_CLUB_INFO_AND_RECOMMENDATION_INFO, KEY_CLUB_CONTACT_INFO,
    RATE_LIMIT_SLEEP, TOTAL_RETRIES
)
from v4.models import AdaptiveLimiter
from v4.types import (
    CityName, ClubId, ComboKey, ClubCache, ExistingClubNames,
    ClubRow, StatsDict, ClubInfoPayload
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
    existing_club_names: ExistingClubNames,
    combo_key: ComboKey,
    club_cache: ClubCache,
    processed_clubs_local: Dict[ComboKey, Set[ClubId]],
    stats: StatsDict,
    dry_run: bool = False
) -> Optional[ClubRow]:
    """
    Fetch detailed club information from the club info API.
    """
    payload: ClubInfoPayload = {
        "ClubId": club_id,
        "Age": age,
        "PlayWith": play_with,
    }

    headers_base = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "User-Agent": UserAgent().random,
        "Ocp-Apim-Subscription-Key": KEY_CLUB_INFO_AND_RECOMMENDATION_INFO
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
                        "WgsClubId": None
                    }
                    contact_data = {}
                else:
                    headers = {
                        **headers_base,
                        "User-Agent": f"scraper-bot/{random.randint(1, 1000)}",
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
                    if city in existing_club_names and club_name in existing_club_names[city]:
                        stats["skipped_name"] += 1
                        logger.warning(f"[SKIP] Club '{club_name}' already exists in city '{city}'. Skipping.")
                        return None
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
                            logger.debug(f"Contact API error for {wgs_id}: {e}")

                club_name = (data.get("ClubName", "") or "").strip()
                if not club_name:
                    stats["no_name"] += 1
                    return None

                if city in existing_club_names and club_name in existing_club_names[city]:
                    stats["skipped_name"] += 1
                    logger.warning(f"[SKIP] Club '{club_name}' already exists in city '{city}'. Skipping.")
                    return None

                teams_info = data.get("TeamsInfo", {}) or {}
                football_types_list = []
                football_types_list.extend(teams_info.get("FootballType", []) or [])
                football_types_list.extend(teams_info.get("Gender", []) or [])
                football_types_list.extend(teams_info.get("DisabilityType", []) or [])

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
                    "Contact Phone": contact_data.get("phone", "") or "",
                    "Contact Email": contact_data.get("email", "") or "",
                    "Contact Website": contact_data.get("website", "") or ""
                }

                existing_club_names.setdefault(city, set()).add(club_name)
                club_cache[club_id] = row
                processed_clubs_local.setdefault(combo_key, set()).add(club_id)
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