"""
Club Info API payload building for v4 crawler.
"""
from typing import List, Dict
from v4.types import ClubInfoPayload, ClubId, CityName


def build_club_info_payload(
    club_id: ClubId,
    age: int,
    play_with: int,
    disability_type: List[Dict],
    disability_option: int,
    football_type: str,
    week_days: str,
    latitude: float,
    longitude: float,
    school_year: str,
) -> ClubInfoPayload:
    """Build the club info API payload."""
    return {
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


def build_club_info_headers() -> Dict[str, str]:
    """Build base headers for club info API requests."""
    from fake_useragent import UserAgent
    from v4.config import KEY_CLUB_INFO_AND_RECOMMENDATION_INFO

    return {
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