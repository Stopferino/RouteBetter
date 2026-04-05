"""
Flight Optimizer - Local Request Cache
Stores API results in a JSON file to save search quota.
Entries older than CACHE_TTL_HOURS are treated as stale and re-fetched.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DEFAULT_CACHE_FILE = "flight_cache.json"
CACHE_TTL_HOURS = 48


def _is_fresh(fetched_at: str, ttl_hours: int = CACHE_TTL_HOURS) -> bool:
    """Returns True if the cache entry is younger than ttl_hours."""
    try:
        fetched = datetime.strptime(fetched_at, "%Y-%m-%d %H:%M")
        return (datetime.now() - fetched).total_seconds() < ttl_hours * 3600
    except (ValueError, TypeError):
        return True  # fail open: unknown format → treat as fresh


def _age_hours(fetched_at: str) -> float | None:
    """Returns the age in hours of a cache entry, or None on parse error."""
    try:
        fetched = datetime.strptime(fetched_at, "%Y-%m-%d %H:%M")
        return round((datetime.now() - fetched).total_seconds() / 3600, 1)
    except (ValueError, TypeError):
        return None


def _cache_key(origin: str, destination: str, outbound_date: str, return_date: str) -> str:
    return f"{origin}_{destination}_{outbound_date}_{return_date}"


def load_cache(cache_file: str = DEFAULT_CACHE_FILE) -> dict:
    path = Path(cache_file)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Cache loaded: {len(data)} stored request(s) ({cache_file})")
        return data
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Cache could not be read ({e}), starting empty.")
        return {}


def save_cache(cache: dict, cache_file: str = DEFAULT_CACHE_FILE):
    """Atomically write the cache to disk (temp-file + rename) so a crash
    mid-write never leaves a corrupt JSON file."""
    import os, tempfile
    path = Path(cache_file)
    try:
        dir_ = path.parent or Path(".")
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=dir_, delete=False, suffix=".tmp"
        ) as tmp:
            json.dump(cache, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, cache_file)
    except (IOError, OSError) as e:
        logger.warning(f"Cache could not be saved: {e}")


def get_cached(
    cache: dict,
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str,
) -> list[dict] | None:
    """Returns cached results, or None if not present or stale (> 48 h)."""
    key = _cache_key(origin, destination, outbound_date, return_date)
    if key in cache:
        entry = cache[key]
        if not _is_fresh(entry.get("fetched_at", "")):
            logger.info(
                f"Cache stale (>48 h): {origin}->{destination} | {outbound_date}<->{return_date}"
            )
            return None
        logger.info(
            f"Cache hit: {origin}->{destination} | {outbound_date}<->{return_date} "
            f"({len(entry['results'])} result(s), fetched at {entry['fetched_at']})"
        )
        return entry["results"]
    return None


def get_cache_age_hours(
    cache: dict,
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str,
) -> float | None:
    """Returns the age in hours of a cache entry, or None if not present."""
    key = _cache_key(origin, destination, outbound_date, return_date)
    entry = cache.get(key)
    if entry:
        return _age_hours(entry.get("fetched_at", ""))
    return None


def set_cached(
    cache: dict,
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str,
    results: list[dict],
):
    """Stores outbound results in the cache dictionary (not yet written to disk)."""
    key = _cache_key(origin, destination, outbound_date, return_date)
    # Strip flight_details (too large, not needed for score calculation)
    slim_results = [
        {k: v for k, v in r.items() if k != "flight_details"}
        for r in results
    ]
    cache[key] = {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "results": slim_results,
    }


# ── Return-leg cache (keyed by departure_token) ────────────────────────────────

def get_cached_return(cache: dict, departure_token: str) -> dict | None:
    """Returns cached return-leg detail for a given departure_token, or None if stale."""
    key = f"return__{departure_token[:32]}"
    entry = cache.get(key)
    if entry:
        if not _is_fresh(entry.get("fetched_at", "")):
            logger.debug(f"Return-leg cache stale (>48 h): {key[:40]}...")
            return None
        logger.debug(f"Return-leg cache hit: {key[:40]}...")
        return entry["data"]
    return None


def set_cached_return(cache: dict, departure_token: str, return_data: dict):
    """Stores return-leg detail in the cache dictionary (not yet written to disk)."""
    key = f"return__{departure_token[:32]}"
    cache[key] = {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data": return_data,
    }


def clear_cache(cache_file: str = DEFAULT_CACHE_FILE):
    """Deletes the entire cache file."""
    path = Path(cache_file)
    if path.exists():
        path.unlink()
        logger.info(f"Cache cleared: {cache_file}")
    else:
        logger.info("No cache file found.")
