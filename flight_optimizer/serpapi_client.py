"""
Flight Optimizer - SerpApi Google Flights Client
"""

import os
import sys
import time
import logging
from datetime import date
from typing import Optional
import requests

logger = logging.getLogger(__name__)

SERPAPI_BASE_URL = "https://serpapi.com/search"

# German airport IATA codes used to detect domestic DE segments
GERMAN_AIRPORTS: frozenset = frozenset({
    "FRA", "MUC", "NUE", "DUS", "HAM", "BER", "TXL", "STR", "CGN",
    "HAJ", "LEJ", "DRS", "HHN", "FKB", "PAD", "ERF", "FDH", "SCN",
    "DTM", "KSF", "GWT", "FMO", "NRN", "LBC", "RLG", "QFB", "ZQW",
    "SXF", "THF",  # older Berlin codes
})


def _validate_dates(outbound_date: str, return_date: str):
    """Validates that dates are in the future and return is after outbound."""
    today = date.today()
    out = date.fromisoformat(outbound_date)
    ret = date.fromisoformat(return_date)

    if out <= today:
        raise ValueError(
            f"Outbound date {outbound_date} is in the past (today: {today}). "
            "Please set a future date in config.py."
        )
    if ret <= out:
        raise ValueError(
            f"Return date {return_date} must be after outbound date {outbound_date}."
        )


