#!/usr/bin/env python3
"""
club_crawling_v4.py - Async API-based crawler with ETA & limit features

v4 improvements over v3:
- --limit N: limit total clubs processed (for testing)
- --max-combos N: limit total (city,age,gender) combos processed
- Overall ETA: pre-calculates total pending, shows time remaining
- Better progress tracking with overall stats
- Resume support (same as v3: pickle checkpoints + CSV inspection)
"""

import os
import sys
import time
import random
import logging
import argparse
import pickle
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from filelock import FileLock
import pandas as pd
import asyncio
from curl_cffi import AsyncSession, requests as curl_requests
from tqdm import tqdm
from fake_useragent import UserAgent
from dotenv import load_dotenv
from datetime import datetime
from typing import Dict, List, Set, Optional, Any

load_dotenv()


class AdaptiveLimiter:
    """
    Adaptive concurrency limiter that adjusts based on server response.
    Reduces concurrency on failures, increases on successes.
    """

    def __init__(self, initial_concurrent: int, min_concurrent: int = 5, max_concurrent: int = 100) -> None:
        self.concurrent = initial_concurrent
        self.min_concurrent = min_concurrent
        self.max_concurrent = max_concurrent
        self.sem = asyncio.Semaphore(self.concurrent)
        self.failed_count = 0
        self.success_count = 0

    async def acquire(self) -> None:
        await self.sem.acquire()

    def release(self) -> None:
        self.sem.release()

    async def record_failure(self) -> None:
        """Record a failure and reduce concurrency if too many failures."""
        self.failed_count += 1
        if self.failed_count >= 3:
            old = self.concurrent
            self.concurrent = max(self.min_concurrent, int(self.concurrent * 0.8))
            diff = old - self.concurrent
            for _ in range(diff):
                await self.sem.acquire()
            self.failed_count = 0
            logger.warning(f"[AdaptiveLimiter] Server issues detected, reduced concurrency to {self.concurrent}")

    async def record_success(self) -> None:
        """Record a success and increase concurrency if stable."""
        self.success_count += 1
        if self.success_count >= 10 and self.concurrent < self.max_concurrent:
            self.concurrent += 1
            self.sem.release()
            self.success_count = 0
            logger.info(f"[AdaptiveLimiter] Server stable, increased concurrency to {self.concurrent}")


# ---------------- CONFIG ----------------
LOGS_FOLDER_NAME = "logs"
OUTPUT_FOLDER_NAME = "output"
STORAGE_FOLDER_NAME = "storage"

os.makedirs(OUTPUT_FOLDER_NAME, exist_ok=True)
os.makedirs(STORAGE_FOLDER_NAME, exist_ok=True)
os.makedirs(LOGS_FOLDER_NAME, exist_ok=True)

INPUT_FILE = f"{OUTPUT_FOLDER_NAME}/england_city.csv"
CITY_COLUMN = "name"
CSV_FILE = f"{OUTPUT_FOLDER_NAME}/clubs_data.csv"
CSV_BASIC_FILE = f"{OUTPUT_FOLDER_NAME}/clubs_basic.csv"
CACHE_FILE = f"{STORAGE_FOLDER_NAME}/club_cache.pkl"
PROCESSED_FILE = f"{STORAGE_FOLDER_NAME}/processed_combos.pkl"
LOG_FILE = f"{LOGS_FOLDER_NAME}/new_scraper_optimized.log"
CSV_LOCK_FILE = os.path.join(STORAGE_FOLDER_NAME, "clubs_data.lock")
CSV_BASIC_LOCK_FILE = os.path.join(STORAGE_FOLDER_NAME, "clubs_basic.lock")

MAX_PROCESSES = int(os.getenv("MAX_PROCESSES", 5))
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", 50))
TOTAL_RETRIES = int(os.getenv("TOTAL_RETRIES", 1000000000))
BATCH_SAVE_SIZE = int(os.getenv("BATCH_SAVE_SIZE", 200))
RATE_LIMIT_SLEEP = int(os.getenv("RATE_LIMIT_SLEEP", 60))
# ----------------------------------------

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except Exception:
    pass


