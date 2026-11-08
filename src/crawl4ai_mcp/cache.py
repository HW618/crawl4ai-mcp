"""Tiny in-process TTL cache for successful crawl results."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class TtlCache(Generic[T]):
    def __init__(self, ttl_sec: float = 60.0, max_entries: int = 64):
        self.ttl_sec = max(0.0, float(ttl_sec))
        self.max_entries = max(1, int(max_entries))
        self._items: dict[str, _Entry[T]] = {}

    @property
    def enabled(self) -> bool:
        return self.ttl_sec > 0

    def clear(self) -> None:
        self._items.clear()

    def get(self, key: str) -> T | None:
        if not self.enabled:
            return None
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            self._items.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: T) -> None:
        if not self.enabled:
            return
        if len(self._items) >= self.max_entries and key not in self._items:
            # Drop the earliest-expiring entry.
            oldest = min(self._items.items(), key=lambda kv: kv[1].expires_at)
            self._items.pop(oldest[0], None)
        self._items[key] = _Entry(value=value, expires_at=time.monotonic() + self.ttl_sec)
