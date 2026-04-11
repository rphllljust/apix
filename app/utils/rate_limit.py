"""Responsabilidade: implementa o modulo app/utils/rate_limit.py."""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque


class InMemoryRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60) -> None:
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1, int(window_seconds))
        self._hits: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        async with self._lock:
            queue = self._hits.setdefault(key, deque())
            while queue and (now - queue[0]) >= self.window_seconds:
                queue.popleft()

            if len(queue) >= self.max_requests:
                retry_after = math.ceil(self.window_seconds - (now - queue[0]))
                return False, max(retry_after, 1)

            queue.append(now)
            return True, 0

