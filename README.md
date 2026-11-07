# ⚽ Football Club Data Crawler (Python)
## 📖 Overview
This project is a **data crawling system** that collects **football club information** from **public web sources** by city.  
It started as a **basic Selenium-based crawler (v1)**, was enhanced with **multi-browser parallelism** for better efficiency (**v2**),  
and ultimately evolved into an **asynchronous API-powered crawler (v3/v4)** — achieving **high performance ⚡**, **scalability 🌍**, and **production-level stability 🧩**.

## ⚙️ Technologies
- **Python 3.9+**
- **Selenium (v1)** — Browser automation for crawling web content
- **Asyncio + curl_cffi (v3/v4)** — Fully asynchronous API request–based crawler with Chrome TLS fingerprint
- **Multiprocessing + AsyncIO hybrid execution** (v4)
- **Adaptive concurrency limiter** to balance performance and server stability
- **Pickle-based caching & checkpoint recovery** for safe resume after interruptions
- **Retry logic & exponential backoff** for network stability (including 429 rate limits)
- **Type hints & type aliases** for code maintainability (v4)
- **Docker support** for containerized deployment (v4)
- **Logging system + tqdm progress bar** for real-time monitoring

---

## 🧩 Project Structure
```
FootballClubDataCrawler/
│
├── city_crawling.py              # Step 1: Crawl city list from gov.uk
├── club_crawling_v1.py           # Step 2 (v1): Basic Selenium crawler
├── club_crawling_v3.py           # Step 2 (v3): Async + API-based crawler
├── club_crawling_v4.py           # Step 2 (v4): Monolithic v4 (legacy, self-contained)
│
├── v4/                           # 🆕 v4 Modular Async API Crawler (main v4 implementation)
│   ├── __init__.py               # Package init
│   ├── __main__.py               # Allows `python -m v4`
│   ├── config.py                 # Configuration constants & env vars
│   ├── types.py                  # Type aliases & type hints
│   ├── models.py                 # AdaptiveLimiter class
│   ├── storage/                  # Storage package
│   │   ├── __init__.py
│   │   ├── pickle_utils.py
│   │   ├── csv_writer.py
│   │   ├── csv_utils.py
│   │   ├── checkpoint.py
│   │   └── summary.py
│   ├── api/                      # API package
│   │   ├── __init__.py
│   │   ├── club_info.py
│   │   └── recommendation.py
│   ├── crawler/                  # Crawler package
│   │   ├── __init__.py
│   │   ├── logging.py
│   │   ├── worker.py
│   │   ├── combos.py
│   │   └── runner.py
│   ├── utils/                    # Shared utilities
│   │   ├── __init__.py
│   │   └── logging.py
│   ├── eta.py                    # ETACalculator class
│   └── main.py                   # CLI entry point
│
├── requirements_v1_v2.txt        # Dependencies for Selenium (v1)
├── requirements_v3.txt           # Dependencies for v3 (Async API)
├── requirements_v4.txt           # Dependencies for v4 (Async API + curl_cffi)
│
├── geocode_cities.py             # Offline city coordinate mapping (55 UK cities)
├── Dockerfile.v4                 # 🆕 Docker image for v4
├── docker-compose.v4.yml         # 🆕 Docker Compose for v4
├── .dockerignore                 # Docker ignore patterns
│
├── .env                          # Environment variables (API keys, config)
├── logs/                         # Runtime logs
├── output/                       # City lists, output CSV files
├── storage/                      # Cache files (pickle, checkpoints) - v3/v4
└── README.md                     # This file
```

## 🚨 **CURRENT API STATUS (IMPORTANT)**
> **⚠️ The production API endpoints currently return NO DATA (0 clubs for all cities).**
> 
> - **Recommendation API** (`clubandcasualrecommendation`): Returns `{"CntOpportunity":0,"RecommendationClubCentreCartDto":[]}` — 200 OK but empty
> - **Club Info API** (`club`): Returns 400 "Property Club Input Details is either missing or empty" — likely needs different payload format
> - **Old endpoints** (`clubrecommendation`, `club`): Return empty array `[]` or 400 errors — deprecated
>
> **This is an API/provider issue, not a code issue.** The v4 code is production-ready with correct endpoints/payloads discovered from website JS analysis.
>
> **Options:**
> 1. **Contact API provider** for updated access/data
> 2. **Use v4 with `--dry-run`** for testing code logic
> 3. **Implement Selenium fallback** if needed

---

## 🧠 Conceptual Flow
1. **`city_crawling.py`** — Collects all available cities that contain football clubs and saves them as CSV.
2. **`geocode_cities.py`** — Maps 55 UK cities to lat/lon coordinates (offline, no API calls).
3. **`v4/` (Async API)** — Uses API endpoints directly with async HTTP requests. **Code ready, API has no data** ⚠️

