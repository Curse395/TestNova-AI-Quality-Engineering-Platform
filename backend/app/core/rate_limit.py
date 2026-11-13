from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request


class InMemoryRateLimiter:
    """Thread-safe per-process sliding-window limiter with bounded key storage."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        if max_keys < 1:
            raise ValueError("Rate-limiter key capacity must be positive")
        self._clock = clock
        self._max_keys = max_keys
        self._events: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def check(
        self,
        scope: str,
        identity: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        now = self._clock()
        key = (scope, identity)
        with self._lock:
            events = self._events.setdefault(key, deque())
            cutoff = now - window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if not events and len(self._events) > self._max_keys:
                self._events.pop(key, None)
            if not events:
                self._events.pop(key, None)
                self._prune_empty_keys(cutoff)
                if len(self._events) >= self._max_keys:
                    return False, 1
                events = self._events.setdefault(key, deque())
            if len(events) >= limit:
                return False, max(1, math.ceil(events[0] + window_seconds - now))
            events.append(now)
            return True, 0

    def _prune_empty_keys(self, cutoff: float) -> None:
        expired = [
            key
            for key, events in self._events.items()
            if not events or events[-1] <= cutoff
        ]
        for key in expired:
            self._events.pop(key, None)


rate_limiter = InMemoryRateLimiter()


def limit_requests(
    scope: str,
    *,
    limit: int,
    window_seconds: int,
) -> Callable[[Request], None]:
    if limit < 1 or window_seconds < 1:
        raise ValueError("Rate-limit count and window must be positive")

    def enforce(request: Request) -> None:
        client = request.client
        identity = client.host if client is not None else "unknown"
        allowed, retry_after = rate_limiter.check(
            scope,
            identity,
            limit=limit,
            window_seconds=window_seconds,
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )

    return enforce
