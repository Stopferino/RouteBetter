"""
Flight Optimizer - Lokaler Anfragen-Cache
Speichert API-Ergebnisse in einer JSON-Datei, um Search-Kontingent zu sparen.
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

DEFAULT_CACHE_FILE = "flight_cache.json"


def _cache_key(origin: str, destination: str, outbound_date: str, return_date: str) -> str:
    return f"{origin}_{destination}_{outbound_date}_{return_date}"


def load_cache(cache_file: str = DEFAULT_CACHE_FILE) -> dict:
    path = Path(cache_file)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Cache geladen: {len(data)} gespeicherte Anfragen ({cache_file})")
        return data
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Cache konnte nicht gelesen werden ({e}), starte leer.")
        return {}


def save_cache(cache: dict, cache_file: str = DEFAULT_CACHE_FILE):
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.warning(f"Cache konnte nicht gespeichert werden: {e}")


def get_cached(
    cache: dict,
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str,
) -> list[dict] | None:
    """Gibt gecachte Ergebnisse zurück, oder None wenn nicht vorhanden."""
    key = _cache_key(origin, destination, outbound_date, return_date)
    if key in cache:
        entry = cache[key]
        logger.info(
            f"Cache-Hit: {origin}→{destination} | {outbound_date}↔{return_date} "
            f"({len(entry['results'])} Ergebnisse, abgerufen am {entry['fetched_at']})"
        )
        return entry["results"]
    return None


def set_cached(
    cache: dict,
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str,
    results: list[dict],
):
    """Speichert Ergebnisse im Cache-Dictionary (noch nicht auf Disk)."""
    key = _cache_key(origin, destination, outbound_date, return_date)
    # flight_details weglassen (zu groß, nicht für Score-Berechnung nötig)
    slim_results = [
        {k: v for k, v in r.items() if k != "flight_details"}
        for r in results
    ]
    cache[key] = {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "results": slim_results,
    }


def clear_cache(cache_file: str = DEFAULT_CACHE_FILE):
    """Löscht den gesamten Cache."""
    path = Path(cache_file)
    if path.exists():
        path.unlink()
        logger.info(f"Cache gelöscht: {cache_file}")
    else:
        logger.info("Kein Cache vorhanden.")
