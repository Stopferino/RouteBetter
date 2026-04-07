"""
Flight Optimizer - Mock Data Generator & Cache Integrity Checker

Provides:
  - check_cache_integrity(cache_file)           → validate cached flight data
  - generate_mock_flights(base_data, ...)       → produce realistic mock flights
  - load_mock_flights_from_cache(cache_file, ..)→ convenience loader
"""

import copy
import json
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Fields every stored flight dict must contain
_REQUIRED_FLIGHT_FIELDS: frozenset[str] = frozenset({
    "price", "duration_minutes", "stops", "airline",
})


# ─── Cache integrity ──────────────────────────────────────────────────────────

def check_cache_integrity(cache_file: str = "flight_cache.json") -> dict:
    """
    Verifies the flight cache file:
      - File exists and is readable
      - At least one outbound-search entry is present
      - Every stored flight has the required fields

    Returns a dict:
      {
        "ok":           bool,
        "entries":      int,   # number of outbound-search entries
        "total_flights": int,  # sum of all stored flights
        "issues":       list[str],
      }
    """
    path = Path(cache_file)
    issues: list[str] = []

    if not path.exists():
        msg = f"Cache file not found: {cache_file}"
        logger.warning(msg)
        return {"ok": False, "entries": 0, "total_flights": 0, "issues": [msg]}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as exc:
        msg = f"Cache unreadable: {exc}"
        logger.warning(msg)
        return {"ok": False, "entries": 0, "total_flights": 0, "issues": [msg]}

    if not data:
        msg = "Cache file exists but is empty"
        logger.warning(msg)
        return {"ok": False, "entries": 0, "total_flights": 0, "issues": [msg]}

    valid_entries = 0
    total_flights = 0

    for key, entry in data.items():
        # Return-leg entries are stored under a "return__…" prefix — skip structural check
        if key.startswith("return__"):
            continue

        if not isinstance(entry, dict):
            issues.append(f"Key {key!r}: entry is not a dict")
            continue

        if "results" not in entry:
            issues.append(f"Key {key!r}: missing 'results' field")
            continue

        results = entry["results"]
        if not isinstance(results, list):
            issues.append(f"Key {key!r}: 'results' is not a list")
            continue

        for i, flight in enumerate(results):
            missing = _REQUIRED_FLIGHT_FIELDS - set(flight.keys())
            if missing:
                issues.append(
                    f"Key {key!r}, flight #{i}: missing required fields {missing}"
                )

        total_flights += len(results)
        valid_entries += 1

    ok = len(issues) == 0 and valid_entries > 0
    status = "OK" if ok else "ISSUES FOUND"
    logger.info(
        f"Cache integrity [{status}]: {valid_entries} entries, "
        f"{total_flights} flights — issues: {len(issues)}"
    )
    return {
        "ok": ok,
        "entries": valid_entries,
        "total_flights": total_flights,
        "issues": issues,
    }


# ─── Mock data helpers ────────────────────────────────────────────────────────

def _shift_time(time_str: str, delta_minutes: int) -> str:
    """
    Shifts a flight time string by *delta_minutes*.
    Handles both SerpApi formats:
      '2026-07-25 19:40'   → full datetime
      '7:40 PM'            → time-only (no date shift; wraps to next day silently)
    Returns the original string unchanged on parse failure.
    """
    for fmt in ("%Y-%m-%d %H:%M", "%I:%M %p", "%H:%M"):
        try:
            dt = datetime.strptime(time_str.strip(), fmt)
            dt += timedelta(minutes=delta_minutes)
            return dt.strftime(fmt)
        except (ValueError, AttributeError):
            continue
    return time_str


def generate_mock_flights(
    base_data: list[dict],
    outbound_date: Optional[str] = None,
    return_date: Optional[str] = None,
    price_variation: float = 0.15,
    duration_variation: float = 0.05,
) -> list[dict]:
    """
    Generates realistic mock flights by randomising an existing list of
    real/cached flight dicts.

    Per flight:
      - price           → adjusted by ±*price_variation* (default ±15 %)
      - duration_minutes→ adjusted by ±*duration_variation* (default ±5 %)
      - segment times   → shifted by a random ±30-minute offset
      - outbound_date / return_date → replaced if provided

    Args:
        base_data:          List of flight dicts (e.g. from cache) to templatise.
        outbound_date:      Override outbound date (YYYY-MM-DD). Keeps original if None.
        return_date:        Override return date (YYYY-MM-DD). Keeps original if None.
        price_variation:    Max fractional price change (0.15 = ±15 %).
        duration_variation: Max fractional duration change (0.05 = ±5 %).

    Returns:
        New list of mock flight dicts — originals are never mutated.
    """
    if not base_data:
        logger.warning("generate_mock_flights: base_data is empty — returning []")
        return []

    mock_flights: list[dict] = []

    for flight in base_data:
        mock = copy.deepcopy(flight)

        # ── Price ──────────────────────────────────────────────────────────
        base_price = float(mock.get("price") or 500)
        factor = 1.0 + random.uniform(-price_variation, price_variation)
        mock["price"] = round(base_price * factor, 2)

        # ── Duration ───────────────────────────────────────────────────────
        base_dur = int(mock.get("duration_minutes") or 600)
        dur_delta = int(base_dur * random.uniform(-duration_variation, duration_variation))
        mock["duration_minutes"] = max(60, base_dur + dur_delta)

        # ── Dates ──────────────────────────────────────────────────────────
        if outbound_date:
            mock["outbound_date"] = outbound_date
        if return_date:
            mock["return_date"] = return_date

        # ── Segment times ──────────────────────────────────────────────────
        time_offset_min = random.randint(-30, 30)
        for seg in mock.get("outbound_segments", []):
            if isinstance(seg, dict):
                if seg.get("from_time"):
                    seg["from_time"] = _shift_time(seg["from_time"], time_offset_min)
                if seg.get("to_time"):
                    seg["to_time"] = _shift_time(seg["to_time"], time_offset_min)

        # Mark as mock so callers can detect it
        mock["_is_mock"] = True
        mock_flights.append(mock)

    logger.info(
        f"generate_mock_flights: {len(mock_flights)} mock flight(s) generated "
        f"from {len(base_data)} template(s)"
    )
    return mock_flights


def load_mock_flights_from_cache(
    cache_file: str = "flight_cache.json",
    outbound_date: Optional[str] = None,
    return_date: Optional[str] = None,
    price_variation: float = 0.15,
    duration_variation: float = 0.05,
) -> list[dict]:
    """
    Convenience function: reads *all* outbound-search entries from the cache
    and returns a fresh batch of mock flights ready to use as test data.

    Returns an empty list if the cache is missing or empty.
    """
    path = Path(cache_file)
    if not path.exists():
        logger.warning(f"load_mock_flights_from_cache: cache not found ({cache_file})")
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as exc:
        logger.warning(f"load_mock_flights_from_cache: could not read cache — {exc}")
        return []

    all_base: list[dict] = []
    for key, entry in data.items():
        if key.startswith("return__"):
            continue
        if isinstance(entry, dict) and isinstance(entry.get("results"), list):
            all_base.extend(entry["results"])

    if not all_base:
        logger.warning("load_mock_flights_from_cache: no usable flights found in cache")
        return []

    return generate_mock_flights(
        all_base,
        outbound_date=outbound_date,
        return_date=return_date,
        price_variation=price_variation,
        duration_variation=duration_variation,
    )
