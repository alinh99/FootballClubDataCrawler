"""
Booking URL scraping for v4 crawler - extracts contact info from static booking pages using SeleniumBase.
"""
import os
import re
import logging
import asyncio
from typing import Dict, List, Optional, Set

# Set custom driver path to avoid permission issues with system Python site-packages
DRIVER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "drivers")
os.environ.setdefault("SELENIUMBASE_DRIVER_PATH", DRIVER_PATH)

from bs4 import BeautifulSoup
from v4.eta import PhaseETACalculator, ETACalculator

logger = logging.getLogger(__name__)

# Global semaphore to ensure booking URLs are scraped sequentially (one at a time)
_booking_scraper_semaphore = asyncio.Semaphore(1)


def _scrape_booking_url_sync(booking_url: str) -> Dict[str, str]:
    """
    Synchronous function to scrape booking URL using SeleniumBase.
    Runs in a thread pool to avoid blocking the event loop.
    """
    from seleniumbase import Driver
    import time

    contact_info = {}
    driver = None
    max_driver_retries = 3

    for driver_attempt in range(max_driver_retries):
        try:
            # Create undetected Chrome driver with stealth options
            driver = Driver(
                uc=True,           # Undetected ChromeDriver mode
                headless=True,     # Run headless
                incognito=True,    # Clean session each time
                disable_csp=True,  # Disable Content Security Policy
                page_load_strategy="eager",  # Don't wait for all resources
                browser="chrome",
            )

            # Set timeouts
            driver.set_page_load_timeout(30)
            driver.implicitly_wait(10)

            logger.info(f"[BOOKING SCRAPE] Navigating to {booking_url}")
            driver.get(booking_url)
            break  # Success, exit retry loop

        except Exception as e:
            logger.warning(f"[BOOKING SCRAPE] Driver creation/navigation failed (attempt {driver_attempt + 1}/{max_driver_retries}): {e}")
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = None
            if driver_attempt == max_driver_retries - 1:
                raise
            time.sleep(2 * (driver_attempt + 1))  # Exponential backoff: 2s, 4s
            continue

    try:

        # Wait for page to load and potential Cloudflare challenge to resolve
        # SeleniumBase's uc mode handles Cloudflare automatically
        time.sleep(5)  # Initial wait for page to start loading

        # Send Tab + Enter to interact with potential Cloudflare challenge (checkbox/button)
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.common.keys import Keys
            actions = ActionChains(driver)
            actions.send_keys(Keys.TAB).perform()
            time.sleep(0.5)
            actions.send_keys(Keys.SPACE).perform()
            logger.info(f"[BOOKING SCRAPE] Sent Tab + Space for challenge interaction")
            time.sleep(3)  # Wait for interaction to take effect
        except Exception as e:
            logger.debug(f"[BOOKING SCRAPE] Tab+Space interaction failed (continuing): {e}")

        # Check for Cloudflare challenge page
        if _is_cloudflare_challenge(driver.page_source):
            logger.warning(f"[BOOKING SCRAPE] Cloudflare challenge detected for {booking_url}. Retrying after delay.")
            driver.refresh()
            time.sleep(5)  # Wait for page to load
            try:
                from selenium.webdriver.common.action_chains import ActionChains
                from selenium.webdriver.common.keys import Keys
                actions = ActionChains(driver)
                actions.send_keys(Keys.TAB).perform()
                time.sleep(0.5)
                actions.send_keys(Keys.SPACE).perform()
                logger.info(f"[BOOKING SCRAPE] Sent Tab + Space for challenge interaction")
                time.sleep(3)  # Wait for interaction to take effect
            except Exception as e:
                logger.debug(f"[BOOKING SCRAPE] Tab+Space interaction failed (continuing): {e}")

        page_source = driver.page_source

        # Parse the page
        soup = BeautifulSoup(page_source, 'html.parser')
        page_text = soup.get_text('\n', strip=True)

        # --- Parse structured format from book.englandfootball.com ---
        lines = [line.strip() for line in page_text.split('\n') if line.strip()]

        # Skip navigation/menu items at the top
        skip_patterns = [
            'clubspark', 'skip to content', 'sign in', 'register',
            'back to search results', 'about this opportunity',
            'choose your sessions', 'select all', 'where to find us',
            'get directions'
        ]

        def is_skip_line(line):
            line_lower = line.lower()
            return any(pattern in line_lower for pattern in skip_patterns)

        # Filter out navigation/menu lines
        content_lines = [line for line in lines if not is_skip_line(line)]

        contact_info['booking_url'] = booking_url

        # Extract venue - look for known venue indicators
        # Venue often appears as: "Hayesfield Girls School" or similar school/venue names
        # It might appear after "Where to find us" or in session details
        venue = None
        for line in content_lines:
            # Look for school/venue patterns (contains "School", "Centre", "Club", "Academy", etc.)
            if any(keyword in line.lower() for keyword in ['school', 'centre', 'center', 'club', 'academy', 'stadium', 'ground', 'pitch', 'facility', 'hall', 'park', 'leisure']):
                # Exclude lines that are clearly dates/times/prices
                if not re.search(r'\d{1,2}:\d{2}', line) and '£' not in line and not re.search(r'\d{1,2} \w+ \d{4}', line):
                    venue = line
                    break

        # If not found, try to get from session details (lines with venue names repeated)
        if not venue:
            # Look for lines that appear multiple times (venue names repeat in session listings)
            from collections import Counter
            line_counts = Counter(content_lines)
            for line, count in line_counts.most_common():
                if count > 1 and len(line) > 3:
                    # Exclude dates, times, prices
                    if not re.search(r'\d{1,2}:\d{2}', line) and '£' not in line and not re.search(r'\d{1,2} \w+ \d{4}', line):
                        venue = line
                        break

        # Final fallback: first non-trivial content line
        if not venue:
            for line in content_lines:
                if len(line) > 5 and not re.search(r'^[\d\s:\-\/]+$', line):
                    venue = line
                    break

        if venue:
            contact_info['venue'] = venue

        # Extract address - look for UK postcode pattern
        # UK postcode pattern: A(A) 9(9) AA (e.g., BA2 3LA, SW1A 1AA)
        postcode_pattern = r'[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}'
        address = None
        for line in content_lines:
            if re.search(postcode_pattern, line, re.IGNORECASE):
                address = line
                break

        # If not found, look for address-like patterns (contains street, lane, road, etc.)
        if not address:
            address_keywords = ['lane', 'road', 'street', 'avenue', 'drive', 'close', 'way', 'place', 'court', 'grove', 'gardens', 'park', 'hill', 'view', 'terrace', 'crescent', 'square', 'mews', 'vale', 'rise', 'row', 'walk', 'path']
            for line in content_lines:
                line_lower = line.lower()
                if any(kw in line_lower for kw in address_keywords) and ',' in line:
                    # Looks like an address
                    if not re.search(r'\d{1,2}:\d{2}', line) and '£' not in line:
                        address = line
                        break

        if address:
            contact_info['address'] = address

        # Extract Coach, Email, Phone using patterns
        for line in lines:
            # Coach name
            coach_match = re.match(r'Coach:\s*(.+)', line, re.IGNORECASE)
            if coach_match:
                contact_info['contact_name'] = coach_match.group(1).strip()
                continue

            # Email
            email_match = re.match(r'Email:\s*(.+)', line, re.IGNORECASE)
            if email_match:
                contact_info['email'] = email_match.group(1).strip()
                continue

            # Phone
            phone_match = re.match(r'Phone:\s*(.+)', line, re.IGNORECASE)
            if phone_match:
                contact_info['phone'] = phone_match.group(1).strip()
                continue

            # Website
            website_match = re.match(r'Website:\s*(.+)', line, re.IGNORECASE)
            if website_match:
                contact_info['website'] = website_match.group(1).strip()
                continue

        # Fallback: regex extraction from full text
        if 'email' not in contact_info:
            email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', page_text)
            if email_match:
                contact_info['email'] = email_match.group(0)

        if 'phone' not in contact_info:
            phone_patterns = [
                r'Phone[:\s]*([+]?[\d\s\-\(\)]{8,})',
                r'\b(0\d{3,4}\s?\d{3,4})\b',  # UK format
                r'\+44\s?\d{3,4}\s?\d{3,4}',  # UK international
            ]
            for pattern in phone_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    contact_info['phone'] = match.group(1).strip()
                    break

        if 'contact_name' not in contact_info:
            name_patterns = [
                r'Coach[:\s]*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
                r'(?:Contact|Manager|Organiser|Organizer)[:\s]*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
            ]
            for pattern in name_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    contact_info['contact_name'] = match.group(1).strip()
                    break

        # Also try structured data (schema.org, JSON-LD)
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                import json
                # Skip empty script tags (script.string can be None)
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if data.get('@type') in ['Organization', 'LocalBusiness', 'SportsClub']:
                        contact_info.setdefault('phone', data.get('telephone', ''))
                        contact_info.setdefault('email', data.get('email', ''))
                        contact_info.setdefault('website', data.get('url', ''))
                        if 'address' in data and 'address' not in contact_info:
                            addr = data['address']
                            if isinstance(addr, dict):
                                # Convert all parts to strings to handle numeric values (e.g., postalCode as number)
                                parts = [
                                    str(addr.get('streetAddress', '')),
                                    str(addr.get('addressLocality', '')),
                                    str(addr.get('postalCode', ''))
                                ]
                                # Filter out empty strings and "None" strings
                                filtered_parts = [p for p in parts if p and p.lower() != 'none']
                                contact_info['address'] = ', '.join(filtered_parts)
            except Exception:
                pass

        # Clean up empty values
        contact_info = {k: v for k, v in contact_info.items() if v}

        logger.info(f"[BOOKING SCRAPE] Extracted from {booking_url}: {contact_info}")

    except Exception as e:
        logger.warning(f"[BOOKING SCRAPE] Error scraping {booking_url}: {e}")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return contact_info


