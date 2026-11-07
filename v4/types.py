"""
Type definitions and aliases for v4 crawler.
"""
from typing import Dict, List, Set, Any, Union
from dataclasses import dataclass


# Type aliases
CityName = str
ClubId = Union[int, str]
ClubName = str
Latitude = float
Longitude = float
ComboKey = str  # Format: "CityName__0"
PageNumber = int
PageSize = int

# API Response types
RecommendationClubItem = Dict[str, Any]
RecommendationResponse = Dict[str, Any]
ClubInfoResponse = Dict[str, Any]
ContactInfoResponse = Dict[str, Any]

# Internal data structures
ClubDict = Dict[ClubId, str]  # ClubId -> FootballType
ClubsList = List[ClubDict]
ExistingClubNames = Dict[CityName, Set[ClubName]]
ProcessedCombos = Set[ComboKey]
ClubCache = Dict[ClubId, Dict[str, Any]]

# Stats dictionary
StatsDict = Dict[str, int]

# City coordinates
CityCoords = Dict[str, Dict[str, float]]  # city -> {"lat": float, "lon": float}

# Payload types
RecommendationPayload = Dict[str, Any]
ClubInfoPayload = Dict[str, Any]

# Result row for CSV
ClubRow = Dict[str, Any]

# Basic club row (from recommendation API) - written immediately
BasicClubRow = Dict[str, Any]

# City processing result
@dataclass
class CityResult:
    city: CityName
    elapsed: float
    stats: StatsDict
    combos_done: int


# Worker arguments
WorkerArgs = Dict[str, Any]