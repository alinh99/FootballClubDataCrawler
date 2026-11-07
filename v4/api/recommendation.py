"""
Recommendation API for v4 crawler: fetch recommendation pages and extract club IDs.
"""
import asyncio
import random
import logging
import json as _json
from typing import List, Optional, Union, Dict, Any

from curl_cffi import requests as curl_requests

from v4.config import (
    API_CLUB_RECOMMENDATION_URL,
    KEY_CLUB_INFO_AND_RECOMMENDATION_INFO,
    DEFAULT_LAT, DEFAULT_LON, CITY_COORDS, TOTAL_RETRIES
)
from v4.types import (
    CityName, RecommendationResponse, ClubsList,
    RecommendationPayload
)
from v4.utils.logging import log_error_with_context

logger = logging.getLogger(__name__)


def extract_clubids_from_recommendation(
    api_general_info_data: Union[List[RecommendationResponse], RecommendationResponse]
) -> ClubsList:
    """
    Extract club IDs from recommendation API response (legacy function for backward compatibility).

    API returns: {"CntOpportunity": N, "RecommendationClubCentreCartDto": [...]}
    Each item in RecommendationClubCentreCartDto has ClubId and other fields.
    """
    clubs: ClubsList = []

    # Handle both old format (list of objects) and new format (single object with CentreCartDto)
    if not api_general_info_data:
        return clubs

    # If it's a list (old format), iterate through each item
    if isinstance(api_general_info_data, list):
        for d in api_general_info_data:
            # Try both possible keys
            for key in ["RecommendationClubCentreCartDto", "RecommendationClubCartDto"]:
                for c in d.get(key, []) or []:
                    cid = c.get("ClubId", "")
                    # Allow ClubId = 0 (0 is valid, only skip None/empty string)
                    if cid is not None and cid != "":
                        clubs.append({cid: d.get("FootballType", "")})
    # If it's a dict (new format), process directly
    elif isinstance(api_general_info_data, dict):
        for key in ["RecommendationClubCentreCartDto", "RecommendationClubCartDto"]:
            for c in api_general_info_data.get(key, []) or []:
                cid = c.get("ClubId", "")
                # Allow ClubId = 0 (0 is valid, only skip None/empty string)
                if cid is not None and cid != "":
                    clubs.append({cid: api_general_info_data.get("FootballType", "")})

    return clubs


def extract_full_club_data_from_recommendation(
    api_general_info_data: Union[List[RecommendationResponse], RecommendationResponse]
) -> List[Dict[str, Any]]:
    """
    Extract ALL available fields from recommendation API response.

    Returns a list of dictionaries with all club data fields from the recommendation API.
    This includes: ClubId, ClubName, WgsClubId, TeamCount, DistanceFromUserLocation,
    DiscoverFootballType, Disability, PlaysOnDay, Gender, Category, FootballType,
    Longitude, Latitude, AddressLine1, AddressLine2, AddressLine3, PostCode, City,
    and many more fields.
    """
    clubs: List[Dict[str, Any]] = []

    if not api_general_info_data:
        return clubs

    # If it's a list (old format), iterate through each item
    if isinstance(api_general_info_data, list):
        for d in api_general_info_data:
            # Try both possible keys
            for key in ["RecommendationClubCentreCartDto", "RecommendationClubCartDto"]:
                for c in d.get(key, []) or []:
                    cid = c.get("ClubId", "")
                    if cid is not None and cid != "":
                        # Copy all fields from the club item
                        club_data = dict(c)
                        # Add FootballType from parent if not present
                        if "FootballType" not in club_data:
                            club_data["FootballType"] = d.get("FootballType", "")
                        clubs.append(club_data)
    # If it's a dict (new format), process directly
    elif isinstance(api_general_info_data, dict):
        for key in ["RecommendationClubCentreCartDto", "RecommendationClubCartDto"]:
            for c in api_general_info_data.get(key, []) or []:
                cid = c.get("ClubId", "")
                if cid is not None and cid != "":
                    club_data = dict(c)
                    if "FootballType" not in club_data:
                        club_data["FootballType"] = api_general_info_data.get("FootballType", "")
                    clubs.append(club_data)

    return clubs


async def fetch_recommendation_pages(city: CityName, dry_run: bool = False) -> List[RecommendationResponse]:
    """
    Fetch all pages of club recommendations for a city.
    Returns list of API response objects.
    """
    if dry_run:
        return [{"RecommendationClubCartDto": [{"ClubId": f"DRY_{city}_{i}"} for i in range(25)], "FootballType": "DRY"}]

    loop = asyncio.get_event_loop()

    # Get city coordinates
    city_coords = CITY_COORDS.get(city, {"lat": DEFAULT_LAT, "lon": DEFAULT_LON})
    latitude = city_coords["lat"]
    longitude = city_coords["lon"]

    # Payload template with all fields from website analysis (default values)
    # PageNumber will increment, PageSize=12
    base_payload: RecommendationPayload = {
        "SearchForUser": "",
        "Age": 0,
        "PlayWith": 4,  # Website default (4 = all football types)
        "FootballType": 4,
        "FootballTypeAllNone": "None",
        "WeekDays": "1,2,3,4,5,6,7",
        "Disabilityoption": 3,
        "DisabilityType": [],
        "SelectedDisabilityType": "",
        "Distance": 10,
        "OptforCurrentLocation": "No",
        "Latitude": latitude,
        "Longitude": longitude,
        "Programs": "Comets,DisabilityRec,JustPlayKickabout,JustPlayLearnToPlay,SquadGirlsFootball,Wildcats",
        "RawPrograms": [],
        "WaysToPlay": "1,2,3",
        "RawWaysToPlay": [],
        "PageSize": 12,
        "RawWeekDays": [],
        "SchoolYear": "",
        "ReadableLocation": city,
        "SearchId": "",
        "SelectedFootballType": 4,
        "SurfaceType": "3G or Astroturf,Grass,Indoor,Others",
        "quickSearch": True,
    }

    def fetch_page(page_number: int) -> Optional[RecommendationResponse]:
        """Fetch a single page of results"""
        headers = {
            "User-Agent": f"scraper-bot/{random.randint(1, 1000)}",
            "Ocp-Apim-Subscription-Key": KEY_CLUB_INFO_AND_RECOMMENDATION_INFO
        }
        payload = {**base_payload, "PageNumber": page_number}
        with curl_requests.Session(impersonate="chrome120", headers=headers, timeout=300.0) as client:
            resp = client.post(API_CLUB_RECOMMENDATION_URL, json=payload)
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

    all_results: List[RecommendationResponse] = []
    page = 1
    max_pages = 50  # Safety limit

    while page <= max_pages:
        for current_retry in range(TOTAL_RETRIES):
            try:
                result = await loop.run_in_executor(None, fetch_page, page)
                if result is None:
                    # 204 No Content - no more pages
                    return all_results
                if result:
                    all_results.append(result)
                    # Check if we got fewer results than page size (last page)
                    clubs_in_page = extract_clubids_from_recommendation([result]) if isinstance(result, dict) else extract_clubids_from_recommendation(result)
                    if len(clubs_in_page) < 12:
                        # Last page, stop pagination
                        return all_results
                page += 1
                break
            except Exception as e:
                log_error_with_context(
                    logger, f"Page {page} failed: {e}",
                    city=city, page=page, attempt=current_retry+1, error=e, level="warning"
                )
                await asyncio.sleep(min(0.5 * (2 ** current_retry) + random.random(), 10.0))

    return all_results