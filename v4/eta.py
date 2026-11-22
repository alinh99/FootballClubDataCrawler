"""
ETA Calculator for v4 crawler - supports both combo-level and club-level tracking.
"""
import time
import logging
from typing import Final, Optional

logger = logging.getLogger(__name__)


class ETACalculator:
    def __init__(self, total: int, label: str = "items") -> None:
        self.total: Final[int] = total
        self.label: Final[str] = label
        self.completed: int = 0
        self.start_time: float = time.time()
        self.last_log_time: float = 0
        self.last_log_completed: int = 0
        self.rate: float = 0.0

    def update(self, completed: int) -> None:
        """Update completed count and calculate rate."""
        self.completed = completed
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            self.rate = completed / elapsed

    def increment(self) -> None:
        """Increment completed count by 1."""
        self.update(self.completed + 1)

    def get_eta_str(self) -> str:
        if self.completed >= self.total:
            return "0s"
        if self.rate <= 0:
            return "calculating..."
        remaining = self.total - self.completed
        eta_seconds = remaining / self.rate
        hours, remainder = divmod(int(eta_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours:02d}h{minutes:02d}m{seconds:02d}s"
        return f"{minutes:02d}m{seconds:02d}s"

    def get_progress_str(self) -> str:
        pct = (self.completed / self.total * 100) if self.total > 0 else 0
        return f"{self.completed}/{self.total} {self.label} ({pct:.1f}%)"

    def get_rate_str(self) -> str:
        if self.rate > 0:
            return f"{self.rate:.1f} {self.label}/s"
        elif self.completed > 0:
            # Completed items but rate not yet calculated (very fast)
            elapsed = time.time() - self.start_time
            if elapsed > 0:
                return f"{self.completed / elapsed:.1f} {self.label}/s"
        return f"0.0 {self.label}/s"

    def log_progress(self, logger: logging.Logger, prefix: str = "", force: bool = False, log_interval: int = 10) -> None:
        """Log progress to console and file at specified intervals."""
        now = time.time()
        # Log every log_interval items, or if forced, or if significant time passed (30s)
        should_log = (
            force or
            self.completed >= self.total or
            (self.completed - self.last_log_completed >= log_interval) or
            (now - self.last_log_time >= 30)
        )
        if should_log:
            msg = f"{prefix}{self.get_progress_str()} | Rate: {self.get_rate_str()} | ETA: {self.get_eta_str()}"
            logger.info(msg)
            # Also print to console for immediate visibility
            print(msg)
            self.last_log_time = now
            self.last_log_completed = self.completed


class PhaseETACalculator:
    """Combined ETA calculator for Phase 1 + Phase 2 with club-level detail."""

    def __init__(self, total_combos: int, total_clubs_phase1: int = 0, total_clubs_phase2: int = 0):
        self.combo_eta = ETACalculator(total_combos, "combos")
        self.phase1_eta = ETACalculator(total_clubs_phase1, "clubs") if total_clubs_phase1 > 0 else None
        self.phase2_eta = ETACalculator(total_clubs_phase2, "clubs") if total_clubs_phase2 > 0 else None
        self.phase1_started = False
        self.phase2_started = False

    def start_phase1(self, total_clubs: int) -> None:
        self.phase1_eta = ETACalculator(total_clubs, "clubs")
        self.phase1_started = True
        logger.info(f"[Phase 1] Starting: {total_clubs} clubs to process")

    def update_phase1(self, completed: int) -> None:
        if self.phase1_eta:
            self.phase1_eta.update(completed)

    def log_phase1(self, logger: logging.Logger, city: str, force: bool = False) -> None:
        if self.phase1_eta:
            self.phase1_eta.log_progress(logger, f"[Phase 1] [{city}] ", force=force, log_interval=5)

    def start_phase2(self, total_clubs: int) -> None:
        self.phase2_eta = ETACalculator(total_clubs, "clubs")
        self.phase2_started = True
        logger.info(f"[Phase 2] Starting: {total_clubs} clubs to process")

    def update_phase2(self, completed: int) -> None:
        if self.phase2_eta:
            self.phase2_eta.update(completed)

    def log_phase2(self, logger: logging.Logger, city: str, force: bool = False) -> None:
        if self.phase2_eta:
            self.phase2_eta.log_progress(logger, f"[Phase 2] [{city}] ", force=force, log_interval=5)

    def update_combo(self, completed: int) -> None:
        self.combo_eta.update(completed)

    def log_combo(self, logger: logging.Logger, force: bool = False) -> None:
        self.combo_eta.log_progress(logger, "[Overall] ", force=force, log_interval=10)

    def get_summary(self) -> str:
        parts = [f"Combos: {self.combo_eta.get_progress_str()}"]
        if self.phase1_eta:
            parts.append(f"Phase1: {self.phase1_eta.get_progress_str()}")
        if self.phase2_eta:
            parts.append(f"Phase2: {self.phase2_eta.get_progress_str()}")
        return " | ".join(parts)