# ---------------- Async CSV Writer (Queue-based, Non-blocking) ----------------
class AsyncCSVWriter:
    """
    Background CSV writer that processes rows from an async queue.
    Allows the crawler to push rows without blocking on I/O.
    """

    def __init__(self, csv_path: str, lock_path: str, batch_size: int = BATCH_SAVE_SIZE):
        self.csv_path = csv_path
        self.lock_path = lock_path
        self.batch_size = batch_size
        self.queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._lock = FileLock(lock_path, timeout=30)
        self._header_written = os.path.exists(csv_path)

    async def start(self) -> None:
        """Start the background writer task."""
        if self._writer_task is None or self._writer_task.done():
            self._stop_event.clear()
            self._writer_task = asyncio.create_task(self._writer_loop())
            logger.debug(f"AsyncCSVWriter started for {self.csv_path}")

    async def stop(self) -> None:
        """Stop the background writer and flush remaining rows."""
        self._stop_event.set()
        # Wait for queue to be processed
        await self.queue.join()
        if self._writer_task:
            await self._writer_task
            self._writer_task = None
        logger.debug(f"AsyncCSVWriter stopped for {self.csv_path}")

    async def write_rows(self, rows: List[Dict[str, Any]]) -> None:
        """Add rows to the write queue (non-blocking)."""
        if not rows:
            return
        for row in rows:
            await self.queue.put(row)

    async def _writer_loop(self) -> None:
        """Background loop that batches and writes rows to CSV."""
        batch: List[Dict[str, Any]] = []

        while not self._stop_event.is_set() or not self.queue.empty():
            try:
                # Collect batch with timeout
                while len(batch) < self.batch_size:
                    try:
                        row = await asyncio.wait_for(
                            self.queue.get(),
                            timeout=0.5 if not self._stop_event.is_set() else 0.1
                        )
                        batch.append(row)
                        self.queue.task_done()
                    except asyncio.TimeoutError:
                        break

                if batch:
                    await self._write_batch(batch)
                    batch.clear()

            except asyncio.CancelledError:
                # Flush remaining on cancel
                if batch:
                    await self._write_batch(batch)
                raise
            except Exception as e:
                logger.error(f"AsyncCSVWriter error for {self.csv_path}: {e}", exc_info=True)
                if batch:
                    batch.clear()

    async def _write_batch(self, batch: List[Dict[str, Any]]) -> None:
        """Write a batch of rows to CSV using thread pool for blocking I/O."""
        if not batch:
            return

        def _sync_write():
            with self._lock:
                df = pd.DataFrame(batch)
                main_cols = ["City", "PlayWith", "Age"]
                other_cols = [c for c in df.columns if c not in main_cols]
                df = df[main_cols + other_cols]
                header = not self._header_written
                df.to_csv(self.csv_path, mode="a", index=False, header=header)
                self._header_written = True

        # Run blocking I/O in thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_write)
        logger.debug(f"Wrote batch of {len(batch)} rows to {self.csv_path}")


# Global writer instances (one per process)
_csv_writer: Optional[AsyncCSVWriter] = None
_csv_basic_writer: Optional[AsyncCSVWriter] = None


async def get_csv_writer() -> AsyncCSVWriter:
    """Get or create the global CSV writer for detailed data."""
    global _csv_writer
    if _csv_writer is None:
        _csv_writer = AsyncCSVWriter(CSV_FILE, CSV_LOCK_FILE)
        await _csv_writer.start()
    return _csv_writer


async def get_csv_basic_writer() -> AsyncCSVWriter:
    """Get or create the global CSV writer for basic data."""
    global _csv_basic_writer
    if _csv_basic_writer is None:
        _csv_basic_writer = AsyncCSVWriter(CSV_BASIC_FILE, CSV_BASIC_LOCK_FILE)
        await _csv_basic_writer.start()
    return _csv_basic_writer


async def async_append_csv_rows_safe(rows: List[Dict[str, Any]]) -> None:
    """
    Non-blocking CSV append for detailed club data using background writer queue.
    Returns immediately after queuing rows.
    """
    if not rows:
        return
    writer = await get_csv_writer()
    await writer.write_rows(rows)


async def async_append_basic_csv_rows(rows: List[Dict[str, Any]]) -> None:
    """
    Non-blocking CSV append for basic club data (from recommendation API).
    Written immediately after recommendation data is available.
    """
    if not rows:
        return
    writer = await get_csv_basic_writer()
    await writer.write_rows(rows)


async def close_csv_writer() -> None:
    """Close the global CSV writer for detailed data."""
    global _csv_writer
    if _csv_writer:
        await _csv_writer.stop()
        _csv_writer = None


async def close_csv_basic_writer() -> None:
    """Close the global CSV writer for basic data."""
    global _csv_basic_writer
    if _csv_basic_writer:
        await _csv_basic_writer.stop()
        _csv_basic_writer = None


async def close_all_csv_writers() -> None:
    """Close all CSV writers."""
    await close_csv_writer()
    await close_csv_basic_writer()


