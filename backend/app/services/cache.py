"""Tiny in-process TTL cache with per-key locking.

Purpose: stop hammering the YCLIENTS API. Before this, every dashboard/slot/story
request re-downloaded the full record history. Now identical calls within the TTL
share one result, and concurrent callers wait on a single in-flight request
instead of firing N duplicate downloads.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from app.config import settings

_store: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _lock_for(key: str) -> asyncio.Lock:
    async with _locks_guard:
        if key not in _locks:
            _locks[key] = asyncio.Lock()
        return _locks[key]


async def cached(
    key: str,
    loader: Callable[[], Awaitable[Any]],
    ttl: int | None = None,
) -> Any:
    """Return a cached value or await ``loader`` once and cache the result."""
    ttl = settings.cache_ttl_seconds if ttl is None else ttl
    now = time.monotonic()

    hit = _store.get(key)
    if hit and hit[0] > now:
        return hit[1]

    lock = await _lock_for(key)
    async with lock:
        # Another coroutine may have filled the cache while we waited.
        hit = _store.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]

        logger.debug(f"cache miss: {key}")
        value = await loader()
        _store[key] = (time.monotonic() + ttl, value)
        return value


def invalidate(prefix: str = "") -> int:
    """Drop cache entries whose key starts with ``prefix`` ("" clears all)."""
    keys = [k for k in _store if k.startswith(prefix)]
    for k in keys:
        _store.pop(k, None)
    return len(keys)


def stats() -> dict[str, int]:
    now = time.monotonic()
    return {
        "entries": len(_store),
        "live": sum(1 for exp, _ in _store.values() if exp > now),
    }
