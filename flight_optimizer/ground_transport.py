"""
Ground transport calculator.

Uses:
- Nominatim (OpenStreetMap) for address geocoding — free, no API key.
- OSRM public API for driving distance + duration — free, no API key.

Calculates the driving leg from home to departure airport and from
arrival airport to the destination address, for each of the 6 airports.
"""

import logging
import time
import urllib.parse
import urllib.request
import json

logger = logging.getLogger(__name__)

# Coordinates for the six airports in the search grid
AIRPORT_COORDS = {
    "HKG": (22.3080, 113.9185),
    "SZX": (22.6394, 113.8142),
    "CAN": (23.3924, 113.2988),
    "FRA": (50.0379, 8.5622),
    "MUC": (48.3537, 11.7860),
    "NUE": (49.4987, 11.0667),
}

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_OSRM_URL = "https://router.project-osrm.org/route/v1/driving"

# Nominatim requires a User-Agent and politely asks for ≤1 req/s
_HEADERS = {"User-Agent": "FlightOptimizer/1.0 (personal research tool)"}
_last_nominatim_call: float = 0.0


def geocode(address: str) -> tuple[float, float, str] | None:
    """
    Convert a free-text address to (lat, lon, display_name).
    Returns None if geocoding fails.
    """
    global _last_nominatim_call
    params = urllib.parse.urlencode({"q": address, "format": "json", "limit": "1"})
    url = f"{_NOMINATIM_URL}?{params}"

    # Rate-limit to 1 req/sec as required by Nominatim ToS
    elapsed = time.time() - _last_nominatim_call
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            _last_nominatim_call = time.time()
            data = json.loads(resp.read())
        if not data:
            logger.warning(f"Nominatim: no results for '{address}'")
            return None
        r = data[0]
        return float(r["lat"]), float(r["lon"]), r.get("display_name", address)
    except Exception as e:
        logger.warning(f"Nominatim geocoding error for '{address}': {e}")
        return None


def driving_route(lat1: float, lon1: float, lat2: float, lon2: float) -> dict | None:
    """
    Return {"duration_minutes": float, "distance_km": float} for the
    fastest driving route between two points, or None on failure.
    """
    url = f"{_OSRM_URL}/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("code") != "Ok" or not data.get("routes"):
            logger.warning(f"OSRM: no route ({lat1},{lon1}) → ({lat2},{lon2})")
            return None
        route = data["routes"][0]
        return {
            "duration_minutes": round(route["duration"] / 60, 1),
            "distance_km": round(route["distance"] / 1000, 1),
        }
    except Exception as e:
        logger.warning(f"OSRM routing error: {e}")
        return None


def calculate_ground_transport(
    home_address: str,
    dest_address: str,
    cost_per_km: float = 1.5,
) -> dict:
    """
    Geocode both addresses and compute driving legs for every airport.

    Returns a dict:
    {
      "home_display": str,
      "dest_display": str,
      "home_coords": (lat, lon) | None,
      "dest_coords": (lat, lon) | None,
      "legs": {
          "HKG": {"duration_minutes": X, "distance_km": Y, "cost": Z},
          "SZX": ...,
          "CAN": ...,
          "FRA": ...,
          "MUC": ...,
          "NUE": ...,
      }
    }
    """
    result = {
        "home_display": home_address,
        "dest_display": dest_address,
        "home_coords": None,
        "dest_coords": None,
        "legs": {},
    }

    home_geo = geocode(home_address)
    dest_geo = geocode(dest_address)

    if home_geo:
        result["home_coords"] = (home_geo[0], home_geo[1])
        result["home_display"] = home_geo[2]
    else:
        logger.warning("Could not geocode home address")

    if dest_geo:
        result["dest_coords"] = (dest_geo[0], dest_geo[1])
        result["dest_display"] = dest_geo[2]
    else:
        logger.warning("Could not geocode destination address")

    # Departure airports — home → airport
    if result["home_coords"]:
        hlat, hlon = result["home_coords"]
        for code in ("HKG", "SZX", "CAN"):
            alat, alon = AIRPORT_COORDS[code]
            route = driving_route(hlat, hlon, alat, alon)
            if route:
                route["cost"] = round(route["distance_km"] * cost_per_km, 2)
            result["legs"][code] = route  # None if unavailable

    # Arrival airports — airport → destination
    if result["dest_coords"]:
        dlat, dlon = result["dest_coords"]
        for code in ("FRA", "MUC", "NUE"):
            alat, alon = AIRPORT_COORDS[code]
            route = driving_route(alat, alon, dlat, dlon)
            if route:
                route["cost"] = round(route["distance_km"] * cost_per_km, 2)
            result["legs"][code] = route  # None if unavailable

    return result
