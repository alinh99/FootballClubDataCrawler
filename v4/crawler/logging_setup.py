"""
Logging setup for worker processes - ensures logging works in multiprocessing.
"""
import logging
import os
from v4.config import LOG_FILE


class FlushingFileHandler(logging.FileHandler):
    """FileHandler that flushes after every emit."""
    def emit(self, record):
        super().emit(record)
        self.flush()


class FlushingStreamHandler(logging.StreamHandler):
    """StreamHandler that flushes after every emit."""
    def emit(self, record):
        super().emit(record)
        self.flush()


def setup_worker_logging() -> logging.Logger:
    """
    Setup logging for a worker process.
    Each process gets its own handlers to avoid conflicts.
    """
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Clear any existing handlers
    logger.handlers.clear()

    # File handler - append mode for multiprocessing, flush immediately
    file_handler = FlushingFileHandler(LOG_FILE, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console handler - flush immediately
    console_handler = FlushingStreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger


def get_worker_logger(name: str) -> logging.Logger:
    """Get a logger for a worker module."""
    return logging.getLogger(name)