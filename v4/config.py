"""
Configuration constants for v4 crawler.
"""
import os
from typing import Dict, Final, Optional
from dotenv import load_dotenv

load_dotenv()

# ---------------- Folders ----------------
LOGS_FOLDER_NAME: Final[str] = "logs"
OUTPUT_FOLDER_NAME: Final[str] = "output"
STORAGE_FOLDER_NAME: Final[str] = "storage"

os.makedirs(OUTPUT_FOLDER_NAME, exist_ok=True)
os.makedirs(STORAGE_FOLDER_NAME, exist_ok=True)
os.makedirs(LOGS_FOLDER_NAME, exist_ok=True)

# ---------------- File Paths ----------------
INPUT_FILE: Final[str] = f"{OUTPUT_FOLDER_NAME}/england_city.csv"
CITY_COLUMN: Final[str] = "name"
CSV_FILE: Final[str] = f"{OUTPUT_FOLDER_NAME}/clubs_data.csv"
CSV_BASIC_FILE: Final[str] = f"{OUTPUT_FOLDER_NAME}/clubs_basic.csv"
CACHE_FILE: Final[str] = f"{STORAGE_FOLDER_NAME}/club_cache.pkl"
PROCESSED_FILE: Final[str] = f"{STORAGE_FOLDER_NAME}/processed_combos.pkl"
LOG_FILE: Final[str] = f"{LOGS_FOLDER_NAME}/new_scraper_optimized.log"
CSV_LOCK_FILE: Final[str] = os.path.join(STORAGE_FOLDER_NAME, "clubs_data.lock")
CSV_BASIC_LOCK_FILE: Final[str] = os.path.join(STORAGE_FOLDER_NAME, "clubs_basic.lock")

# ---------------- Config from .env ----------------
MAX_PROCESSES: Final[int] = int(os.getenv("MAX_PROCESSES", 5))
MAX_CONCURRENT_REQUESTS: Final[int] = int(os.getenv("MAX_CONCURRENT_REQUESTS", 50))
TOTAL_RETRIES: Final[int] = int(os.getenv("TOTAL_RETRIES", 1000000000))
BATCH_SAVE_SIZE: Final[int] = int(os.getenv("BATCH_SAVE_SIZE", 200))
RATE_LIMIT_SLEEP: Final[int] = int(os.getenv("RATE_LIMIT_SLEEP", 60))

# ---------------- API Endpoints ----------------
API_CLUB_RECOMMENDATION_URL: Final[str] = os.getenv(
    "API_CLUB_RECOMMENDATION_URL",
    "https://hcdeapimngt1.azure-api.net/discoverfootball-subky/v1/api/clubandcasualrecommendation"
)
API_CLUB_INFO_URL: Final[str] = os.getenv(
    "API_CLUB_INFO_URL",
    "https://hcdeapimngt1.azure-api.net/discoverfootball-subky/v1/api/club"
)
API_CLUB_CONTACT_URL: Final[str] = os.getenv(
    "API_CLUB_CONTACT_URL",
    "https://hcdeapimngt1.azure-api.net/external/v1/orgs"
)
KEY_CLUB_INFO_AND_RECOMMENDATION_INFO: Optional[str] = os.getenv("KEY_CLUB_INFO_AND_RECOMMENDATION_INFO")
KEY_CLUB_CONTACT_INFO: Optional[str] = os.getenv("KEY_CLUB_CONTACT_INFO")

# ---------------- City Coordinates ----------------
DEFAULT_LAT: Final[float] = 51.5074
DEFAULT_LON: Final[float] = -0.1278

CityCoordsDict = Dict[str, Dict[str, float]]