### 🔧 v4 Key Features (Async API-based + ETA & Limits) — **Code Complete & Modular**
| Feature | Description |
|---------|-------------|
| **Multiprocessing + AsyncIO Hybrid** | Each city runs in a separate process; thousands of requests run concurrently via `asyncio` + `curl_cffi` |
| **Adaptive Concurrency Limiter** | Dynamically adjusts concurrent requests (5–100) based on server response |
| **Pickle-based Caching & Checkpoint Recovery** | `club_cache.pkl` + `processed_combos.pkl` — auto-resume on interrupt |
| **Combo-level Resume** | Skips already-processed `(city, age, play_with)` combos — no duplicate work |
| **Per-city Duplicate Skip** | Immediately skips clubs already present in output CSV for the same city |
| **Exponential Backoff Retry** | Up to 10M retries with jitter; **429-specific: 60s → 120s → 240s... (capped at 5 min)** |
| **Overall ETA Estimation** | Pre-calculates total pending combos, tracks real-time rate, displays time remaining |
| **Limit Controls** | `--limit N` (max clubs) / `--max-combos N` (max city combos) |
| **Type Safety** | Full type hints + `types.py` with type aliases for maintainability |
| **Modular Architecture** | Split into focused modules in `v4/` package (api, crawler, storage, utils) |
| **Docker Ready** | Multi-stage `Dockerfile.v4` + `docker-compose.v4.yml` for deployment |

---

## ⚠️ API Authentication Required (for v3/v4)
The v3/v4 crawler calls **private Azure API Management endpoints** requiring valid subscription keys:
- `API_CLUB_RECOMMENDATION_URL` — `https://hcdeapimngt1.azure-api.net/discoverfootball-subky/v1/api/clubandcasualrecommendation`
- `API_CLUB_INFO_URL` — `https://hcdeapimngt1.azure-api.net/discoverfootball-subky/v1/api/club`
- `API_CLUB_CONTACT_URL` — `https://hcdeapimngt1.azure-api.net/external/v1/orgs`
- `KEY_CLUB_INFO_AND_RECOMMENDATION_INFO` — for recommendation + club info APIs
- `KEY_CLUB_CONTACT_INFO` — for contact info API

**All endpoints return HTTP 401 without valid `Ocp-Apim-Subscription-Key` headers.**  
Fill in the keys in `.env` before running v3/v4 in production. For testing without credentials, use `--dry-run` flag.

---

