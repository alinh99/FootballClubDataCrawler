"""
Recommendation API payload building for v4 crawler.
"""
from typing import Dict, Any, List
from v4.config import CITY_COORDS, DEFAULT_LAT, DEFAULT_LON
from v4.types import RecommendationPayload, CityName


def build_recommendation_payload(city: CityName) -> RecommendationPayload:
    """
    Build the recommendation API payload matching the website exactly.

    Website payload structure:
    - SearchForUser: ""
    - Age: "" (empty string as per website)
    - PlayWith: 7 (hardcoded to 7 as per website)
    - FootballType: 4
    - FootballTypeAllNone: "All"
    - WeekDays: "1,2,3,4,5,6,7"
    - Disabilityoption: 3
    - DisabilityType: []
    - SelectedDisabilityType: ""
    - Distance: 200
    - OptforCurrentLocation: "No"
    - Latitude/Longitude: from city coords
    - Programs: comma-separated string
    - RawPrograms: array of program names
    - WaysToPlay: "1,2,3"
    - RawWaysToPlay: ["1", "2", "3"]
    - RawWeekDays: ["1", "2", "3", "4", "5", "6", "7"]
    - PageSize: 12 
    - SchoolYear: ""
    - ReadableLocation: city name
    - SearchId: "55532411-57f1-4bc0-bed4-49e268b32622" (fixed as per website)
    - SelectedFootballType: 4
    - SurfaceType: "3G or Astroturf,Grass,Indoor,Others"
    - quickSearch: True
    """
    city_coords = CITY_COORDS.get(city, {"lat": DEFAULT_LAT, "lon": DEFAULT_LON})
    latitude = city_coords["lat"]
    longitude = city_coords["lon"]

    return {
        "SearchForUser": "",
        "Age": "",  # Empty string as per website
        "PlayWith": 7,  # Hardcoded to 7 as per website
        "FootballType": 4,
        "FootballTypeAllNone": "All",
        "WeekDays": "1,2,3,4,5,6,7",
        "Disabilityoption": 3,
        "DisabilityType": [],
        "SelectedDisabilityType": "",
        "Distance": 200,
        "OptforCurrentLocation": "No",
        "Latitude": latitude,
        "Longitude": longitude,
        "Programs": "Comets,DisabilityRec,JustPlayKickabout,JustPlayLearnToPlay,SquadGirlsFootball,Wildcats",
        "RawPrograms": ["Comets", "DisabilityRec", "JustPlayKickabout", "JustPlayLearnToPlay", "SquadGirlsFootball", "Wildcats"],
        "WaysToPlay": "1,2,3",
        "RawWaysToPlay": ["1", "2", "3"],
        "RawWeekDays": ["1", "2", "3", "4", "5", "6", "7"],
        "PageSize": 50,  # Match website payload
        "SchoolYear": "",
        "ReadableLocation": city,  # Use actual city name
        "SearchId": "55532411-57f1-4bc0-bed4-49e268b32622",  # Fixed as per website
        "SelectedFootballType": 4,
        "SurfaceType": "3G or Astroturf,Grass,Indoor,Others",
        "quickSearch": True,
    }


def build_page_payload(base_payload: RecommendationPayload, page_number: int) -> Dict[str, Any]:
    """Build payload for a specific page number."""
    return {**base_payload, "PageNumber": page_number}