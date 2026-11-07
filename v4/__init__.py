"""
v4 - Async API Football Club Crawler

A high-performance asynchronous crawler for football club data
using the find.englandfootball.com API.

Features:
- Multiprocessing + AsyncIO hybrid execution
- Adaptive concurrency limiter
- Pickle-based caching & checkpoint recovery
- Exponential backoff retry with jitter
- CSV output with file locking
- Progress tracking with tqdm

Usage:
    python -m v4 [--dry-run] [--limit N] [--max-combos N]
"""