def fetch_flights(
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str,
    currency: str = "EUR",
    hl: str = "en",
    gl: str = "us",
    max_stops: Optional[int] = None,
    airline_filter: Optional[list] = None,
) -> list[dict]:
    """
    Fetches roundtrip flight data from SerpApi (Google Flights).

    Returns a list of flight dictionaries:
      - origin, destination, outbound_date, return_date
      - price (float, EUR)
      - duration_minutes (int)
      - airline (str)
      - stops (int)
      - flight_details (dict, raw)
    """
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        raise EnvironmentError(
            "SERPAPI_KEY is not set. Please add it as an environment variable / secret."
        )

    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "currency": currency,  # Prices returned directly in this currency (e.g. EUR)
        "hl": hl,
        "gl": gl,
        "type": "1",        # 1 = Round trip
        "travel_class": "1",  # 1 = Economy (cheapest class)
        "api_key": api_key,
    }

    # Optional native stop filter (SerpApi: 0=non-stop only, 1=max 1 stop, 2=max 2 stops)
    if max_stops is not None and max_stops in (0, 1, 2):
        params["stops"] = str(max_stops)

    logger.info(f"Fetching: {origin} -> {destination} | {outbound_date} <-> {return_date}")

    max_retries = 3
    retry_delay = 5  # seconds between retries
    data = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(SERPAPI_BASE_URL, params=params, timeout=60)
            data = response.json()
            break  # Success — exit retry loop
        except requests.Timeout:
            if attempt < max_retries:
                logger.warning(
                    f"Timeout for {origin}->{destination} (attempt {attempt}/{max_retries}), "
                    f"retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
            else:
                logger.warning(
                    f"Timeout for {origin}->{destination} after {max_retries} attempts — skipping."
                )
                return []
        except requests.RequestException as e:
            logger.warning(f"Network error for {origin}->{destination}: {e} — skipping.")
            return []
        except ValueError as e:
            logger.error(f"Invalid JSON response: {e}")
            return []

    if data is None:
        return []

    # Check for API-level errors (also covers HTTP 4xx/5xx)
    if "error" in data:
        err_msg = data["error"]

        # No results = expected for some route/date combinations, not a real error
        if "hasn't returned any results" in err_msg or "no results" in err_msg.lower():
            logger.warning(
                f"No results for {origin}->{destination} | {outbound_date}<->{return_date} (skipped)"
            )
            return []

        # Real errors — log and optionally exit
        logger.error(f"SerpApi error: {err_msg}")

        if "past" in err_msg.lower():
            logger.error(
                "  -> Date is in the past! "
                "Please set OUTBOUND_DATE and RETURN_DATE to future dates in config.py."
            )
            sys.exit(1)
        if "api_key" in err_msg.lower() or "invalid" in err_msg.lower():
            logger.error("  -> Invalid or expired SERPAPI_KEY.")
            sys.exit(1)
        return []

    results = []

    # Parse both "best_flights" and "other_flights"
    for section in ("best_flights", "other_flights"):
        for itinerary in data.get(section, []):
            try:
                price = itinerary.get("price")
                if price is None:
                    continue

                flights_legs = itinerary.get("flights", [])
                raw_layovers = itinerary.get("layovers", [])

                # ── Outbound duration ──────────────────────────────────────
                total_duration = itinerary.get("total_duration")
                if total_duration is None:
                    total_duration = sum(leg.get("duration", 0) for leg in flights_legs)

                # ── Airline (first carrier) ────────────────────────────────
                airline = (
                    flights_legs[0].get("airline", "Unknown")
                    if flights_legs else "Unknown"
                )

                # ── Outbound stops ─────────────────────────────────────────
                stops = len(raw_layovers)

                # ── Outbound segment details ───────────────────────────────
                outbound_segments = []
                for leg in flights_legs:
                    dep = leg.get("departure_airport", {})
                    arr = leg.get("arrival_airport", {})
                    leg_extensions = leg.get("extensions") or []
                    # Fare brand is usually the first extension that looks like a cabin/fare label
                    # Guard: extensions may contain non-string items (SerpApi quirk)
                    fare_brand = next(
                        (e for e in leg_extensions
                         if isinstance(e, str) and any(kw in e.lower() for kw in
                                ("economy", "business", "first", "premium", "light",
                                 "flex", "basic", "saver", "plus", "classic"))),
                        None,
                    )
                    outbound_segments.append({
                        "from_airport": dep.get("id", "?"),
                        "from_name": dep.get("name", ""),
                        "from_time": dep.get("time", ""),
                        "to_airport": arr.get("id", "?"),
                        "to_name": arr.get("name", ""),
                        "to_time": arr.get("time", ""),
                        "airline": leg.get("airline", "Unknown"),
                        "flight_number": leg.get("flight_number", ""),
                        "aircraft": leg.get("airplane", ""),
                        "duration_minutes": leg.get("duration", 0),
                        "overnight": leg.get("overnight", False),
                        "booking_class": leg.get("travel_class", "Economy"),
                        "fare_brand": fare_brand,
                    })

                # ── Outbound layover details ───────────────────────────────
                outbound_layovers = []
                for lay in raw_layovers:
                    outbound_layovers.append({
                        "airport": lay.get("name", "?"),
                        "airport_id": lay.get("id", "?"),
                        "duration_minutes": lay.get("duration", 0),
                    })

                # ── Outbound route string (e.g. "HKG->DOH->FRA") ──────────
                if outbound_segments:
                    route_airports = [outbound_segments[0]["from_airport"]]
                    for seg in outbound_segments:
                        route_airports.append(seg["to_airport"])
                    outbound_route = "->".join(route_airports)
                else:
                    outbound_route = f"{origin}->{destination}"

                # ── Optional filters ───────────────────────────────────────
                if airline_filter and not any(
                    af.lower() in airline.lower() for af in airline_filter
                ):
                    continue
                if max_stops is not None and stops > max_stops:
                    continue

                # Booking class from the first outbound leg
                booking_class = (
                    outbound_segments[0].get("booking_class", "Economy")
                    if outbound_segments else "Economy"
                )
                fare_brand = (
                    outbound_segments[0].get("fare_brand")
                    if outbound_segments else None
                )

                results.append({
                    "origin": origin,
                    "destination": destination,
                    "outbound_date": outbound_date,
                    "return_date": return_date,
                    "price": float(price),
                    "currency": currency,
                    # Outbound leg summary (used by scorer)
                    "duration_minutes": int(total_duration),
                    "stops": stops,
                    "airline": airline,
                    # Booking / fare class
                    "booking_class": booking_class,
                    "fare_brand": fare_brand,
                    # Detailed outbound leg breakdown
                    "outbound_route": outbound_route,
                    "outbound_segments": outbound_segments,
                    "outbound_layovers": outbound_layovers,
                    # Token needed to fetch return leg details (step 2)
                    "departure_token": itinerary.get("departure_token", ""),
                    "flight_details": itinerary,
                })
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"Itinerary skipped (parse error): {e}")
                continue

    logger.info(f"  -> {len(results)} result(s) found")
    return results


