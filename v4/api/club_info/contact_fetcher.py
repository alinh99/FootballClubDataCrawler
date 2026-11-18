"""
Contact API fetching for v4 crawler.
"""
import random
import logging
from typing import Dict, Any, Optional

from curl_cffi import AsyncSession

from v4.config import API_CLUB_CONTACT_URL, KEY_CLUB_CONTACT_INFO

logger = logging.getLogger(__name__)


async def fetch_contact_info(client: AsyncSession, wgs_id: str) -> Dict[str, Any]:
    """
    Fetch contact information from the contact API using WgsClubId.

    Returns empty dict on failure.
    """
    contact_data: Dict[str, Any] = {}

    try:
        contact_resp = await client.get(
            f"{API_CLUB_CONTACT_URL}/{wgs_id}/clubcontact",
            headers={
                "Ocp-Apim-Subscription-Key": KEY_CLUB_CONTACT_INFO,
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
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

    return contact_data