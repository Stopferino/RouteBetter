"""
Ground transport calculator.

Uses:
- Nominatim (OpenStreetMap) for address geocoding — free, no API key.
- OpenAI (via Replit AI proxy) to estimate realistic time + cost per transport mode.
- OSRM (fallback) for raw driving distance when AI is unavailable.

The AI is aware of realistic transport modes:
  Departure side (HKG/SZX/CAN): metro, Didi, bus, specific cross-border routes.
  Arrival side (FRA/MUC/NUE): Deutsche Bahn, regional bus, S-Bahn.
"""

import json
import logging
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

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_OSRM_URL      = "https://router.project-osrm.org/route/v1/driving"
_HEADERS       = {"User-Agent": "FlightOptimizer/1.0 (personal research tool)"}
_last_nominatim_call: float = 0.0


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


# ── AI estimation ──────────────────────────────────────────────────────────────

def _call_openai(prompt: str, system: str, max_tokens: int = 1200) -> str | None:
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
) -> dict | None:
    """
    Ask the AI to estimate realistic travel time and cost for each airport leg.
    Returns {"HKG": {...}, "SZX": {...}, ...} or None if AI is unavailable.
    """
    system = (
        "You are a travel logistics expert who knows public transport, Didi, Deutsche Bahn, "
        "metro systems, and airport ground transport in China and Germany very well. "
        "You respond ONLY with a valid JSON object, no markdown fences, no extra text."
    )

    coord_hint_home = f" (approx coords {home_coords[0]:.4f},{home_coords[1]:.4f})" if home_coords else ""
    coord_hint_dest = f" (approx coords {dest_coords[0]:.4f},{dest_coords[1]:.4f})" if dest_coords else ""

    prompt = f"""
Estimate realistic door-to-airport (or airport-to-door) travel for the following routes.

HOME ADDRESS: {home_address}{coord_hint_home}
DESTINATION ADDRESS IN GERMANY: {dest_address}{coord_hint_dest}

DEPARTURE AIRPORTS (home → airport):
- HKG: Hong Kong International Airport. The traveller typically takes a Didi from home to Shenzhen Bay Port / Futian Checkpoint, then crosses the border and takes the bus or Airport Express to HKG.
- SZX: Shenzhen Bao'an International Airport. The traveller typically uses the Shenzhen Metro (Airport Express Line).
- CAN: Guangzhou Baiyun International Airport. The traveller typically uses Didi from home.

ARRIVAL AIRPORTS (airport → destination in Germany):
- FRA: Frankfurt Airport → destination address. Traveller uses Deutsche Bahn ICE/RE or regional trains where possible.
- MUC: Munich Airport → destination address. Traveller uses S-Bahn (S1/S8), regional bus, or Deutsche Bahn.
- NUE: Nuremberg Airport → destination address. Traveller uses public transport (U2 metro + regional train) or Deutsche Bahn.

For EACH airport code, return an object with:
  - "time_minutes": one-way travel time estimate (integer)
  - "cost_eur": one-way cost estimate in EUR (number, use current rough fares)
  - "mode": short description of transport used (e.g. "Didi + border bus + Airport Express")
  - "notes": one sentence of explanation

Return EXACTLY this JSON structure (no markdown):
{{
  "HKG": {{"time_minutes": ..., "cost_eur": ..., "mode": "...", "notes": "..."}},
  "SZX": {{"time_minutes": ..., "cost_eur": ..., "mode": "...", "notes": "..."}},
  "CAN": {{"time_minutes": ..., "cost_eur": ..., "mode": "...", "notes": "..."}},
  "FRA": {{"time_minutes": ..., "cost_eur": ..., "mode": "...", "notes": "..."}},
  "MUC": {{"time_minutes": ..., "cost_eur": ..., "mode": "...", "notes": "..."}},
  "NUE": {{"time_minutes": ..., "cost_eur": ..., "mode": "...", "notes": "..."}}
}}
""".strip()

    raw = _call_openai(prompt, system, max_tokens=1200)
    if not raw:
        return None

    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

    try:
        data = json.loads(text)
        # Validate all 6 keys exist
        expected = {"HKG", "SZX", "CAN", "FRA", "MUC", "NUE"}
        if not expected.issubset(data.keys()):
            logger.warning(f"AI response missing some airport keys: {data.keys()}")
            return None
        # Normalise: ensure numeric types
        for code in expected:
            entry = data[code]
            entry["time_minutes"] = float(entry.get("time_minutes") or 0)
            entry["cost_eur"]     = float(entry.get("cost_eur") or 0)
        return data
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"AI response parse error: {e}\nRaw: {raw[:300]}")
        return None


# ── OSRM fallback leg builder ─────────────────────────────────────────────────

def _fallback_legs(home_coords, dest_coords) -> dict:
    """Build legs using OSRM driving estimates when AI is unavailable."""
    legs = {}
    DRIVING_EUR_PER_KM = 1.5

    if home_coords:
        hlat, hlon = home_coords
        for code in ("HKG", "SZX", "CAN"):
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
        for code in ("FRA", "MUC", "NUE"):
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
    cost_per_km: float = 1.5,   # kept for backward compat but not used by AI path
) -> dict:
    """
    Geocode both addresses, then estimate ground transport for all 6 airports.

    Returns:
    {
      "home_display": str,
      "dest_display": str,
      "home_coords":  (lat, lon) | None,
      "dest_coords":  (lat, lon) | None,
      "ai_powered":   bool,
      "legs": {
          "HKG": {"time_minutes": X, "cost_eur": Y, "mode": "...", "notes": "...", "cost": Y},
          ...
      }
    }
    The "cost" key mirrors "cost_eur" so the rest of app.py keeps working unchanged.
    """
    result = {
        "home_display": home_address,
        "dest_display": dest_address,
        "home_coords":  None,
        "dest_coords":  None,
        "ai_powered":   False,
        "legs":         {},
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

    # Try AI estimation first
    ai_legs = _ai_transport_estimate(
        home_address, dest_address,
        result["home_coords"], result["dest_coords"],
    )

    if ai_legs:
        result["ai_powered"] = True
        # Normalise: add "cost" alias (used by app.py scoring) = cost_eur
        for code, leg in ai_legs.items():
            leg["cost"]         = leg["cost_eur"]
            leg["duration_minutes"] = leg["time_minutes"]   # alias for UI
        result["legs"] = ai_legs
    else:
        logger.warning("AI estimate failed; falling back to OSRM driving estimates")
        legs = _fallback_legs(result["home_coords"], result["dest_coords"])
        for code, leg in legs.items():
            if leg:
                leg["cost"] = leg["cost_eur"]
                leg["duration_minutes"] = leg["time_minutes"]
        result["legs"] = legs

    return result
