"""
Data models and classes for v4 crawler.
"""
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from v4.types import StatsDict

logger = logging.getLogger(__name__)


class AdaptiveLimiter:
    """
    Adaptive concurrency limiter that adjusts based on server response.
    Reduces concurrency on failures, increases on successes.
    """

    def __init__(
        self,
        initial_concurrent: int,
        min_concurrent: int = 5,
        max_concurrent: int = 100
    ) -> None:
        self.concurrent = initial_concurrent
        self.min_concurrent = min_concurrent
        self.max_concurrent = max_concurrent
        self.sem = asyncio.Semaphore(self.concurrent)
        self.failed_count = 0
        self.success_count = 0

    async def acquire(self) -> None:
        await self.sem.acquire()

    def release(self) -> None:
        self.sem.release()

    async def record_failure(self) -> None:
        """Record a failure and reduce concurrency if too many failures."""
        self.failed_count += 1
        if self.failed_count >= 3:
            old = self.concurrent
            self.concurrent = max(self.min_concurrent, int(self.concurrent * 0.8))
            diff = old - self.concurrent
            for _ in range(diff):
                await self.sem.acquire()
            self.failed_count = 0
            logger.warning(f"[AdaptiveLimiter] Server issues detected, reduced concurrency to {self.concurrent}")

    async def record_success(self) -> None:
        """Record a success and increase concurrency if stable."""
        self.success_count += 1
        if self.success_count >= 10 and self.concurrent < self.max_concurrent:
            self.concurrent += 1
            self.sem.release()
            self.success_count = 0
            logger.info(f"[AdaptiveLimiter] Server stable, increased concurrency to {self.concurrent}")