from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    """A minimal in-memory sliding-window rate limiter."""

    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str) -> bool:
        """Record an attempt for `key`. Returns True if it's allowed, False if rate-limited."""
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window_seconds:
                bucket.popleft()

            if len(bucket) >= self.max_attempts:
                return False

            bucket.append(now)
            return True


login_limiter = RateLimiter(max_attempts=10, window_seconds=60)
register_limiter = RateLimiter(max_attempts=5, window_seconds=60)
verify_limiter = RateLimiter(max_attempts=10, window_seconds=60)
