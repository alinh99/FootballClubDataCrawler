"""
Async CSV writer for v4 crawler: background queue-based non-blocking CSV writes.
Supports two-phase writing: basic (from recommendation) and detail (from club info).
"""
import os
import asyncio
import logging
from typing import List, Optional, Dict, Any

import pandas as pd
from filelock import FileLock

from v4.config import (
    CSV_FILE, CSV_BASIC_FILE,
    CSV_LOCK_FILE, CSV_BASIC_LOCK_FILE,
    BATCH_SAVE_SIZE
)
from v4.types import ClubRow, BasicClubRow

logger = logging.getLogger(__name__)


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
                # Ensure consistent column order
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


async def async_append_csv_rows_safe(rows: List[ClubRow]) -> None:
    """
    Non-blocking CSV append for detailed club data using background writer queue.
    Returns immediately after queuing rows.
    """
    if not rows:
        return
    writer = await get_csv_writer()
    await writer.write_rows(rows)


async def async_append_basic_csv_rows(rows: List[BasicClubRow]) -> None:
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