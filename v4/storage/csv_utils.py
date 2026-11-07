"""
CSV reading utilities for v4 crawler.
"""
import logging
from typing import Dict, List, Set, Tuple

import pandas as pd
import os

from v4.config import CSV_FILE, CITY_COLUMN, INPUT_FILE
from v4.types import CityName, ExistingClubNames, ProcessedCombos

logger = logging.getLogger(__name__)


def load_existing_csv(csv_path: str = CSV_FILE) -> ExistingClubNames:
    """Load existing clubs from CSV for duplicate checking."""
    if not os.path.exists(csv_path):
        return {}
    try:
        df = pd.read_csv(csv_path)
        existing: ExistingClubNames = {}
        for _, row in df.iterrows():
            city = row.get("City", "")
            name = row.get("Club Name", "")
            if city and name:
                existing.setdefault(city, set()).add(name.strip())
        return existing
    except Exception as e:
        logger.warning(f"load_existing_csv failed: {e}")
        return {}


def load_existing_output_info(csv_path: str = CSV_FILE) -> Tuple[ExistingClubNames, ProcessedCombos]:
    """Load existing clubs and processed combos from CSV."""
    import os
    existing_club_names: ExistingClubNames = {}
    combos_from_csv: ProcessedCombos = set()
    if not os.path.exists(csv_path):
        return existing_club_names, combos_from_csv
    try:
        df = pd.read_csv(csv_path)
        for _, row in df.iterrows():
            city = row.get("City", "")
            name = row.get("Club Name", "")
            play_with = row.get("PlayWith", "")
            age = row.get("Age", "")
            if city and name:
                existing_club_names.setdefault(city, set()).add(name.strip())
            if city and play_with != "" and age != "":
                combos_from_csv.add(f"{city}__{play_with}__{age}")
    except Exception as e:
        logger.warning(f"load_existing_output_info failed: {e}")
    return existing_club_names, combos_from_csv


def load_cities(input_file: str = INPUT_FILE, column: str = CITY_COLUMN) -> List[CityName]:
    """Load city list from CSV."""
    try:
        df = pd.read_csv(input_file)
        cities = sorted(df[column].dropna().unique().tolist())
        return cities
    except Exception as e:
        logger.error(f"load_cities failed: {e}")
        return []


def get_processed_combos_from_csv(csv_path: str = CSV_FILE) -> ProcessedCombos:
    """Get already processed combos from existing CSV."""
    import os
    if not os.path.exists(csv_path):
        return set()
    try:
        df = pd.read_csv(csv_path)
        combos: ProcessedCombos = set()
        for _, row in df.iterrows():
            city = row.get("City", "")
            play_with = row.get("PlayWith", "")
            age = row.get("Age", "")
            if city and play_with != "" and age != "":
                combos.add(f"{city}__{play_with}__{age}")
        return combos
    except Exception as e:
        logger.warning(f"get_processed_combos_from_csv failed: {e}")
        return set()