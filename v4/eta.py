"""
ETA Calculator for v4 crawler.
"""
import time
from typing import Final


class ETACalculator:
    def __init__(self, total_combos: int) -> None:
        self.total_combos: Final[int] = total_combos
        self.completed_combos: int = 0
        self.start_time: float = time.time()
        self.last_update: float = self.start_time
        self.combos_per_second: float = 0.0

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