def fetch_all_combinations(
    origins: list[str],
    destinations: list[str],
    outbound_dates: list[str],
    return_dates: list[str],
    currency: str = "EUR",
    hl: str = "en",
    gl: str = "us",
    max_stops: Optional[int] = None,
    airline_filter: Optional[list] = None,
    delay_seconds: float = 1.0,
    cache: Optional[dict] = None,
    cache_file: Optional[str] = None,
) -> list[dict]:
    """
    Fetches all origin/destination combinations x date pairs.
    delay_seconds prevents rate limiting.
    cache: optional cache dictionary (from cache.py)
    """
    from flight_optimizer.cache import get_cached, set_cached, save_cache

    # Validate all dates before making any API calls
    for out_date in outbound_dates:
        for ret_date in return_dates:
            _validate_dates(out_date, ret_date)

    all_results = []
    total = len(origins) * len(destinations) * len(outbound_dates) * len(return_dates)
    count = 0
    api_calls = 0
    cache_hits = 0

    for origin in origins:
        for destination in destinations:
            for out_date in outbound_dates:
                for ret_date in return_dates:
                    count += 1
                    logger.info(
                        f"[{count}/{total}] {origin}->{destination} | {out_date}<->{ret_date}"
                    )

                    # Check cache first
                    if cache is not None:
                        cached = get_cached(cache, origin, destination, out_date, ret_date)
                        if cached is not None:
                            all_results.extend(cached)
                            cache_hits += 1
                            continue

                    # Make API request
                    flights = fetch_flights(
                        origin=origin,
                        destination=destination,
                        outbound_date=out_date,
                        return_date=ret_date,
                        currency=currency,
                        hl=hl,
                        gl=gl,
                        max_stops=max_stops,
                        airline_filter=airline_filter,
                    )
                    api_calls += 1
                    all_results.extend(flights)

                    # Store result in cache
                    if cache is not None:
                        set_cached(cache, origin, destination, out_date, ret_date, flights)
                        if cache_file:
                            save_cache(cache, cache_file)

                    if count < total:
                        time.sleep(delay_seconds)

    logger.info(
        f"Done: {api_calls} API request(s), {cache_hits} loaded from cache "
        f"(saved: {cache_hits} of {total} searches)"
    )
    return all_results


# ─── Return leg helpers ────────────────────────────────────────────────────────

def _parse_segments(flights_legs: list, raw_layovers: list, origin: str, dest: str) -> tuple:
    """
    Shared helper: parses a list of flight leg dicts and layover dicts into
    structured segments, layovers, route string, and total duration.
    """
    segments = []
    for leg in flights_legs:
        dep = leg.get("departure_airport", {})
        arr = leg.get("arrival_airport", {})
        leg_extensions = leg.get("extensions") or []
        # Guard: extensions may contain non-string items (SerpApi quirk)
        fare_brand = next(
            (e for e in leg_extensions
             if isinstance(e, str) and any(kw in e.lower() for kw in
                    ("economy", "business", "first", "premium", "light",
                     "flex", "basic", "saver", "plus", "classic"))),
            None,
        )
        segments.append({
            "from_airport": dep.get("id", "?"),
            "from_name": dep.get("name", ""),
            "from_time": dep.get("time", ""),
            "to_airport": arr.get("id", "?"),
            "to_name": arr.get("name", ""),
            "to_time": arr.get("time", ""),
            "airline": leg.get("airline", "Unknown"),
            "flight_number": leg.get("flight_number", ""),
            "aircraft": leg.get("airplane", ""),
            "duration_minutes": leg.get("duration", 0),
            "overnight": leg.get("overnight", False),
            "booking_class": leg.get("travel_class", "Economy"),
            "fare_brand": fare_brand,
        })

    layovers = []
    for lay in raw_layovers:
        layovers.append({
            "airport": lay.get("name", "?"),
            "airport_id": lay.get("id", "?"),
            "duration_minutes": lay.get("duration", 0),
            "overnight": lay.get("overnight", False),
        })

    if segments:
        route_airports = [segments[0]["from_airport"]]
        for seg in segments:
            route_airports.append(seg["to_airport"])
        route = "->".join(route_airports)
    else:
        route = f"{origin}->{dest}"

    total_dur = sum(s["duration_minutes"] for s in segments) + sum(l["duration_minutes"] for l in layovers)

    return segments, layovers, route, total_dur