# Cloudflare challenge detection (English + Vietnamese)
CLOUDFLARE_INDICATORS = [
    "chờ một chút",       # Vietnamese: "wait a moment"
    "Đã phát hiện thấy thay đổi mạng.",  # Vietnamese: "Network change detected."
]


def _is_cloudflare_challenge(html: str) -> bool:
    """Check if the response is a Cloudflare challenge page."""
    html_lower = html.lower()
    return any(indicator in html_lower for indicator in CLOUDFLARE_INDICATORS)


async def scrape_booking_url_for_contact(booking_url: str, _client=None,
                                          crawled_booking_urls: Optional[Set[str]] = None,
                                          crawled_club_names: Optional[Set[str]] = None,
                                          club_name: Optional[str] = None) -> Dict[str, str]:
    """
    Scrape the BookingURL static page for contact information using SeleniumBase.

    Expected page format (from book.englandfootball.com):
    SOUTH BRISTOL SPORTS CENTRE
    west town lane, BS149EA

    Get directions

    Need more information?
    Coach: Kyle Nicholls

    Email: kyle.nicholls@bcfc.co.uk

    Phone: 07484 039800

    Returns dict with: phone, email, website, address, contact_name, venue

    Args:
        booking_url: The booking URL to scrape
        client: Ignored (kept for API compatibility with old signature)
        crawled_booking_urls: Set of already crawled booking URLs to skip
        crawled_club_names: Set of already crawled club names to skip
        club_name: Current club name being processed (for logging)
    """
    # Handle NaN/float values
    import math
    if booking_url is None:
        return {}
    if isinstance(booking_url, float) and math.isnan(booking_url):
        return {}
    booking_url = str(booking_url).strip()
    if not booking_url:
        return {}

    # Skip if club name or booking URL already crawled (phase 2 only mode)
    if crawled_club_names and club_name and club_name in crawled_club_names:
        logger.info(f"[BOOKING SCRAPE] Skipping already crawled club: {club_name} (URL: {booking_url})")
        return {}
    if crawled_booking_urls and booking_url in crawled_booking_urls:
        logger.info(f"[BOOKING SCRAPE] Skipping already crawled booking URL: {booking_url}")
        return {}

    # Run selenium in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _scrape_booking_url_sync, booking_url)
    except Exception as e:
        logger.warning(f"[BOOKING SCRAPE] Error scraping {booking_url}: {e}")
        return {}


