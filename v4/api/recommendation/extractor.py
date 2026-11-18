"""
Recommendation API response data extraction for v4 crawler.
"""
from typing import List, Dict, Any, Union
from v4.types import RecommendationResponse, ClubsList


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
                    clubs.append({cid: d.get("FootballType", "")})
    # If it's a dict (new format), process directly
    elif isinstance(api_general_info_data, dict):
        for key in ["RecommendationClubCentreCartDto", "RecommendationClubCartDto"]:
            for c in api_general_info_data.get(key, []) or []:
                cid = c.get("ClubId", "")
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

    NO FILTER - take everything from API response
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
                    # NO FILTER - take everything from API response
                    club_data = dict(c)
                    clubs.append(club_data)
    # If it's a dict (new format), process directly
    elif isinstance(api_general_info_data, dict):
        for key in ["RecommendationClubCentreCartDto", "RecommendationClubCartDto"]:
            for c in api_general_info_data.get(key, []) or []:
                # NO FILTER - take everything from API response
                club_data = dict(c)
                clubs.append(club_data)

    return clubs


def get_cnt_opportunity(api_general_info_data: Union[List[RecommendationResponse], RecommendationResponse]) -> int:
    """Extract CntOpportunity from API response."""
    if not api_general_info_data:
        return 0

    if isinstance(api_general_info_data, list):
        # For list format, try first item
        for d in api_general_info_data:
            if isinstance(d, dict) and "CntOpportunity" in d:
                return d.get("CntOpportunity", 0)
    elif isinstance(api_general_info_data, dict):
        return api_general_info_data.get("CntOpportunity", 0)

    return 0