"""
Storage package for v4 crawler.
Re-exports all storage utilities.
"""

# Pickle utilities
from v4.storage.pickle_utils import safe_load_pickle, atomic_pickle_dump

# JSON Checkpoint (new - human readable)
from v4.storage.json_checkpoint import (
    save_checkpoint_json,
    load_checkpoint_json,
    log_checkpoint_status,
    log_error_to_file,
    get_resume_plan,
    CHECKPOINT_JSON_FILE,
    ERROR_LOG_FILE,
)

# CSV writer (async queue-based)
from v4.storage.csv_writer import (
    AsyncCSVWriter,
    get_csv_writer,
    get_csv_basic_writer,
    async_append_csv_rows_safe,
    async_append_basic_csv_rows,
    close_csv_writer,
    close_csv_basic_writer,
    close_all_csv_writers,
)

# CSV reading utilities
from v4.storage.csv_utils import (
    load_existing_csv,
    load_existing_output_info,
    load_cities,
    get_processed_combos_from_csv,
)

# Checkpoint utilities (legacy pickle)
from v4.storage.checkpoint import save_checkpoint, load_checkpoint

# Summary utilities
from v4.storage.summary import save_summary_csv

__all__ = [
    # Pickle
    "safe_load_pickle",
    "atomic_pickle_dump",
    # JSON Checkpoint
    "save_checkpoint_json",
    "load_checkpoint_json",
    "log_checkpoint_status",
    "log_error_to_file",
    "get_resume_plan",
    "CHECKPOINT_JSON_FILE",
    "ERROR_LOG_FILE",
    # CSV Writer
    "AsyncCSVWriter",
    "get_csv_writer",
    "get_csv_basic_writer",
    "async_append_csv_rows_safe",
    "async_append_basic_csv_rows",
    "close_csv_writer",
    "close_csv_basic_writer",
    "close_all_csv_writers",
    # CSV Reading
    "load_existing_csv",
    "load_existing_output_info",
    "load_cities",
    "get_processed_combos_from_csv",
    # Checkpoint (legacy)
    "save_checkpoint",
    "load_checkpoint",
    # Summary
    "save_summary_csv",
]