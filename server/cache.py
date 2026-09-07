from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class CacheLookup(Generic[T]):
    value: T
    hit: bool


class ExpiringLruCache(Generic[T]):
    """A bounded, process-local cache that also coalesces identical calculations."""

    def __init__(self, *, max_entries: int, ttl_seconds: float) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._items: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._inflight: dict[str, _Pending] = {}
        self._lock = Lock()

    def get_or_compute(self, key: str, compute: Callable[[], T]) -> CacheLookup[T]:
        while True:
            with self._lock:
                now = time.monotonic()
                item = self._items.pop(key, None)
                if item is not None and item[0] > now:
                    self._items[key] = item
                    return CacheLookup(value=item[1], hit=True)
                pending = self._inflight.get(key)
                if pending is None:
                    pending = _Pending()
                    self._inflight[key] = pending
                    break
            pending.done.wait()

        try:
            value = compute()
        except BaseException:
            with self._lock:
                self._inflight.pop(key).done.set()
            raise
        with self._lock:
            self._items[key] = (time.monotonic() + self._ttl_seconds, value)
            while len(self._items) > self._max_entries:
                self._items.popitem(last=False)
            self._inflight.pop(key).done.set()
        return CacheLookup(value=value, hit=False)


class FixedWindowRateLimiter:
    """Per-process fixed-window limiter for expensive unauthenticated requests."""

    def __init__(self, *, limit: int, window_seconds: float, max_keys: int = 1_024) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if max_keys < 1:
            raise ValueError("max_keys must be at least 1")
        self._limit = limit
        self._window_seconds = window_seconds
        self._max_keys = max_keys
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        with self._lock:
            now = time.monotonic()
            stale_keys = [
                client_key
                for client_key, (started_at, _count) in self._buckets.items()
                if now >= started_at + self._window_seconds
            ]
            for stale_key in stale_keys:
                del self._buckets[stale_key]
            if key not in self._buckets and len(self._buckets) >= self._max_keys:
                oldest_key = min(self._buckets, key=lambda client_key: self._buckets[client_key][0])
                del self._buckets[oldest_key]
            window_start, count = self._buckets.get(key, (now, 0))
            if now >= window_start + self._window_seconds:
                window_start, count = now, 0
            retry_after = max(1, int(window_start + self._window_seconds - now))
            if count >= self._limit:
                return False, retry_after
            self._buckets[key] = (window_start, count + 1)
            return True, retry_after


class _Pending:
    def __init__(self) -> None:
        from threading import Event

        self.done = Event()
