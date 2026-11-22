"""
Phase 1: Write ALL available club info from recommendation API immediately.
"""
import logging
from typing import List, Dict, Any

from v4.types import CityName, BasicClubRow, ClubsList
from v4.storage import async_append_basic_csv_rows

logger = logging.getLogger(__name__)


async def process_phase1(
    city: CityName,
    age: int,
    play_with: int,
    clubs_data: ClubsList
) -> List[str]:
    """
    Phase 1: Write ALL available club info from recommendation API immediately.

    Returns list of UNIQUE club_ids that need detailed fetching in Phase 2.
    (Phase 2 will scrape ALL booking URLs for each unique club from all entries)
    """
    basic_rows: List[BasicClubRow] = []
    club_ids_to_fetch_detail: List[str] = []
    total_clubs = len(clubs_data)

    if total_clubs > 0:
        logger.info(f"[{city}] Phase 1: Processing {total_clubs} clubs (Age={age}, PlayWith={play_with})")

    for idx, club_data in enumerate(clubs_data, 1):
        club_id = club_data.get("ClubId", "")
        pct = idx / total_clubs * 100
        logger.info(f"[{city}] Phase 1: Processing club {idx}/{total_clubs} ({pct:.1f}%) (ClubId={club_id})")

        # Get club name with OrganizationName fallback
        club_name = (club_data.get("ClubName", "") or club_data.get("OrganizationName", "") or "").strip()

        # Build basic row with ACTUAL combo values
        basic_row: BasicClubRow = {
            "City": city,
            "PlayWith": play_with,
            "Age": age,
            "ClubId": club_id,
            "Source": "recommendation",
            "Club Name": club_name,  # Use fallback name
        }
        # Add all fields from recommendation response
        for key, value in club_data.items():
            if key not in ("ClubId", "ClubName"):  # Already added above
                basic_row[key] = value

        basic_rows.append(basic_row)
        club_ids_to_fetch_detail.append(club_id)

    if basic_rows:
        await async_append_basic_csv_rows(basic_rows)
        logger.info(f"[{city}] Phase 1: Written {len(basic_rows)} basic club rows (Age={age}, PlayWith={play_with})")

    # Return all club_ids (preserve order) - Phase 2 will handle multiple booking URLs per club
    logger.info(f"[{city}] Phase 1: {len(club_ids_to_fetch_detail)} total entries for Phase 2")
    return club_ids_to_fetch_detail