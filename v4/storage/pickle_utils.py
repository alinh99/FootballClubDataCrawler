"""
Pickle utilities for v4 crawler: safe load and atomic dump.
"""
import os
import pickle
import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def safe_load_pickle(path: str, default: Any) -> Any:
    """Safely load pickle file with fallback."""
    try:
        if os.path.exists(path):
            with open(path, "rb") as f:
                return pickle.load(f)
    except Exception as e:
        logger.warning(f"safe_load_pickle failed for {path}: {e}")
    return default


def atomic_pickle_dump(data: Any, path: str) -> None:
    """Atomically save pickle file using temp file + replace."""
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "wb") as f:
            pickle.dump(data, f)
        os.replace(tmp_path, path)
    except Exception as e:
        logger.error(f"atomic_pickle_dump failed for {path}: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


async def async_atomic_pickle_dump(data: Any, path: str) -> None:
    """Async version of atomic_pickle_dump - runs in thread pool to avoid blocking."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, atomic_pickle_dump, data, path)