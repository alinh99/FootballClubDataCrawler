"""
Summary CSV utilities for v4 crawler.
"""
import os
import time
import logging
from typing import Dict, List, Any

import pandas as pd

from v4.types import CityName, StatsDict

logger = logging.getLogger(__name__)


def save_summary_csv(
    cities: List[CityName],
    overall_stats: StatsDict,
    failed_cities: List[CityName],
    start_dt: str,
    elapsed: float
) -> None:
    """Save summary report to CSV."""
    try:
        hours, remainder = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(remainder, 60)
        end_dt = time.strftime("%Y-%m-%d %H:%M:%S")

        summary_row: Dict[str, Any] = {
            "Date": time.strftime("%Y-%m-%d"),
            "Start Time": start_dt,
            "End Time": end_dt,
            "Duration": f"{hours:02d}:{minutes:02d}:{seconds:02d}",
            "Total Cities": len(cities),
            "Failed Cities": len(failed_cities),
            "Fetched": overall_stats.get("total_fetched", 0),
            "Saved": overall_stats.get("saved", 0),
            "Skipped (Same City)": overall_stats.get("skipped_name", 0),
            "Skipped (Other)": overall_stats.get("skipped_other", 0),
            "Failed City Names": ", ".join(failed_cities) if failed_cities else "",
            "Status": "❌ PARTIAL" if failed_cities else "✅ SUCCESS"
        }

        summary_path = "logs/summary_report.csv"
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)

        df = pd.DataFrame([summary_row])
        if os.path.exists(summary_path):
            df.to_csv(summary_path, mode="a", header=False, index=False)
        else:
            df.to_csv(summary_path, mode="w", header=True, index=False)
    except Exception as e:
        logger.error(f"save_summary_csv failed: {e}")