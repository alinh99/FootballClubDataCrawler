#!/usr/bin/env python3
"""
safe_fast_scraper_final.py

- Read cities from england_city.csv (column "Name")
- Ages 5..99, play_with in [4,5] # 4 means Male, 5 means Female
- Resume at combo level (city, play_with, age) by inspecting output CSV or processed_combos.pkl
- Multiprocessing per city + asyncio within each process
- Skip club_name already present in CSV immediately
- --dry-run to simulate (no external calls)
"""

import os
import time
import json
import random
import logging
import argparse
import pickle
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from filelock import FileLock
import pandas as pd
import asyncio
import httpx
from tqdm import tqdm
from fake_useragent import UserAgent
from dotenv import load_dotenv
import sys


load_dotenv()

class AdaptiveLimiter:
    def __init__(self, initial_concurrent, min_concurrent=5, max_concurrent=100):
        self.concurrent = initial_concurrent
        self.min_concurrent = min_concurrent
        self.max_concurrent = max_concurrent
        self.sem = asyncio.Semaphore(self.concurrent)
        self.failed_count = 0
        self.success_count = 0

    async def acquire(self):
        await self.sem.acquire()

    def release(self):
        self.sem.release()

    def record_failure(self):
        self.failed_count += 1
        if self.failed_count >= 3:  # nếu 3 request fail liên tiếp
            old = self.concurrent
            self.concurrent = max(self.min_concurrent, int(self.concurrent * 0.8))
            diff = old - self.concurrent
            for _ in range(diff):
                self.sem.acquire()  # giảm semaphore
            self.failed_count = 0
            logger.warning(f"[AdaptiveLimiter] Server issues detected, reduced concurrency to {self.concurrent}")

    def record_success(self):
        self.success_count += 1
        if self.success_count >= 10 and self.concurrent < self.max_concurrent:
            self.concurrent += 1
            self.sem.release()
            self.success_count = 0
            logger.info(f"[AdaptiveLimiter] Server stable, increased concurrency to {self.concurrent}")

LOGS_FOLDER_NAME = "logs"
OUTPUT_FOLDER_NAME = "output"
STORAGE_FOLDER_NAME = "storage"

os.makedirs(OUTPUT_FOLDER_NAME, exist_ok=True)
os.makedirs(STORAGE_FOLDER_NAME, exist_ok=True)
os.makedirs(LOGS_FOLDER_NAME, exist_ok=True)

# ---------------- CONFIG ----------------
INPUT_FILE = f"{OUTPUT_FOLDER_NAME}/england_city.csv"
CITY_COLUMN = "name"
CSV_FILE = f"{OUTPUT_FOLDER_NAME}/clubs_data.csv"             # final CSV output (has City,PlayWith,Age,Club Name,...)
CACHE_FILE = f"{STORAGE_FOLDER_NAME}/club_cache.pkl"
PROCESSED_FILE = f"{STORAGE_FOLDER_NAME}/processed_combos.pkl" # set of (city_play_age) tuples
LOG_FILE = f"{LOGS_FOLDER_NAME}/new_scraper_optimized.log"
CSV_LOCK_FILE = os.path.join(STORAGE_FOLDER_NAME, "clubs_data.lock")

MAX_PROCESSES = int(os.getenv("MAX_PROCESSES", 5))
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", 50))  # per-process
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

# ---------------- helpers ----------------
def safe_load_pickle(path, default):
    try:
        if os.path.exists(path):
            with open(path, "rb") as f:
                return pickle.load(f)
    except Exception as e:
        logger.warning(f"safe_load_pickle failed for {path}: {e}")
    return default

