"""
Ground transport calculator.

Uses:
- Nominatim (OpenStreetMap) for address geocoding — free, no API key.
- OpenAI (via Replit AI proxy) to estimate realistic time + cost per transport mode.
- OSRM (fallback) for raw driving distance when AI is unavailable.
- Disk cache: estimates are stored in ground_transport_cache.json and reused
  across sessions for the same home/dest address + airport combination.
"""

import json
import logging
import math
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

AIRPORT_COORDS = {
    "HKG": (22.3080, 113.9185),
    "SZX": (22.6394, 113.8142),
    "CAN": (23.3924, 113.2988),
    "FRA": (50.0379, 8.5622),
    "MUC": (48.3537, 11.7860),
    "NUE": (49.4987, 11.0667),
}

AIRPORT_NAMES = {
    "HKG": "Hong Kong International Airport",
    "SZX": "Shenzhen Bao'an International Airport",
    "CAN": "Guangzhou Baiyun International Airport",
    "FRA": "Frankfurt Airport (Flughafen Frankfurt/Main)",
    "MUC": "Munich Airport (Flughafen München)",
    "NUE": "Nuremberg Airport (Flughafen Nürnberg)",
}

_ORIGIN_HINTS = {
    "HKG": "Traveller takes Didi from home to Shenzhen Bay Port / Futian Checkpoint, crosses border, then bus or Airport Express to HKG.",
    "SZX": "Traveller uses the Shenzhen Metro Airport Express Line.",
    "CAN": "Traveller uses Didi from home.",
}
_DEST_HINTS = {
    "FRA": "Traveller uses Deutsche Bahn ICE/RE or regional trains from Frankfurt Airport.",
    "MUC": "Traveller uses S-Bahn (S1/S8), regional bus, or Deutsche Bahn from Munich Airport.",
    "NUE": "Traveller uses public transport (U2 metro + regional train) or Deutsche Bahn from Nuremberg Airport.",
}

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_OSRM_URL      = "https://router.project-osrm.org/route/v1/driving"
_HEADERS       = {"User-Agent": "FlightOptimizer/1.0 (personal research tool)"}
_last_nominatim_call: float = 0.0


# ── On-disk cache ──────────────────────────────────────────────────────────────

_GT_CACHE_FILE = Path(__file__).parent / "ground_transport_cache.json"
_GT_CACHE: dict = {}


def _load_gt_cache():
    global _GT_CACHE
    if _GT_CACHE_FILE.exists():
        try:
            with open(_GT_CACHE_FILE, "r", encoding="utf-8") as f:
                _GT_CACHE = json.load(f)
            logger.info(f"Ground transport cache loaded: {len(_GT_CACHE)} entr(ies)")
        except Exception as e:
            logger.warning(f"Ground transport cache load error: {e}")
            _GT_CACHE = {}


