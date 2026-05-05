import time
from collections import OrderedDict


class SimpleCache:
    """LRU TTL cache. max_size prevents unbounded memory growth."""

    def __init__(self, ttl: float, max_size: int = 200):
        self._ttl      = ttl
        self._max_size = max_size
        self._store: OrderedDict = OrderedDict()

    def get(self, key):
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() - entry["ts"] > self._ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return entry["data"]

    def set(self, key, value):
        self._store[key] = {"ts": time.time(), "data": value}
        self._store.move_to_end(key)
        if len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def invalidate(self, key):
        self._store.pop(key, None)


# ---------------------------------------------------------------------------
# Shared cache instances — imported by routers
# ---------------------------------------------------------------------------
news_cache     = SimpleCache(ttl=15 * 60,   max_size=1)
macro_cache    = SimpleCache(ttl=60,         max_size=1)
screener_cache = SimpleCache(ttl=25 * 60,   max_size=11)
earnings_cache = SimpleCache(ttl=4 * 3600,  max_size=1)
options_cache  = SimpleCache(ttl=120,        max_size=100)
sector_cache   = SimpleCache(ttl=24 * 3600, max_size=500)
yields_cache   = SimpleCache(ttl=3600,       max_size=1)