async def scrape_multiple_booking_urls(booking_urls: List[str], _client=None, booking_eta: Optional[ETACalculator] = None,
                                       crawled_club_names: Optional[Set[str]] = None,
                                       crawled_booking_urls: Optional[Set[str]] = None,
                                       club_name: Optional[str] = None) -> Dict[str, str]:
    """
    Scrape multiple booking URLs and merge the results.
    Takes the first non-empty value for each field.

    Args:
        booking_urls: List of booking URLs to scrape
        client: Ignored (kept for API compatibility)
        booking_eta: Optional shared ETACalculator for tracking progress across all clubs
        crawled_club_names: Set of already crawled club names to skip
        crawled_booking_urls: Set of already crawled booking URLs to skip
        club_name: Current club name being processed (for logging)

    Returns:
        Merged contact info dict with: phone, email, website, address, contact_name, venue
    """
    if not booking_urls:
        return {}

    merged_contact = {}
    total_urls = len(booking_urls)

    # Use shared ETA calculator if provided, otherwise create local one
    use_shared_eta = booking_eta is not None
    local_eta = None
    if not use_shared_eta:
        local_eta = PhaseETACalculator(total_combos=1)
        local_eta.start_phase2(total_urls)
        booking_eta = local_eta.phase2_eta

    for idx, booking_url in enumerate(booking_urls, 1):
        # Ensure booking_url is a string and handle NaN/float values
        import math
        if booking_url is None:
            logging.warning(f"[BOOKING SCRAPE] Skipping None booking URL at index {idx}/{total_urls} (URL: {booking_url})")
            continue
        if isinstance(booking_url, float) and math.isnan(booking_url):
            logging.warning(f"[BOOKING SCRAPE] Skipping NaN booking URL at index {idx}/{total_urls} (URL: {booking_url})")
            continue
        booking_url = str(booking_url).strip()
        if not booking_url:
            continue

        # Skip if club name or booking URL already crawled (phase 2 only mode)
        if crawled_club_names and club_name and club_name in crawled_club_names:
            logger.info(f"[BOOKING SCRAPE] Skipping already crawled club: {club_name} (URL: {booking_url})")
            if use_shared_eta:
                booking_eta.update(idx)
                booking_eta.log_progress(logger, f"[BOOKING SCRAPE] ", force=False)
            else:
                booking_eta.update(idx)
                booking_eta.log_progress(logger, f"[BOOKING SCRAPE] ", force=False)
            continue
        if crawled_booking_urls and booking_url in crawled_booking_urls:
            logger.info(f"[BOOKING SCRAPE] Skipping already crawled booking URL: {booking_url}")
            if use_shared_eta:
                booking_eta.update(idx)
                booking_eta.log_progress(logger, f"[BOOKING SCRAPE] ", force=False)
            else:
                booking_eta.update(idx)
                booking_eta.log_progress(logger, f"[BOOKING SCRAPE] ", force=False)
            continue

        try:
            logger.info(f"[BOOKING SCRAPE] Processing URL {idx}/{total_urls}: {booking_url}")
            # Use semaphore to ensure sequential execution globally
            async with _booking_scraper_semaphore:
                contact = await scrape_booking_url_for_contact(booking_url, _client)
            # Merge: take first non-empty value for each field
            for key, value in contact.items():
                if value and key not in merged_contact:
                    merged_contact[key] = value

            # Update booking ETA
            if use_shared_eta:
                booking_eta.update(idx)
                booking_eta.log_progress(logger, f"[BOOKING SCRAPE] ", force=False)
            else:
                booking_eta.update(idx)
                booking_eta.log_progress(logger, f"[BOOKING SCRAPE] ", force=False)

            # Small delay between requests to avoid overwhelming the server
            if idx < total_urls:
                await asyncio.sleep(2)

        except Exception as e:
            logger.warning(f"[BOOKING SCRAPE] Error scraping URL {idx}/{total_urls} ({booking_url}): {e}")
            # Still update ETA for failed URL
            if use_shared_eta:
                booking_eta.update(idx)
                booking_eta.log_progress(logger, f"[BOOKING SCRAPE] ", force=False)
            else:
                booking_eta.update(idx)
                booking_eta.log_progress(logger, f"[BOOKING SCRAPE] ", force=False)
            continue

    if use_shared_eta:
        booking_eta.update(total_urls)
        booking_eta.log_progress(logger, f"[BOOKING SCRAPE] ", force=True)
    else:
        booking_eta.update(total_urls)
        booking_eta.log_progress(logger, f"[BOOKING SCRAPE] ", force=True)

    return merged_contact