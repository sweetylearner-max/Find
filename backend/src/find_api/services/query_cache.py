from cachetools import TTLCache
from threading import Lock

CACHE_MAXSIZE = 128
CACHE_TTL_SECONDS = 300

_query_cache = TTLCache(maxsize=CACHE_MAXSIZE, ttl=CACHE_TTL_SECONDS)
_cache_lock = Lock()

INDEX_VERSION = 0


def normalize_query(query: str, limit: int, skip: int) -> str:
    normalized_query = " ".join(query.lower().split())
    return f"{normalized_query}:{limit}:{skip}"


def get_cached_query(query: str, limit: int, skip: int):
    normalized = normalize_query(query, limit, skip)

    with _cache_lock:
        entry = _query_cache.get(normalized)

        if not entry:
            return None

        if entry["index_version"] != INDEX_VERSION:
            _query_cache.pop(normalized, None)
            return None

        return entry


def set_cached_query(query: str, limit: int, skip: int, embedding, results):
    normalized = normalize_query(query, limit, skip)

    with _cache_lock:
        _query_cache[normalized] = {
            "embedding": embedding,
            "results": results,
            "index_version": INDEX_VERSION,
        }


def invalidate_query_cache():
    global INDEX_VERSION

    with _cache_lock:
        INDEX_VERSION += 1
        _query_cache.clear()


def clear_query_cache():
    with _cache_lock:
        _query_cache.clear()