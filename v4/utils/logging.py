"""
Shared logging utilities for v4 crawler.
"""
import logging
import traceback
import sys
from typing import Optional

from v4.types import CityName, ClubId


def log_error_with_context(
    logger: logging.Logger,
    message: str,
    city: Optional[CityName] = None,
    club_id: Optional[ClubId] = None,
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
    tb_str = traceback.format_exc() if error else ""

    full_msg = (
        f"[ERROR] {message} | {context_str} | "
        f"Location: {func_name}@{filename}:{lineno}"
    )

    log_func = getattr(logger, level, logger.error)
    if tb_str:
        log_func(f"{full_msg}\n{tb_str}")
    else:
        log_func(full_msg)