def _save_gt_cache():
    try:
        with open(_GT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_GT_CACHE, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Ground transport cache save error: {e}")


def _gt_cache_key(
    home_address: str, dest_address: str,
    origin_airports: list, dest_airports: list,
) -> str:
    all_codes = sorted(set(origin_airports) | set(dest_airports))
    return f"{home_address.lower().strip()}|{dest_address.lower().strip()}|{','.join(all_codes)}"


_load_gt_cache()


# ── Geocoding ──────────────────────────────────────────────────────────────────

def geocode(address: str) -> tuple[float, float, str] | None:
    """Return (lat, lon, display_name) or None on failure."""
    global _last_nominatim_call
    params = urllib.parse.urlencode({"q": address, "format": "json", "limit": "1"})
    url = f"{_NOMINATIM_URL}?{params}"
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


# ── OSRM fallback ──────────────────────────────────────────────────────────────

def _osrm_driving(lat1: float, lon1: float, lat2: float, lon2: float) -> dict | None:
    url = f"{_OSRM_URL}/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("code") != "Ok" or not data.get("routes"):
            return None
        route = data["routes"][0]
        return {
            "duration_minutes": round(route["duration"] / 60, 1),
            "distance_km":      round(route["distance"] / 1000, 1),
        }
    except Exception as e:
        logger.warning(f"OSRM error: {e}")
        return None


# ── Haversine distance ─────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two (lat, lon) points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── AI estimation ──────────────────────────────────────────────────────────────

def _call_openai(prompt: str, system: str, max_tokens: int = 1400) -> str | None:
    """Call OpenAI via Replit AI proxy and return the raw text response."""
    base_url = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL", "").rstrip("/")
    api_key  = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY", "dummy")
    if not base_url:
        logger.warning("AI_INTEGRATIONS_OPENAI_BASE_URL not set; skipping AI estimate")
        return None

    payload = json.dumps({
        "model": "gpt-4o-mini",
        "max_completion_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"OpenAI call failed: {e}")
        return None


def _ai_transport_estimate(
    home_address: str,
    dest_address: str,
    home_coords: tuple | None,
    dest_coords: tuple | None,
    origin_airports: list[str],
    dest_airports: list[str],
) -> dict | None:
    """
    Ask the AI to estimate realistic travel time and cost for each airport leg.
    Returns {code: {...}} for all requested airports, or None if AI is unavailable.
    """
    system = (
        "You are a travel logistics expert who knows public transport, Didi, Deutsche Bahn, "
        "metro systems, and airport ground transport worldwide. "
        "You respond ONLY with a valid JSON object, no markdown fences, no extra text."
    )

    coord_hint_home = (
        f" (approx coords {home_coords[0]:.4f},{home_coords[1]:.4f})"
        if home_coords else ""
    )
    coord_hint_dest = (
        f" (approx coords {dest_coords[0]:.4f},{dest_coords[1]:.4f})"
        if dest_coords else ""
    )

    dep_lines = []
    for code in origin_airports:
        name = AIRPORT_NAMES.get(code, f"{code} Airport")
        hint = _ORIGIN_HINTS.get(
            code,
            "Use your knowledge of local transport options (public transit, taxi, ride-sharing).",
        )
        dist_str = ""
        if home_coords and code in AIRPORT_COORDS:
            ac = AIRPORT_COORDS[code]
            dist_km = _haversine_km(home_coords[0], home_coords[1], ac[0], ac[1])
            # Floor: straight-line distance at 100 km/h effective speed (conservative but not overcorrected)
            min_minutes = int(dist_km / 100 * 60)
            dist_str = (
                f" Straight-line distance: {dist_km:.0f} km. "
                f"MINIMUM realistic travel time: {min_minutes} min — do NOT go below this."
            )
        dep_lines.append(f"- {code}: {name}. {hint}{dist_str}")

    arr_lines = []
    for code in dest_airports:
        name = AIRPORT_NAMES.get(code, f"{code} Airport")
        hint = _DEST_HINTS.get(
            code,
            "Use your knowledge of local transport options (public transit, taxi, ride-sharing).",
        )
        dist_str = ""
        if dest_coords and code in AIRPORT_COORDS:
            ac = AIRPORT_COORDS[code]
            dist_km = _haversine_km(dest_coords[0], dest_coords[1], ac[0], ac[1])
            min_minutes = int(dist_km / 100 * 60)
            dist_str = (
                f" Straight-line distance: {dist_km:.0f} km. "
                f"MINIMUM realistic travel time: {min_minutes} min — do NOT go below this."
            )
        arr_lines.append(f"- {code}: {name}. {hint}{dist_str}")

    all_codes = origin_airports + dest_airports
    json_template = "{\n" + ",\n".join(
        f'  "{code}": {{"time_minutes": ..., "cost_eur": ..., "mode": "...", "notes": "..."}}'
        for code in all_codes
    ) + "\n}"

    prompt = f"""Estimate REALISTIC door-to-airport (or airport-to-door) travel times for the following routes.

IMPORTANT RULES:
- Use the actual distances provided below — do NOT underestimate travel time.
- Account for urban traffic, connections, waiting times, and typical delays.
- For Didi/taxi in Chinese cities: average effective speed including traffic is 40–60 km/h.
- For trains (DB ICE/RE in Germany): include time to reach the station + waiting time.
- Do NOT estimate times that would require averaging more than 80 km/h door-to-door.
- Each stated MINIMUM is a hard floor — your estimate must be >= that value.

HOME ADDRESS: {home_address}{coord_hint_home}
DESTINATION ADDRESS: {dest_address}{coord_hint_dest}

DEPARTURE AIRPORTS (home address → airport, one-way travel):
{chr(10).join(dep_lines)}

ARRIVAL AIRPORTS (airport → destination address, one-way travel):
{chr(10).join(arr_lines)}

For EACH airport code, return an object with:
  - "time_minutes": one-way travel time estimate in minutes (integer, must respect the stated minimum)
  - "cost_eur": one-way cost estimate in EUR (number, use current rough fares)
  - "mode": short description of transport used (e.g. "Didi + border bus + Airport Express")
  - "notes": one sentence of explanation including key distance/time breakdown

Return EXACTLY this JSON structure (no markdown, no extra text):
{json_template}""".strip()

    raw = _call_openai(prompt, system, max_tokens=1400)
    if not raw:
        return None

    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

    try:
        data = json.loads(text)
        expected = set(all_codes)
        if not expected.issubset(data.keys()):
            logger.warning(f"AI response missing some airport keys: {data.keys()}")
            return None
        # Enforce distance-based minimums regardless of what the AI returned
        for code in expected:
            entry = data[code]
            entry["time_minutes"] = float(entry.get("time_minutes") or 0)
            entry["cost_eur"]     = float(entry.get("cost_eur") or 0)
            # Compute distance-based floor for this leg
            if code in origin_airports and home_coords and code in AIRPORT_COORDS:
                ac = AIRPORT_COORDS[code]
                dist_km  = _haversine_km(home_coords[0], home_coords[1], ac[0], ac[1])
                min_mins = dist_km / 100 * 60
                if entry["time_minutes"] < min_mins:
                    logger.warning(
                        f"AI gave {entry['time_minutes']:.0f} min for {code} origin leg "
                        f"(floor={min_mins:.0f} min, dist={dist_km:.0f} km) — clamping up."
                    )
                    entry["time_minutes"] = round(min_mins)
            elif code in dest_airports and dest_coords and code in AIRPORT_COORDS:
                ac = AIRPORT_COORDS[code]
                dist_km  = _haversine_km(dest_coords[0], dest_coords[1], ac[0], ac[1])
                min_mins = dist_km / 100 * 60
                if entry["time_minutes"] < min_mins:
                    logger.warning(
                        f"AI gave {entry['time_minutes']:.0f} min for {code} dest leg "
                        f"(floor={min_mins:.0f} min, dist={dist_km:.0f} km) — clamping up."
                    )
                    entry["time_minutes"] = round(min_mins)
        return data
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"AI response parse error: {e}\nRaw: {raw[:300]}")
        return None


# ── OSRM fallback leg builder ─────────────────────────────────────────────────

def _fallback_legs(home_coords, dest_coords, origin_airports, dest_airports) -> dict:
    """Build legs using OSRM driving estimates when AI is unavailable."""
    legs = {}
    DRIVING_EUR_PER_KM = 1.5

    if home_coords:
        hlat, hlon = home_coords
        for code in origin_airports:
            if code not in AIRPORT_COORDS:
                legs[code] = None
                continue
            alat, alon = AIRPORT_COORDS[code]
            r = _osrm_driving(hlat, hlon, alat, alon)
            if r:
                legs[code] = {
                    "time_minutes": r["duration_minutes"],
                    "cost_eur":     round(r["distance_km"] * DRIVING_EUR_PER_KM, 2),
                    "distance_km":  r["distance_km"],
                    "mode":         "Driving (estimate)",
                    "notes":        "OSRM driving fallback — AI unavailable",
                }
            else:
                legs[code] = None

    if dest_coords:
        dlat, dlon = dest_coords
        for code in dest_airports:
            if code not in AIRPORT_COORDS:
                legs[code] = None
                continue
            alat, alon = AIRPORT_COORDS[code]
            r = _osrm_driving(alat, alon, dlat, dlon)
            if r:
                legs[code] = {
                    "time_minutes": r["duration_minutes"],
                    "cost_eur":     round(r["distance_km"] * DRIVING_EUR_PER_KM, 2),
                    "distance_km":  r["distance_km"],
                    "mode":         "Driving (estimate)",
                    "notes":        "OSRM driving fallback — AI unavailable",
                }
            else:
                legs[code] = None

    return legs


# ── Public API ─────────────────────────────────────────────────────────────────

def calculate_ground_transport(
    home_address: str,
    dest_address: str,
    origin_airports: list[str] | None = None,
    dest_airports: list[str] | None = None,
    cost_per_km: float = 1.5,
) -> dict:
    """
    Geocode both addresses, then estimate ground transport for all requested airports.
    Results are cached to disk; the same home+dest+airports combination is never
    re-queried (AI or OSRM) as long as the cache file exists.

    Returns:
    {
      "home_display": str,
      "dest_display": str,
      "home_coords":  (lat, lon) | None,
      "dest_coords":  (lat, lon) | None,
      "ai_powered":   bool,
      "legs": {
          code: {"time_minutes": X, "cost_eur": Y, "cost": Y, "mode": "...", "notes": "..."},
          ...
      }
    }
    """
    if origin_airports is None:
        origin_airports = ["HKG", "SZX", "CAN"]
    if dest_airports is None:
        dest_airports = ["FRA", "MUC", "NUE"]

    result = {
        "home_display": home_address,
        "dest_display": dest_address,
        "home_coords":  None,
        "dest_coords":  None,
        "ai_powered":   False,
        "legs":         {},
    }

    cache_key = _gt_cache_key(home_address, dest_address, origin_airports, dest_airports)
    if cache_key in _GT_CACHE:
        logger.info(f"Ground transport cache HIT ({cache_key[:60]}…)")
        cached = _GT_CACHE[cache_key]
        result.update(cached)
        if result["home_coords"] and isinstance(result["home_coords"], list):
            result["home_coords"] = tuple(result["home_coords"])
        if result["dest_coords"] and isinstance(result["dest_coords"], list):
            result["dest_coords"] = tuple(result["dest_coords"])
        for leg in result["legs"].values():
            if leg:
                leg.setdefault("cost", leg.get("cost_eur", 0))
                leg.setdefault("duration_minutes", leg.get("time_minutes", 0))
        return result

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

    ai_legs = _ai_transport_estimate(
        home_address, dest_address,
        result["home_coords"], result["dest_coords"],
        origin_airports, dest_airports,
    )

    if ai_legs:
        result["ai_powered"] = True
        for code, leg in ai_legs.items():
            leg["cost"]             = leg["cost_eur"]
            leg["duration_minutes"] = leg["time_minutes"]
        result["legs"] = ai_legs
    else:
        logger.warning("AI estimate failed; falling back to OSRM driving estimates")
        legs = _fallback_legs(
            result["home_coords"], result["dest_coords"],
            origin_airports, dest_airports,
        )
        for code, leg in legs.items():
            if leg:
                leg["cost"]             = leg["cost_eur"]
                leg["duration_minutes"] = leg["time_minutes"]
        result["legs"] = legs

    cacheable = {
        "home_display": result["home_display"],
        "dest_display": result["dest_display"],
        "home_coords":  list(result["home_coords"]) if result["home_coords"] else None,
        "dest_coords":  list(result["dest_coords"]) if result["dest_coords"] else None,
        "ai_powered":   result["ai_powered"],
        "legs":         result["legs"],
    }
    _GT_CACHE[cache_key] = cacheable
    _save_gt_cache()
    logger.info(f"Ground transport result cached (total: {len(_GT_CACHE)} entries)")

    return result