CITY_COORDS: Final[CityCoordsDict] = {
    "Bath": {"lat": 51.3758, "lon": -2.3599},
    "Birmingham": {"lat": 52.4862, "lon": -1.8904},
    "Bradford": {"lat": 53.7959, "lon": -1.7594},
    "Brighton & Hove": {"lat": 50.8225, "lon": -0.1372},
    "Bristol": {"lat": 51.4545, "lon": -2.5879},
    "Cambridge": {"lat": 52.2053, "lon": 0.1218},
    "Canterbury": {"lat": 51.2787, "lon": 1.0779},
    "Carlisle": {"lat": 54.8925, "lon": -2.9335},
    "Chelmsford": {"lat": 51.7356, "lon": 0.4685},
    "Chester": {"lat": 53.1934, "lon": -2.8931},
    "Chichester": {"lat": 50.8376, "lon": -0.7749},
    "Colchester": {"lat": 51.8959, "lon": 0.8919},
    "Coventry": {"lat": 52.4068, "lon": -1.5197},
    "Derby": {"lat": 52.9225, "lon": -1.4746},
    "Doncaster": {"lat": 53.5228, "lon": -1.1285},
    "Durham": {"lat": 54.7753, "lon": -1.5849},
    "Ely": {"lat": 52.3989, "lon": 0.2636},
    "Exeter": {"lat": 50.7184, "lon": -3.5339},
    "Gloucester": {"lat": 51.8642, "lon": -2.2382},
    "Hereford": {"lat": 52.0564, "lon": -2.7160},
    "Kingston-upon-Hull": {"lat": 53.7457, "lon": -0.3367},
    "Lancaster": {"lat": 54.0466, "lon": -2.8007},
    "Leeds": {"lat": 53.8008, "lon": -1.5491},
    "Leicester": {"lat": 52.6369, "lon": -1.1398},
    "Lichfield": {"lat": 52.6850, "lon": -1.8260},
    "Lincoln": {"lat": 53.2307, "lon": -0.5406},
    "Liverpool": {"lat": 53.4084, "lon": -2.9916},
    "London": {"lat": 51.5074, "lon": -0.1278},
    "Manchester": {"lat": 53.4808, "lon": -2.2426},
    "Milton Keynes": {"lat": 52.0406, "lon": -0.7594},
    "Newcastle-upon-Tyne": {"lat": 54.9783, "lon": -1.6178},
    "Norwich": {"lat": 52.6309, "lon": 1.2974},
    "Nottingham": {"lat": 52.9548, "lon": -1.1581},
    "Oxford": {"lat": 51.7520, "lon": -1.2577},
    "Peterborough": {"lat": 52.5695, "lon": -0.2405},
    "Plymouth": {"lat": 50.3755, "lon": -4.1427},
    "Portsmouth": {"lat": 50.8198, "lon": -1.0880},
    "Preston": {"lat": 53.7632, "lon": -2.7031},
    "Ripon": {"lat": 54.1370, "lon": -1.5219},
    "Salford": {"lat": 53.4875, "lon": -2.2901},
    "Salisbury": {"lat": 51.0698, "lon": -1.7951},
    "Sheffield": {"lat": 53.3811, "lon": -1.4701},
    "Southampton": {"lat": 50.9097, "lon": -1.4044},
    "Southend-on-Sea": {"lat": 51.5378, "lon": 0.7143},
    "St Albans": {"lat": 51.7527, "lon": -0.3394},
    "Stoke on Trent": {"lat": 53.0027, "lon": -2.1794},
    "Sunderland": {"lat": 54.9069, "lon": -1.3838},
    "Truro": {"lat": 50.2661, "lon": -5.0520},
    "Wakefield": {"lat": 53.6833, "lon": -1.4977},
    "Wells": {"lat": 51.2101, "lon": -2.6448},
    "Westminster": {"lat": 51.4994, "lon": -0.1348},
    "Winchester": {"lat": 51.0632, "lon": -1.3086},
    "Wolverhampton": {"lat": 52.5862, "lon": -2.1275},
    "Worcester": {"lat": 52.1912, "lon": -2.2219},
    "York": {"lat": 53.9614, "lon": -1.0776},
}