# ---------------- helpers ----------------
def safe_load_pickle(path: str, default: Any) -> Any:
    try:
        if os.path.exists(path):
            with open(path, "rb") as f:
                return pickle.load(f)
    except Exception as e:
        logger.warning(f"safe_load_pickle failed for {path}: {e}")
    return default


def atomic_pickle_dump(obj: Any, path: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(obj, f)
    os.replace(tmp, path)


def load_cities(path: str = INPUT_FILE, column: str = CITY_COLUMN) -> List[str]:
    df = pd.read_csv(path)
    return sorted(df[column].dropna().unique().tolist())


def load_city_coords(path: str = "output/city_coordinates.csv") -> Dict[str, Dict[str, float]]:
    """Load city coordinates from CSV"""
    if not os.path.exists(path):
        logger.warning(f"City coordinates file not found: {path}, using defaults")
        return {}
    df = pd.read_csv(path)
    coords = {}
    for _, row in df.iterrows():
        coords[row["city"]] = {"lat": row["latitude"], "lon": row["longitude"]}
    return coords


CITY_COORDS = load_city_coords()
DEFAULT_LAT = 51.5074
DEFAULT_LON = -0.1278


def load_existing_output_info(csv_path: str = CSV_FILE) -> tuple[Dict[str, Set[str]], Set[str]]:
    existing_club_names = {}
    completed_combos = set()

    if not os.path.exists(csv_path):
        return existing_club_names, completed_combos

    try:
        df = pd.read_csv(csv_path, usecols=lambda c: c in {"City", "PlayWith", "Age", "Club Name"})

        if "Club Name" in df.columns and "City" in df.columns:
            for _, r in df.iterrows():
                city = r["City"]
                name = str(r["Club Name"]).strip()
                if city and name:
                    existing_club_names.setdefault(city, set()).add(name)

        if {"City", "PlayWith", "Age"}.issubset(df.columns):
            combos = df[["City", "PlayWith", "Age"]].drop_duplicates()
            for _, r in combos.iterrows():
                try:
                    key = f"{r['City']}__{int(r['PlayWith'])}__{int(r['Age'])}"
                    completed_combos.add(key)
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"Could not parse existing CSV for resume info: {e}", exc_info=True)

    return existing_club_names, completed_combos