def atomic_pickle_dump(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(obj, f)
    os.replace(tmp, path)

def load_cities(path=INPUT_FILE, column=CITY_COLUMN):
    df = pd.read_csv(path)
    return sorted(df[column].dropna().unique().tolist())

def load_existing_output_info(csv_path=CSV_FILE):
    """
    Read existing output CSV (if present) and return:
     - existing_club_names: dict {city_name: set(club_names)} (used to skip duplicates per city)
     - completed_combos: set of combo keys f"{city}__{play_with}__{age}"
    
    If CSV not present or missing columns, return empty structures.
    """
    existing_club_names = {}  # dict {city: set(club_names)}
    completed_combos = set()
    
    if not os.path.exists(csv_path):
        return existing_club_names, completed_combos
    
    try:
        df = pd.read_csv(csv_path, usecols=lambda c: c in {"City","PlayWith","Age","Club Name"})
        
        # --- Build dict of club names per city ---
        if "Club Name" in df.columns and "City" in df.columns:
            for _, r in df.iterrows():
                city = r["City"]
                name = str(r["Club Name"]).strip()
                if city and name:
                    existing_club_names.setdefault(city, set()).add(name)
        
        # --- Build completed combos ---
        if {"City","PlayWith","Age"}.issubset(df.columns):
            combos = df[["City","PlayWith","Age"]].drop_duplicates()
            for _, r in combos.iterrows():
                try:
                    key = f"{r['City']}__{int(r['PlayWith'])}__{int(r['Age'])}"
                    completed_combos.add(key)
                except Exception:
                    continue

    except Exception as e:
        logger.warning(f"Could not parse existing CSV for resume info: {e}", exc_info=True)
    
    return existing_club_names, completed_combos

def save_summary_csv(cities, overall_stats, failed_cities, start_dt, elapsed):
    import csv
    import os
    from datetime import datetime

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
        "Fetched": overall_stats.get('total_fetched',0),
        "Saved": overall_stats.get('saved',0),
        "Skipped (Same City)": overall_stats.get('skipped_name',0),
        "Skipped (Other)": overall_stats.get('skipped_other',0),
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

# Async-safe append CSV (includes combo columns)
async def async_append_csv_rows(rows, csv_path=CSV_FILE):
    if not rows:
        return
    df = pd.DataFrame(rows)
    header = not os.path.exists(csv_path)
    loop = asyncio.get_event_loop()
    # run pandas to_csv in thread to avoid blocking event loop
    await loop.run_in_executor(None, lambda: df.to_csv(csv_path, mode='a', index=False, header=header))

# ---------------- core async fetching per club ----------------
async def fetch_club_info(client: httpx.AsyncClient, club_id: str, age: int, play_with: int,
                          city: str, limiter: AdaptiveLimiter, existing_club_names: dict,
                          combo_key: str, club_cache: dict, processed_clubs_local: dict,
                          stats: dict, dry_run: bool):
    """
    Fetch club detail by club_id. Return a dict row to save or None.
    """
    # --- Skip only if same city --- #
    if club_id in club_cache:
        cached_city = club_cache[club_id].get("City") if isinstance(club_cache[club_id], dict) else None
        if cached_city == city:
            stats["skipped_cache"] += 1
            logger.warning(
                f"Club {club_id} - Age: {age} - City: {city} - Play with: {'Male' if play_with == 4 else 'Female'}"
                f" already exists in cache for this city. Skipping."
            )
            
            return None

    payload = {
        "ClubId": club_id,
        "Age": str(age),
        "PlayWith": play_with,
        "FootballType": 3,
        "WeekDays": "1,2,3,4,5,6,7",
        "Disabilityoption": 1,
        "DisabilityType": [{"DisabilityId": i} for i in range(1, 14)],
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
                        "TeamsCount": random.randint(1,5),
                        "WgsClubId": None
                    }
                    contact_data = {}
                else:

                    headers = {**headers_base, "User-Agent": f"scraper-bot/{random.randint(1,1000)}",
                               "Ocp-Apim-Subscription-Key": os.getenv("KEY_CLUB_INFO_AND_RECOMMENDATION_INFO")}  # giữ nguyên headers
                    resp = await client.post(os.getenv("API_CLUB_INFO_URL"), json=payload, headers=headers, timeout=300.0)
                    if resp.status_code in (429, 500, 503):
                        limiter.record_failure()
                        logger.error(f"Server errors at Club {club_id} - Age: {age} - City: {city} - Play with: {'Male' if play_with == 4 else 'Female'}. Retry: {attempt+1}/{TOTAL_RETRIES}")
                        stats["rate_limited"] += 1
                        if attempt+1 == TOTAL_RETRIES:
                            logger.error(f"Max retries reached for Server errors at Club {club_id} - Age: {age} - City: {city} - Play with: {'Male' if play_with == 4 else 'Female'}. Retry: {attempt+1}/{TOTAL_RETRIES}")
                        await asyncio.sleep(RATE_LIMIT_SLEEP + random.random()*5)
                        continue
                    resp.raise_for_status()
                    limiter.record_success()
                    data = resp.json()
                    
                    club_name = (data.get("ClubName","") or "").strip()
                    if city in existing_club_names and club_name in existing_club_names[city]:
                        stats["skipped_name"] += 1
                        logger.warning(f"[SKIP] Club '{club_name}' already exists in city '{city}'. Skipping.")
                        return None
                    contact_data = {}  # fetch contact như cũ
                    #                     contact_data = {}
                    wgs_id = data.get("WgsClubId")
                    if wgs_id:
                        try:
                            contact_base = os.getenv("API_CLUB_CONTACT_URL", "https://hcdeapimngt1.azure-api.net/external/v1/orgs")
                            contact_resp = await client.get(
                                f"{contact_base}/{wgs_id}/clubcontact",
                                headers={"Ocp-Apim-Subscription-Key": os.getenv("KEY_CLUB_CONTACT_INFO"), "User-Agent": f"scraper-bot/{random.randint(1,1000)}"},
                                timeout=300.0
                            )
                            if contact_resp.status_code == 200:
                                contact_data = contact_resp.json()
                        except Exception:
                            pass

                # xử lý dữ liệu bình thường
                club_name = (data.get("ClubName","") or "").strip()
                if not club_name:
                    stats["no_name"] += 1
                    return None
                
                # # Skip duplicate name immediately
                # if city in existing_club_names and club_id in club_cache:
                #     cached_city = club_cache[club_id].get("City") if isinstance(club_cache[club_id], dict) else None
                #     if cached_city == city:
                #         stats["skipped_cache"] += 1
                #         logger.warning(f"[SKIP] Club {club_id} in city '{city}' already in cache. Skipping.")
                #         return None

                # --- Skip duplicate name **same city** ---
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
                    "Club Address": ", ".join(filter(None, [data.get("AddressLine1",""), data.get("City",""), data.get("PostCode","")])),
                    "Accredited To": data.get("ClubCounty","") or "",
                    "Football Types": ", ".join(filter(None, football_types_list)),
                    "Team Numbers": data.get("TeamsCount",0) or 0,
                    "Contact Name": contact_data.get("individualName","") or "",
                    "Contact Phone": contact_data.get("phone","") or "",
                    "Contact Email": contact_data.get("email","") or "",
                    "Contact Website": contact_data.get("website","") or ""
                }

                # update caches
                existing_club_names.setdefault(city, set()).add(club_name)
                club_cache[club_id] = row
                processed_clubs_local.setdefault(combo_key, set()).add(club_id)
                stats["success"] += 1
                return row

            except httpx.HTTPStatusError as http_error:
                limiter.record_failure()
                stats["http_errors"] += 1
                print(f"Error for http status error: {http_error}. Retry: {attempt+1}/{TOTAL_RETRIES}")
                logger.error(f"Error for http status error: {http_error}. Retry: {attempt+1}/{TOTAL_RETRIES}", exc_info=True)
                await asyncio.sleep(min(1.0 * (2 ** attempt) + random.random(), 10.0))
            except Exception as exception_error:
                stats["other_errors"] += 1
                print(f"Error for exception_error: {exception_error}. Retry: {attempt+1}/{TOTAL_RETRIES}")
                logger.error(f"Error for exception_error: {exception_error}. Retry: {attempt+1}/{TOTAL_RETRIES}", exc_info=True)
                await asyncio.sleep(min(0.5 * (2 ** attempt) + random.random(), 10.0))
        stats["failed"] += 1
        return None