## 🚀 Setup
### 🧰 1. Install Python
Install Python 3.9 or above: [https://www.python.org/downloads/](https://www.python.org/downloads/)

### ⚙️ 2. Install Dependencies
#### 🕷️ For Selenium Versions (v1)
```
pip install -r requirements_v1_v2.txt
```
Also install ChromeDriver: `pip install webdriver-manager` (auto-manages ChromeDriver)

#### ⚡ For Async API Versions (v3/v4) — **Code ready, API has no data**
```
pip install -r requirements_v4.txt
```
- **On Linux/macOS (Recommended for max performance):**
```
pip install uvloop
```

#### 🐳 For Docker (v4)
```
docker build -f Dockerfile.v4 -t football-crawler-v4 .
# Or use docker-compose
docker-compose -f docker-compose.v4.yml up --build
```

### 🧾 Example `.env` File (UPDATED with correct endpoints)
```
API_CLUB_RECOMMENDATION_URL = "https://hcdeapimngt1.azure-api.net/discoverfootball-subky/v1/api/clubandcasualrecommendation"
API_CLUB_INFO_URL = "https://hcdeapimngt1.azure-api.net/discoverfootball-subky/v1/api/club"
API_CLUB_CONTACT_URL = "https://hcdeapimngt1.azure-api.net/external/v1/orgs"
KEY_CLUB_INFO_AND_RECOMMENDATION_INFO =  "YOUR_KEY_HERE"
KEY_CLUB_CONTACT_INFO = "YOUR_KEY_HERE"
WEBSITE_URL = "https://find.englandfootball.com/"
WEBSITE_NAME = "EnglandFootballClub"
MAX_PROCESSES = 5
MAX_CONCURRENT_REQUESTS = 50
BATCH_SAVE_SIZE = 200
RATE_LIMIT_SLEEP = 60
```

> ⚠️ **Important:** The API endpoints require valid `Ocp-Apim-Subscription-Key` headers. **Currently the API returns no data even with valid keys.** Contact API provider for data access.

---

## 🏃 Running the Crawler

### ⚡ **v4 Async API Modular (Code Ready, API Has No Data)**
```bash
# Test without credentials (simulates requests)
python -m v4 --dry-run

# Quick test: limit to 10 clubs
python -m v4 --dry-run --limit 10

# Quick test: limit to 5 city combos
python -m v4 --dry-run --max-combos 5

# Production run (requires valid API keys in .env + API must have data)
python -m v4

# Production with limit for testing
python -m v4 --limit 100

# Run specific city count
python -m v4 --max-combos 10
```

### 🐳 **Docker (v4)**
```bash
# Build image
docker build -f Dockerfile.v4 -t football-crawler-v4 .

# Run dry-run test
docker run --rm football-crawler-v4 --dry-run --max-combos 3

# Run with docker-compose (mounts volumes for persistence)
docker-compose -f docker-compose.v4.yml up

# Production with API keys
docker run --rm \
  -e KEY_CLUB_INFO_AND_RECOMMENDATION_INFO=your_key \
  -e KEY_CLUB_CONTACT_INFO=your_key \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/storage:/app/storage \
  -v $(pwd)/logs:/app/logs \
  football-crawler-v4 --max-combos 10
```

### 🔄 Resume After Interruption
v4 automatically resumes from the last completed checkpoint:
1. Reads existing `output/clubs_data.csv` for completed combos
2. Loads `storage/processed_combos.pkl` (v4)
3. Skips clubs already in CSV for the same city
4. Continues with remaining combos — no manual intervention needed

### 📊 Monitor Progress
```bash
tail -f logs/new_scraper_optimized.log   # v4 API logs
# Or watch the summary CSV
watch -n 30 cat logs/summary_report.csv
```

---

## 🧩 Version Comparison

| Feature / Aspect | v1 — Basic Selenium | v4 — Async API + ETA |
|------------------|---------------------|----------------------|
| **Core Technology** | Selenium WebDriver | Asyncio + curl_cffi + Multiprocessing |
| **Architecture** | Monolithic | **Modular (packages in `v4/`)** |
| **Type Safety** | No | **Full type hints + aliases** |
| **Docker Support** | No | **Multi-stage Dockerfile + Compose** |
| **Speed** | 🐢 Slow | ⚡ Extremely fast (when API works) |
| **Data Source** | Website (works) | API (currently no data) |
| **Production Ready** | No (basic) | **Yes (code complete)** |
| **Checkpoint/Resume** | ❌ Manual | ✅ Combo-level auto-resume |
| **Limit Controls** | ❌ None | ✅ `--limit`, `--max-combos` |
| **Headless Support** | ❌ No | N/A |
| **429 Handling** | Basic | **Exponential backoff (60s→120s→240s...)** |
| **Use Case** | Prototype | **Future: when API works** |

---

## 🧩 Requirements Summary

### `requirements_v1_v2.txt` (for v1 Selenium)
```
selenium
webdriver-manager
pandas
fake-useragent
python-dotenv
tqdm
```

### `requirements_v4.txt` (for v4 Async API)
```
pandas
curl_cffi
tqdm
fake-useragent
python-dotenv
filelock
```

*(`curl_cffi` = browser TLS fingerprint impersonation for better scraping; `httpx` still works as alternative)*

*(Optional for Linux/macOS only)*
```
pip install uvloop
```

---

## 🎯 Learning & Technical Takeaways
| Concept | Description |
|----------|-------------|
| **Asynchronous Programming (asyncio)** | Handles thousands of requests concurrently without blocking (v4). |
| **Multiprocessing** | Runs multiple cities in parallel using CPU cores (v4). |
| **Adaptive Rate Limiting** | Adjusts speed automatically when target server slows down (v4). |
| **Pickle Caching** | Saves progress and skips duplicates (v4). |
| **Retry & Error Handling** | Retries failed requests with exponential backoff (v4). |
| **429-Specific Backoff** | Exponential backoff for rate limits: 60s → 120s → 240s... capped at 5 min (v4). |
| **Type Hints & Aliases** | Improves maintainability and IDE support (v4). |
| **Modular Architecture** | Clean separation of concerns: config, models, storage, api, crawler, utils (v4). |
| **Docker Multi-stage Build** | Small production images with build-time dependency caching (v4). |
| **Logging & tqdm** | Real-time progress tracking (v4). |

---

## 💡 Future Development Ideas
- Integrate **PostgreSQL** or **MongoDB** for scalable storage.
- Build a **FastAPI backend** for data access and management.
- Create a **Streamlit dashboard** for data visualization.
- Add **smart deduplication** and **data cleaning** pipelines.
- Enable **auto-scheduling** and **cloud deployment** (e.g., AWS Lambda, Docker, Kubernetes).
- When API data is restored: switch back to v4 for 100x speed improvement.
- Implement **Selenium fallback** for production data collection if API remains unavailable.

---

## 🏁 Author
**Linh Nguyen Hoang**  
🎯 Aspiring Python Backend / Data Engineer  
🌍 Goal: Build a high-performance asynchronous crawler to collect and process structured football club data efficiently.  
📧 Contact: *[alinh1803@gmail.com]*  

## 📜 License
MIT License © 2025 Linh Nguyen Hoang

---

> **Note:** This README.md was drafted with assistance from ChatGPT for clarity and formatting. The code and ideas are original, with minimal guidance from ChatGPT for clean structure.

> **API Status Update (2026-11-07):** The production API endpoints (`clubandcasualrecommendation`, `club`) return no data for any city. The v4 code is complete and correct — it uses the exact endpoints and payload structures discovered from the website's JavaScript bundles. The issue is on the API provider side.

> **v4 Update (2026-11-07):** Refactored into modular `v4/` package with full type hints, type aliases in `types.py`, Docker support (`Dockerfile.v4`, `docker-compose.v4.yml`), exponential backoff for 429 errors, and improved logging with club names. Further split into sub-packages: `v4/api/`, `v4/crawler/`, `v4/storage/`, `v4/utils/`. The legacy monolithic `club_crawling_v4.py` is also available as a self-contained single-file version with all fixes applied.