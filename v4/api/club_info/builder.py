"""
Club row building for v4 crawler - builds the final ClubRow from API data.
"""
from typing import Dict, Any, List
from v4.types import ClubRow


def build_club_row(
    city: str,
    play_with: int,
    age: int,
    club_name: str,
    data: Dict[str, Any],
    contact_data: Dict[str, Any],
    booking_contact: Dict[str, Any],
    week_days: str,
    latitude: float,
    longitude: float,
    school_year: str,
    football_type: str,
    disability_option: int,
    search_id: str,
    club_id: str,
    booking_url: str = "",
) -> ClubRow:
    """
    Build a ClubRow from all available data sources.

    Priority for contact fields:
    1. Contact API data (contact_data)
    2. Booking URL scraped data (booking_contact)
    3. Club info API data (data)
    """
    teams_info = data.get("TeamsInfo", {}) or {}
    football_types_list = []
    football_types_list.extend(teams_info.get("FootballType", []) or [])
    football_types_list.extend(teams_info.get("Gender", []) or [])
    football_types_list.extend(teams_info.get("DisabilityType", []) or [])

    # Merge contact info with priority: contact_data > booking_contact > data
    contact_name = contact_data.get("individualName", "") or booking_contact.get("contact_name", "") or ""
    contact_phone = contact_data.get("phone", "") or booking_contact.get("phone", "") or data.get("TelephoneNumber", "") or ""
    contact_email = contact_data.get("email", "") or booking_contact.get("email", "") or data.get("EmailAddress", "") or ""
    contact_website = contact_data.get("website", "") or booking_contact.get("website", "") or data.get("Website", "") or ""

    # Booking URL scraped fields
    booking_venue = booking_contact.get("venue", "")
    booking_address = booking_contact.get("address", "")

    # Construct the Club URL:
    # - For ClubId=0: use booking_url
    # - For valid ClubId: use https://find.englandfootball.com/club/{club_id}
    if club_id not in (0, "0"):
        club_url = f"https://find.englandfootball.com/club/{club_id}"
    else:
        club_url = booking_url

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
        "Contact Name": contact_name,
        "Contact Phone": contact_phone,
        "Contact Email": contact_email,
        "Contact Website": contact_website,
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
        # Booking URL scraped fields
        "BookingVenue": booking_venue,
        "BookingAddress": booking_address,
        "ClubURL": club_url,
    }

    return row