def save_summary_csv(cities: List[str], overall_stats: Dict[str, int], failed_cities: List[str], start_dt: str, elapsed: float) -> None:
    import csv
    hours, remainder = divmod(int(elapsed), 3600)
    minutes, seconds = divmod(remainder, 60)
    summary_csv = os.path.join("logs", "summary_report.csv")
    end_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "✅ SUCCESS" if not failed_cities else "❌ FAILED"

    summary_row = {
        "Date": end_dt.split()[0],
        "Start Time": start_dt,
        "End Time": end_dt,
        "Duration": f"{hours:02d}:{minutes:02d}:{seconds:02d}",
        "Total Cities": len(cities),
        "Failed Cities": len(failed_cities),
        "Fetched": overall_stats.get('total_fetched', 0),
        "Saved": overall_stats.get('saved', 0),
        "Skipped (Same City)": overall_stats.get('skipped_name', 0),
        "Skipped (Other)": overall_stats.get('skipped_other', 0),
        "Failed City Names": ", ".join(failed_cities) if failed_cities else "",
        "Status": status,
    }

    file_exists = os.path.exists(summary_csv)
    os.makedirs("logs", exist_ok=True)
    with open(summary_csv, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=summary_row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(summary_row)

    logger.info(f"📝 Summary written to {summary_csv} [{status}]")


# ---------------- Error logging with context ----------------
def log_error_with_context(
    logger: logging.Logger,
    message: str,
    city: Optional[str] = None,
    club_id: Optional[int] = None,
    club_name: Optional[str] = None,
    page: Optional[int] = None,
    attempt: Optional[int] = None,
    error: Optional[Exception] = None,
    level: str = "error"
) -> None:
    """
    Log error with full context: file, line, city, club_id, club_name, page, attempt, traceback.
    """
    # Get caller's frame info (2 levels up: this function -> caller -> caller's caller)
    frame = sys._getframe(2)
    filename = frame.f_code.co_filename
    lineno = frame.f_lineno
    func_name = frame.f_code.co_name

    context_parts = []
    if city:
        context_parts.append(f"City: {city}")
    if club_id is not None:
        context_parts.append(f"ClubID: {club_id}")
    if club_name:
        context_parts.append(f"ClubName: '{club_name}'")
    if page is not None:
        context_parts.append(f"Page: {page}")
    if attempt is not None:
        context_parts.append(f"Attempt: {attempt}")

    context_str = " | ".join(context_parts) if context_parts else "N/A"
    tb_str = ""
    if error:
        import traceback
        tb_str = traceback.format_exc()

    full_msg = (
        f"[ERROR] {message} | {context_str} | "
        f"Location: {func_name}@{filename}:{lineno}"
    )

    log_func = getattr(logger, level, logger.error)
    if tb_str:
        log_func(f"{full_msg}\n{tb_str}")
    else:
        log_func(full_msg)


# ---------------- core async fetching per club ----------------
async def fetch_club_info(
    client: AsyncSession,
    club_id: str,
    age: int,
    play_with: int,
    city: str,
    limiter: AdaptiveLimiter,
    existing_club_names: Dict[str, Set[str]],
    combo_key: str,
    club_cache: Dict[str, Dict[str, Any]],
    processed_clubs_local: Dict[str, Set[str]],
    stats: Dict[str, int],
    dry_run: bool
) -> Optional[Dict[str, Any]]:
    if club_id in club_cache:
        cached_city = club_cache[club_id].get("City") if isinstance(club_cache[club_id], dict) else None
        if cached_city == city:
            stats["skipped_cache"] += 1
            logger.warning(
                f"Club {club_id} - Age: {age} - City: {city} - Play with: {'Male' if play_with == 4 else 'Female'}"
                f" already exists in cache for this city. Skipping."
            )
            return None

    # Use approximate UK center coordinates as default (API requires Latitude/Longitude)
    DEFAULT_LAT = 51.5074
    DEFAULT_LON = -0.1278

    payload = {
        "ClubId": club_id,
        "Age": str(age),
        "PlayWith": play_with,
        "FootballType": 1,  # Use 1 (matches website FootballType enum)
        "WeekDays": "1,2,3,4,5,6,7",
        "Disabilityoption": 3,  # Website uses 3
        "DisabilityType": [{"DisabilityId": i} for i in range(1, 14)],
        "Latitude": DEFAULT_LAT,
        "Longitude": DEFAULT_LON,
        "SchoolYear": str(max(1, age - 4)),
        "SearchId": str(uuid.uuid4()),  # Client-generated UUID
    }

    headers_base = {
        "Content-Type": "application/json",
        "Accept": "gzip, deflate",
        "Connection": "keep-alive",
        "User-Agent": UserAgent().random,
        "Ocp-Apim-Subscription-Key": os.getenv("KEY_CLUB_INFO_AND_RECOMMENDATION_INFO")
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
                    headers = {**headers_base, "User-Agent": f"scraper-bot/{random.randint(1, 1000)}",
                               "Ocp-Apim-Subscription-Key": os.getenv("KEY_CLUB_INFO_AND_RECOMMENDATION_INFO")}
                    resp = await client.post(os.getenv("API_CLUB_INFO_URL"), json=payload, headers=headers, timeout=300.0)
                    if resp.status_code in (401, 403):
                        raise Exception(f"Auth failed ({resp.status_code}): Check API key")
                    if resp.status_code in (429, 500, 502, 503, 504):
                        await limiter.record_failure()
                        log_error_with_context(
                            logger, f"Server error ({resp.status_code}) for Club {club_id}",
                            city=city, club_id=club_id, attempt=attempt + 1
                        )
                        stats["rate_limited"] += 1
                        if attempt + 1 == TOTAL_RETRIES:
                            log_error_with_context(
                                logger, f"Max retries reached for Club {club_id}",
                                city=city, club_id=club_id, attempt=attempt + 1
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
                            contact_base = os.getenv("API_CLUB_CONTACT_URL", "https://hcdeapimngt1.azure-api.net/external/v1/orgs")
                            contact_resp = await client.get(
                                f"{contact_base}/{wgs_id}/clubcontact",
                                headers={"Ocp-Apim-Subscription-Key": os.getenv("KEY_CLUB_CONTACT_INFO"), "User-Agent": f"scraper-bot/{random.randint(1, 1000)}"},
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

                row = {
                    "City": city,
                    "PlayWith": play_with,
                    "Age": age,
                    "Club Name": club_name,
                    "Club Address": ", ".join(filter(None, [data.get("AddressLine1", ""), data.get("City", ""), data.get("PostCode", "")])),
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
                club_name_val = (data.get("ClubName", "") or "").strip() if 'data' in locals() and isinstance(data, dict) else "Unknown"
                log_error_with_context(
                    logger, f"Exception in fetch_club_info: {exception_error}",
                    city=city, club_id=club_id, club_name=club_name_val, attempt=attempt + 1, error=exception_error
                )
                await asyncio.sleep(min(0.5 * (2 ** attempt) + random.random(), 10.0))
        stats["failed"] += 1
        return None


# ---------------- fetch list-of-clubs for a combo ----------------
def extract_clubids_from_recommendation(api_general_info_data: Any) -> List[Dict[str, str]]:
    """
    Extract club IDs from recommendation API response.

    API returns: {"CntOpportunity": N, "RecommendationClubCentreCartDto": [...]}
    Each item in RecommendationClubCentreCartDto has ClubId and other fields.
    """
    clubs: List[Dict[str, str]] = []

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


def extract_full_club_data_from_recommendation(api_general_info_data: Any) -> List[Dict[str, Any]]:
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


async def fetch_recommendation_pages(city: str, dry_run: bool = False) -> List[Dict[str, Any]]:
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
    base_payload = {
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

    def fetch_page(page_number: int) -> Optional[Dict[str, Any]]:
        """Fetch a single page of results"""
        import json as _json
        headers = {"User-Agent": f"scraper-bot/{random.randint(1, 1000)}", "Ocp-Apim-Subscription-Key": os.getenv("KEY_CLUB_INFO_AND_RECOMMENDATION_INFO")}
        payload = {**base_payload, "PageNumber": page_number}
        with curl_requests.Session(impersonate="chrome120", headers=headers, timeout=300.0) as client:
            resp = client.post(os.getenv("API_CLUB_RECOMMENDATION_URL"), json=payload)
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

    all_results: List[Dict[str, Any]] = []
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
                    city=city, page=page, attempt=current_retry + 1, error=e, level="warning"
                )
                await asyncio.sleep(min(0.5 * (2 ** current_retry) + random.random(), 10.0))

    return all_results


async def process_combo_async(
    city: str,
    existing_club_names: Dict[str, Set[str]],
    club_cache: Dict[str, Dict[str, Any]],
    processed_clubs_local: Dict[str, Set[str]],
    stats: Dict[str, int],
    dry_run: bool = False
) -> List[Dict[str, Any]]:
    """
    Process a single city combo (now just one combo per city with defaults).
    Phase 1: Write ALL available club info from recommendation API immediately.
    Phase 2: Fetch detailed info and write to detail CSV (for any missing fields).
    """
    combo_key = f"{city}__0"
    limiter = AdaptiveLimiter(MAX_CONCURRENT_REQUESTS, min_concurrent=5, max_concurrent=MAX_CONCURRENT_REQUESTS)
    api_general_info_data = await fetch_recommendation_pages(city, dry_run)

    # Extract ALL fields from recommendation API response
    clubs_data = extract_full_club_data_from_recommendation(api_general_info_data)
    if not clubs_data:
        return []

    # ===== PHASE 1: Write ALL available club info from recommendation API immediately =====
    basic_rows: List[Dict[str, Any]] = []
    club_ids_to_fetch_detail: List[str] = []

    for club_data in clubs_data:
        club_id = club_data.get("ClubId", "")
        if not club_id:
            continue

        # Skip if already in cache for this city
        if club_id in club_cache:
            cached_city = club_cache[club_id].get("City") if isinstance(club_cache[club_id], dict) else None
            if cached_city == city:
                stats["skipped_cache"] += 1
                logger.warning(
                    f"Club {club_id} - City: {city} already exists in cache. Skipping basic write."
                )
                continue

        # Build basic row with ALL fields from recommendation API
        basic_row = {
            "City": city,
            "PlayWith": 4,
            "Age": 0,
            "ClubId": club_id,
            "Source": "recommendation",
        }
        # Add all fields from recommendation response
        for key, value in club_data.items():
            if key != "ClubId":  # Already added above
                basic_row[key] = value

        basic_rows.append(basic_row)
        club_ids_to_fetch_detail.append(club_id)

    if basic_rows:
        await async_append_basic_csv_rows(basic_rows)
        logger.info(f"[{city}] Phase 1: Written {len(basic_rows)} basic club rows to CSV (all recommendation fields)")

    # ===== PHASE 2: Fetch detailed info and write to detail CSV =====
    # Only fetch detail for clubs that need additional info not in recommendation
    rows_to_save: List[Dict[str, Any]] = []

    async with AsyncSession(impersonate="chrome120", timeout=300.0) as client:
        tasks = [
            fetch_club_info(client, club_id, 0, 4, city, limiter,
                            existing_club_names, combo_key, club_cache, processed_clubs_local, stats, dry_run)
            for club_id in club_ids_to_fetch_detail
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in raw_results:
        if isinstance(r, dict):
            rows_to_save.append(r)
    return rows_to_save


# ---------------- process city (per-process) ----------------
def process_city_worker(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Worker function that runs in a separate process.
    Each worker creates its own asyncio event loop.
    """
    city = args.get("city", "Unknown")
    pending_combos = args.get("pending_combos", [])
    dry_run = args.get("dry_run", False)
    shared_counter = args.get("shared_counter")
    shared_lock = args.get("shared_lock")
    clubs_saved_counter = args.get("clubs_saved_counter")
    clubs_saved_lock = args.get("clubs_saved_lock")
    limit = args.get("limit", 0)

    start = time.time()
    logger.info(f"Process start for city {city}, combos={len(pending_combos)}, dry_run={dry_run}, limit={limit}")

    existing_club_names, combos_from_csv = load_existing_output_info(CSV_FILE)
    club_cache = safe_load_pickle(CACHE_FILE, {}) or {}
    processed_combos_global = safe_load_pickle(PROCESSED_FILE, set()) or set()
    processed_clubs_local: Dict[str, Set[str]] = {}
    processed_combos_buffer: Set[str] = set()

    stats: Dict[str, int] = {"success": 0, "failed": 0, "http_errors": 0, "other_errors": 0,
                 "rate_limited": 0, "skipped_name": 0, "skipped_cache": 0, "no_name": 0}

    total = len(pending_combos)
    pbar = tqdm(total=total, desc=f"City: {city}", ncols=120, position=1, leave=False)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        for (age, play_with) in pending_combos:
            # Check limit before processing combo
            if limit > 0 and clubs_saved_counter and clubs_saved_lock:
                with clubs_saved_lock:
                    if clubs_saved_counter.value >= limit:
                        logger.info(f"Limit of {limit} clubs reached, stopping city {city}")
                        break

            combo_key = f"{city}__0"  # Single combo per city
            if combo_key in processed_combos_global:
                pbar.set_postfix_str("skip")
                pbar.update(1)
                # Update shared counter
                if shared_counter and shared_lock:
                    with shared_lock:
                        shared_counter.value += 1
                continue

            attempt = 0
            rows: List[Dict[str, Any]] = []
            while attempt < TOTAL_RETRIES:
                attempt += 1
                try:
                    rows = loop.run_until_complete(process_combo_async(
                        city,
                        existing_club_names,
                        club_cache,
                        processed_clubs_local,
                        stats,
                        dry_run=dry_run
                    ))
                    break
                except Exception as e:
                    log_error_with_context(
                        logger, f"City {city} attempt {attempt} failed: {e}",
                        city=city, attempt=attempt, error=e, level="warning"
                    )
                    time.sleep(min(0.5 * (2 ** attempt) + random.random(), 10.0))
                    if attempt < TOTAL_RETRIES:
                        time.sleep(1 + random.random())

            if rows:
                # Check limit again before saving
                if limit > 0 and clubs_saved_counter and clubs_saved_lock:
                    with clubs_saved_lock:
                        if clubs_saved_counter.value >= limit:
                            logger.info(f"Limit of {limit} clubs reached before saving, stopping city {city}")
                            break
                        # Calculate how many we can save
                        remaining = limit - clubs_saved_counter.value
                        if len(rows) > remaining:
                            rows = rows[:remaining]
                        clubs_saved_counter.value += len(rows)

                loop.run_until_complete(async_append_csv_rows_safe(rows))
            else:
                stats["failed"] += 1

            # mark combo done
            processed_combos_buffer.add(combo_key)
            if len(processed_combos_buffer) >= 20:
                processed_combos_global.update(processed_combos_buffer)
                try:
                    atomic_pickle_dump(processed_combos_global, PROCESSED_FILE)
                except Exception as e:
                    log_error_with_context(
                        logger, f"Failed to dump processed_combos: {e}",
                        city=city, error=e, level="warning"
                    )
                processed_combos_buffer.clear()

            pbar.update(1)
            # Update shared counter
            if shared_counter and shared_lock:
                with shared_lock:
                    shared_counter.value += 1

    finally:
        if processed_combos_buffer:
            processed_combos_global.update(processed_combos_buffer)
        try:
            atomic_pickle_dump(processed_combos_global, PROCESSED_FILE)
            atomic_pickle_dump(club_cache, CACHE_FILE)
        except Exception as e:
            log_error_with_context(
                logger, f"Final dump failed: {e}",
                city=city, error=e, level="warning"
            )
        # Close all CSV writers to flush any remaining queued rows
        loop.run_until_complete(close_all_csv_writers())
        loop.close()
        pbar.close()

    elapsed = time.time() - start
    logger.info(f"Process done for city {city} elapsed {elapsed:.1f}s stats={stats}")
    return {"city": city, "elapsed": elapsed, "stats": stats, "combos_done": len(pending_combos)}


# ---------------- ETA Calculator ----------------
class ETACalculator:
    def __init__(self, total_combos: int) -> None:
        self.total_combos = total_combos
        self.completed_combos = 0
        self.start_time = time.time()
        self.last_update = self.start_time
        self.combos_per_second = 0.0

    def update(self, completed: int) -> None:
        self.completed_combos = completed
        now = time.time()
        elapsed = now - self.start_time
        if elapsed > 1:
            self.combos_per_second = completed / elapsed

    def get_eta_str(self) -> str:
        if self.combos_per_second <= 0 or self.completed_combos >= self.total_combos:
            return "calculating..."
        remaining = self.total_combos - self.completed_combos
        eta_seconds = remaining / self.combos_per_second
        hours, remainder = divmod(int(eta_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def get_progress_str(self) -> str:
        pct = (self.completed_combos / self.total_combos * 100) if self.total_combos > 0 else 0
        return f"{self.completed_combos}/{self.total_combos} ({pct:.1f}%)"

    def get_rate_str(self) -> str:
        return f"{self.combos_per_second:.1f} combos/s"


# ---------------- build pending combos ----------------
def build_pending_combos_for_city(city: str, existing_combo_set: Set[str]) -> List[tuple]:
    """
    API uses Age=0 and PlayWith=7 (from website default payload) - returns all clubs.
    Only one combo per city needed.
    """
    pending = []
    key = f"{city}__0"  # Single combo per city (age=0, play_with=default)
    if key not in existing_combo_set:
        pending.append((0, 0))  # age=0, play_with=0 (using defaults from payload)
    return pending


def main(dry_run: bool = False, limit: int = 0, max_combos: int = 0) -> None:
    # Load cities và combo đã crawl
    cities = load_cities(INPUT_FILE, CITY_COLUMN)
    _, combos_from_csv = load_existing_output_info(CSV_FILE)
    processed_from_pickle = safe_load_pickle(PROCESSED_FILE, set()) or set()
    existing_combo_set = set().union(combos_from_csv, processed_from_pickle)

    start_time = time.time()
    start_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"🚀 Crawl started at {start_dt}")

    # Build per-city pending combos with limits
    city_args: List[Dict[str, Any]] = []
    total_pending_combos = 0
    combos_added = 0

    for city in cities:
        pending = build_pending_combos_for_city(city, existing_combo_set)
        if pending:
            # Apply max_combos limit
            if max_combos > 0:
                remaining = max_combos - combos_added
                if remaining <= 0:
                    break
                pending = pending[:remaining]
                combos_added += len(pending)
            else:
                combos_added += len(pending)

            city_args.append({"city": city, "pending_combos": pending, "dry_run": dry_run})
            total_pending_combos += len(pending)
        else:
            logger.info(f"City {city} already fully completed, skipping.")

    if not city_args:
        print("No pending combos — everything is complete.")
        return

    print(f"\n{'='*60}")
    print(f"CRAWL OVERVIEW")
    print(f"{'='*60}")
    print(f"Total cities to process: {len(city_args)}")
    print(f"Total pending combos: {total_pending_combos:,}")
    print(f"Max processes: {MAX_PROCESSES}")
    print(f"Concurrent requests/process: {MAX_CONCURRENT_REQUESTS}")
    print(f"Dry run: {dry_run}")
    if limit > 0:
        print(f"Club limit: {limit}")
    if max_combos > 0:
        print(f"Max combos: {max_combos}")
    print(f"{'='*60}\n")

    # Shared counter for overall progress
    from multiprocessing import Manager
    manager = Manager()
    shared_counter = manager.Value('i', 0)
    shared_lock = manager.Lock()

    # Shared counter for club limit
    clubs_saved_counter = manager.Value('i', 0)
    clubs_saved_lock = manager.Lock()

    # ETA Calculator
    eta_calc = ETACalculator(total_pending_combos)

    # Overall stats
    overall_stats: Dict[str, int] = {
        "total_fetched": 0,
        "saved": 0,
        "skipped_name": 0,
        "skipped_other": 0,
    }
    failed_cities: List[str] = []

    # Run multiprocessing with overall progress bar
    with ProcessPoolExecutor(max_workers=min(MAX_PROCESSES, len(city_args))) as executor:
        # Submit all jobs
        future_to_city: Dict[Any, str] = {}
        for arg in city_args:
            arg["shared_counter"] = shared_counter
            arg["shared_lock"] = shared_lock
            arg["clubs_saved_counter"] = clubs_saved_counter
            arg["clubs_saved_lock"] = clubs_saved_lock
            arg["limit"] = limit
            future = executor.submit(process_city_worker, arg)
            future_to_city[future] = arg["city"]

        # Overall progress bar
        overall_pbar = tqdm(total=total_pending_combos, desc="Overall", ncols=120, position=0)

        last_completed = 0

        for fut in as_completed(future_to_city):
            city = future_to_city[fut]
            for current_retry in range(TOTAL_RETRIES):
                try:
                    res = fut.result()
                    logger.info(f"City finished: {res['city']} elapsed {res['elapsed']:.1f}s")

                    stats = res.get("stats", {})
                    overall_stats["total_fetched"] += stats.get("success", 0)
                    overall_stats["saved"] += stats.get("success", 0)
                    overall_stats["skipped_name"] += stats.get("skipped_name", 0)
                    overall_stats["skipped_other"] += stats.get("skipped_cache", 0) + stats.get("no_name", 0) + stats.get("other_errors", 0)

                    if stats.get("failed", 0) > 0:
                        # Only mark as failed if there are REAL errors (not just empty combos)
                        real_errors = stats.get("http_errors", 0) + stats.get("other_errors", 0)
                        if real_errors > 0:
                            failed_cities.append(res['city'])
                    break
                except Exception as e:
                    log_error_with_context(
                        logger, f"City future error: {e}. Retry: {current_retry+1}",
                        city=city, attempt=current_retry+1, error=e, level="error"
                    )
                    time.sleep(min(0.5 * (2 ** current_retry) + random.random(), 10.0))

            # Update overall progress bar with shared counter
            while True:
                with shared_lock:
                    current = shared_counter.value
                if current > last_completed:
                    delta = current - last_completed
                    overall_pbar.update(delta)
                    last_completed = current
                    eta_calc.update(current)
                    # Update postfix with ETA
                    overall_pbar.set_postfix_str(
                        f"Rate: {eta_calc.get_rate_str()} | ETA: {eta_calc.get_eta_str()} | {eta_calc.get_progress_str()}"
                    )
                else:
                    break

        overall_pbar.close()

    # Summary and final stats
    elapsed = time.time() - start_time
    hours, remainder = divmod(int(elapsed), 3600)
    minutes, seconds = divmod(remainder, 60)
    end_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(
        f"[FINAL TOTAL STATS] Fetched: {overall_stats['total_fetched']}, "
        f"Saved: {overall_stats['saved']}, "
        f"Skipped (Same City): {overall_stats['skipped_name']}, "
        f"Skipped (Other): {overall_stats['skipped_other']}"
    )

    if failed_cities:
        logger.warning(f"⚠️ {len(failed_cities)} cities failed: {', '.join(failed_cities)}")
    else:
        logger.info("✅ All cities completed successfully without errors.")

    logger.info(f"✅ Crawl completed successfully in {hours:02d}:{minutes:02d}:{seconds:02d}")
    logger.info(f"🏁 End time: {end_dt}")

    # Save summary CSV
    save_summary_csv(cities, overall_stats, failed_cities, start_dt, elapsed)

    print(f"\n{'='*60}")
    print(f"DONE in {hours:02d}:{minutes:02d}:{seconds:02d}")
    print(f"Fetched: {overall_stats['total_fetched']:,} | Saved: {overall_stats['saved']:,}")
    print(f"Skipped (dup): {overall_stats['skipped_name']:,} | Other: {overall_stats['skipped_other']:,}")
    if failed_cities:
        print(f"Failed cities: {len(failed_cities)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Football Club Data Crawler v4 - Async API with ETA & Limits")
    parser.add_argument("--dry-run", action="store_true", help="simulate requests (no real API calls)")
    parser.add_argument("--limit", type=int, default=0, help="limit total clubs to process (0 = no limit)")
    parser.add_argument("--max-combos", type=int, default=10, help="limit total (city,age,gender) combos to process (0 = no limit)")
    args = parser.parse_args()
    main(dry_run=args.dry_run, limit=args.limit, max_combos=args.max_combos)