def fetch_return_legs(
    departure_token: str,
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str,
    currency: str = "EUR",
    hl: str = "en",
    gl: str = "us",
) -> Optional[dict]:
    """
    Makes the second SerpApi call (using departure_token) to retrieve the return
    flight leg details for a previously selected outbound itinerary.

    Returns a dict with return_segments, return_layovers, return_route,
    return_duration_minutes, return_stops — or None on failure.
    """
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        raise EnvironmentError("SERPAPI_KEY is not set.")

    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "currency": currency,
        "hl": hl,
        "gl": gl,
        "type": "1",
        "departure_token": departure_token,
        "api_key": api_key,
    }

    for attempt in range(1, 4):
        try:
            resp = requests.get(SERPAPI_BASE_URL, params=params, timeout=60)
            data = resp.json()
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"Return leg fetch timeout (attempt {attempt}/3): {e}")
            if attempt == 3:
                return None
            time.sleep(5)
        except Exception as e:
            logger.warning(f"Return leg fetch error: {e}")
            return None

    if data.get("error"):
        logger.warning(f"Return leg API error: {data['error']}")
        return None

    # Log top-level keys so we can diagnose what SerpApi returns for step-2 calls
    top_keys = [k for k in data.keys() if k not in ("search_metadata", "search_parameters", "search_information")]
    logger.info(f"Return leg response keys: {top_keys}")

    # SerpApi may return return-leg options in best_flights OR other_flights
    best = data.get("best_flights") or data.get("other_flights") or []
    if not best:
        logger.warning(f"Return leg: no flights in response. Keys present: {top_keys}")
        return None

    itinerary = best[0]
    flights_legs = itinerary.get("flights", [])
    raw_layovers = itinerary.get("layovers", [])

    try:
        segments, layovers, route, total_dur = _parse_segments(
            flights_legs, raw_layovers, destination, origin
        )
    except Exception as e:
        logger.warning(f"Return leg parse error: {e}")
        return None

    return {
        "return_segments": segments,
        "return_layovers": layovers,
        "return_route": route,
        "return_duration_minutes": itinerary.get("total_duration", total_dur),
        "return_stops": len(raw_layovers),
    }


def enrich_with_return_legs(
    flights: list[dict],
    top_n: int,
    cache: Optional[dict],
    cache_file: Optional[str],
    currency: str = "EUR",
    hl: str = "en",
    gl: str = "us",
    delay_seconds: float = 1.5,
) -> list[dict]:
    """
    For each flight in the top-N (already sorted by score), fetches the
    return leg details using departure_token. Results are cached by token.
    Modifies each flight dict in-place and returns the updated list.
    """
    from flight_optimizer.cache import get_cached_return, set_cached_return, save_cache

    api_calls = 0
    cache_hits = 0

    for idx, flight in enumerate(flights[:top_n]):
        token = flight.get("departure_token", "")
        if not token:
            logger.warning(f"  Flight #{idx+1}: no departure_token, skipping return fetch.")
            continue

        # Already enriched (e.g. from a previous run's cache)
        if flight.get("return_segments"):
            continue

        # Check return-leg cache
        if cache is not None:
            cached_return = get_cached_return(cache, token)
            if cached_return is not None:
                flight.update(cached_return)
                cache_hits += 1
                continue

        logger.info(
            f"  Fetching return leg for flight #{idx+1}: "
            f"{flight.get('outbound_route', '?')} | {flight['return_date']}"
        )
        result = fetch_return_legs(
            departure_token=token,
            origin=flight["origin"],
            destination=flight["destination"],
            outbound_date=flight["outbound_date"],
            return_date=flight["return_date"],
            currency=currency,
            hl=hl,
            gl=gl,
        )
        api_calls += 1

        if result:
            flight.update(result)
            if cache is not None:
                set_cached_return(cache, token, result)
                if cache_file:
                    save_cache(cache, cache_file)

        if idx + 1 < top_n:
            time.sleep(delay_seconds)

    logger.info(
        f"Return leg enrichment: {api_calls} API call(s), {cache_hits} from cache"
    )
    return flights