# ---------------- fetch list-of-clubs for a combo ----------------
def extract_clubids_from_recommendation(api_general_info_data):
    """Return list of club IDs and their football type as dicts like {ClubId: FootballType}"""
    clubs = []
    for d in api_general_info_data or []:
        for c in d.get("RecommendationClubCartDto", []) or []:
            cid = c.get("ClubId","")
            if cid:
                clubs.append({cid: d.get("FootballType","")})
    return clubs

async def process_combo_async(city, play_with, age, existing_club_names, club_cache, processed_clubs_local, stats, dry_run=False):
    combo_key = f"{city}__{play_with}__{age}"
    # Recommendation API call (one sync call inside thread to keep simple)
    # In dry_run simulate a bunch of club ids
    limiter = AdaptiveLimiter(MAX_CONCURRENT_REQUESTS, min_concurrent=5, max_concurrent=MAX_CONCURRENT_REQUESTS)
    api_general_info_data = None
    
    if dry_run:
        # simulate some pages of recommendation data
        api_general_info_data = [{"RecommendationClubCartDto": [{"ClubId": f"DRY_{city}_{play_with}_{age}_{i}"} for i in range(25)], "FootballType": "DRY"}]
    else:
        # Use httpx sync client in executor to avoid event-loop blocking for big single POST
        loop = asyncio.get_event_loop()
        def sync_post():
            import httpx as _httpx
            headers = {"User-Agent": f"scraper-bot/{random.randint(1,1000)}", "Ocp-Apim-Subscription-Key": os.getenv("KEY_CLUB_INFO_AND_RECOMMENDATION_INFO")}
            with _httpx.Client(http2=True, headers=headers, timeout=300.0) as client:
                resp = client.post(os.getenv("API_CLUB_RECOMMENDATION_URL"), json={
                    "SearchForUser": "Someone else",
                    "Age": str(age),
                    "PlayWith": play_with,
                    "FootballType": 3,
                    "WeekDays": "1,2,3,4,5,6,7",
                    "Disabilityoption": 1,
                    "DisabilityType": [{"DisabilityId": i} for i in range(1, 14)],
                    "SelectedDisabilityType": 10,
                    "OptforCurrentLocation": "No",
                    "PageNumber": 1,
                    "PageSize": 1000000,
                    "ReadableLocation": city,
                    "SelectedFootballType": 2,
                    "SurfaceType": "3G or Astroturf,Grass,Indoor,Others",
                })
                resp.raise_for_status()
                return resp.json()
        for current_retry in range(TOTAL_RETRIES):
            try:
                api_general_info_data = await loop.run_in_executor(None, sync_post)
                break
            except Exception as e:
                logger.warning(f"[{city}][{play_with}][{age}] recommendation API failed: {e}. Retry: {current_retry+1}/{TOTAL_RETRIES}", exc_info=True)
                print(f"[{city}][{play_with}][{age}] recommendation API failed: {e}. Retry: {current_retry+1}/{TOTAL_RETRIES}")
                await asyncio.sleep(min(0.5 * (2 ** current_retry) + random.random(), 10.0))

    clubs_dicts = extract_clubids_from_recommendation(api_general_info_data)
    if not clubs_dicts:
        return []

    # now do async detail fetch for each club id
    timeout = httpx.Timeout(300.0, connect=10.0)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    rows_to_save = []
    
    async with httpx.AsyncClient(http2=True, timeout=timeout) as client:
        tasks = [
            fetch_club_info(client, list(d.keys())[0], age, play_with, city, limiter,
                            existing_club_names, combo_key, club_cache, processed_clubs_local, stats, dry_run)
            for d in clubs_dicts
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in raw_results:
        if isinstance(r, dict):
            rows_to_save.append(r)
    return rows_to_save

# ---------------- process city (per-process) ----------------
async def async_append_csv_rows_safe(rows, csv_path=CSV_FILE):
    """Append rows to CSV safely across multiple processes, preserving main columns."""
    if not rows:
        return
    df = pd.DataFrame(rows)
    main_cols = ["City", "PlayWith", "Age"]
    other_cols = [c for c in df.columns if c not in main_cols]
    df = df[main_cols + other_cols]
    header = not os.path.exists(csv_path)
    lock = FileLock(CSV_LOCK_FILE)
    loop = asyncio.get_event_loop()
    with lock:
        await loop.run_in_executor(None, lambda: df.to_csv(csv_path, mode='a', index=False, header=header))

def process_city_worker(args):
    city = args.get("city", "Unknown")
    pending_combos = args.get("pending_combos", [])
    dry_run = args.get("dry_run", False)

    start = time.time()
    logger.info(f"Process start for city {city}, combos={len(pending_combos)}, dry_run={dry_run}")

    existing_club_names, combos_from_csv = load_existing_output_info(CSV_FILE)
    club_cache = safe_load_pickle(CACHE_FILE, {}) or {}
    processed_combos_global = safe_load_pickle(PROCESSED_FILE, set()) or set()
    processed_clubs_local = {}
    processed_combos_buffer = set()

    stats = {"success":0,"failed":0,"http_errors":0,"other_errors":0,
             "rate_limited":0,"skipped_name":0,"skipped_cache":0,"no_name":0}

    total = len(pending_combos)
    pbar = tqdm(total=total, desc=f"City: {city}", ncols=100)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        for (play_with, age) in pending_combos:
            combo_key = f"{city}__{play_with}__{age}"
            if combo_key in processed_combos_global:
                pbar.set_postfix_str(f"skip {play_with}/{age}")
                pbar.update(1)
                continue

            attempt = 0
            rows = []
            while attempt < TOTAL_RETRIES:
                attempt += 1
                try:
                    rows = loop.run_until_complete(process_combo_async(
                        city, play_with, age,
                        existing_club_names,
                        club_cache,
                        processed_clubs_local,
                        stats,
                        dry_run=dry_run
                    ))
                    break
                    # if not rows:
                    #     logger.warning(f"[{city}][{play_with}/{age}] attempt {attempt} got 0 rows")
                    #     if attempt < TOTAL_RETRIES:
                    #         time.sleep(1 + random.random())  # nhẹ nhàng jitter
                except Exception as e:
                    logger.warning(f"[{city}][{play_with}/{age}] attempt {attempt} failed: {e}", exc_info=True)
                    print(f"[{city}][{play_with}/{age}] attempt {attempt} failed: {e}")
                    time.sleep(min(0.5 * (2 ** attempt) + random.random(), 10.0))
                    if attempt < TOTAL_RETRIES:
                        time.sleep(1 + random.random())

            if rows:
                loop.run_until_complete(async_append_csv_rows(rows, CSV_FILE))
            else:
                stats["failed"] += 1

            # mark combo done
            processed_combos_buffer.add(combo_key)
            if len(processed_combos_buffer) >= 20:
                processed_combos_global.update(processed_combos_buffer)
                try:
                    atomic_pickle_dump(processed_combos_global, PROCESSED_FILE)
                except Exception as e:
                    logger.warning(f"Failed to dump processed_combos: {e}", exc_info=True)
                    print(f"Failed to dump processed_combos: {e}")
                processed_combos_buffer.clear()

            pbar.update(1)

    finally:
        if processed_combos_buffer:
            processed_combos_global.update(processed_combos_buffer)
        try:
            atomic_pickle_dump(processed_combos_global, PROCESSED_FILE)
            atomic_pickle_dump(club_cache, CACHE_FILE)
        except Exception as e:
            logger.warning(f"Final dump failed: {e}")
        loop.close()
        pbar.close()

    elapsed = time.time() - start
    logger.info(f"Process done for city {city} elapsed {elapsed:.1f}s stats={stats}")
    return {"city": city, "elapsed": elapsed, "stats": stats}

# ---------------- main ----------------
def build_pending_combos_for_city(city, existing_combo_set):
    # returns list of (play_with, age) combos that are NOT present in existing_combo_set
    pending = []
    for play_with in [4,5]:
        for age in range(5, 100):  # 5..99 inclusive
            key = f"{city}__{play_with}__{age}"
            if key not in existing_combo_set:
                pending.append((play_with, age))
    return pending

def main(dry_run=False):
    from datetime import datetime

    # Load cities và combo đã crawl
    cities = load_cities(INPUT_FILE, CITY_COLUMN)
    _, combos_from_csv = load_existing_output_info(CSV_FILE)
    processed_from_pickle = safe_load_pickle(PROCESSED_FILE, set()) or set()
    existing_combo_set = set().union(combos_from_csv, processed_from_pickle)

    start_time = time.time()
    start_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"🚀 Crawl started at {start_dt}")

    # Build per-city pending combos
    city_args = []
    for city in cities:
        pending = build_pending_combos_for_city(city, existing_combo_set)
        if pending:
            city_args.append({"city": city, "pending_combos": pending, "dry_run": dry_run})
        else:
            logger.info(f"City {city} already fully completed, skipping.")

    if not city_args:
        print("No pending combos — everything is complete.")
        return

    # Tổng thống kê toàn bộ
    overall_stats = {
        "total_fetched": 0,
        "saved": 0,
        "skipped_name": 0,
        "skipped_other": 0,
    }
    failed_cities = []

    # Run multiprocessing
    with ProcessPoolExecutor(max_workers=min(MAX_PROCESSES, len(city_args))) as executor:
        futures = [executor.submit(process_city_worker, arg) for arg in city_args]

        for fut in tqdm(futures, desc="Cities", ncols=100):
            for current_retry in range(TOTAL_RETRIES):
                try:
                    res = fut.result()
                    logger.info(f"City finished: {res['city']} elapsed {res['elapsed']:.1f}s")
                    
                    # Update overall_stats
                    stats = res.get("stats", {})
                    overall_stats["total_fetched"] += stats.get("success",0)
                    overall_stats["saved"] += stats.get("success",0)
                    overall_stats["skipped_name"] += stats.get("skipped_name",0)
                    overall_stats["skipped_other"] += stats.get("skipped_cache",0) + stats.get("no_name",0) + stats.get("other_errors",0)
                    
                    # Nếu có failed trong city
                    if stats.get("failed",0) > 0:
                        failed_cities.append(res['city'])
                    break
                except Exception as e:
                    logger.exception(f"City future error: {e}. Retry: {current_retry+1}", exc_info=True)
                    print(f"City future error: {e}. Retry: {current_retry+1}")
                    time.sleep(min(0.5 * (2 ** current_retry) + random.random(), 10.0))

    # Log tổng kết
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
    

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="simulate requests (no real API calls)")
    args = parser.parse_args()
    main(dry_run=args.dry_run)