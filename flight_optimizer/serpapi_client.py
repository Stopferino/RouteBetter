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
        "currency": currency,
        "hl": hl,
        "gl": gl,
        "type": "1",  # 1 = Round trip
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

                # Total roundtrip duration
                total_duration = itinerary.get("total_duration")
                if total_duration is None:
                    # Fallback: sum all individual legs
                    total_duration = sum(
                        leg.get("duration", 0) for leg in itinerary.get("flights", [])
                    )

                # Airline (first carrier in the itinerary)
                flights_legs = itinerary.get("flights", [])
                airline = (
                    flights_legs[0].get("airline", "Unknown")
                    if flights_legs
                    else "Unknown"
                )

                # Number of stops (layovers)
                stops = len(itinerary.get("layovers", []))

                # Optional airline filter (substring match)
                if airline_filter and not any(
                    af.lower() in airline.lower() for af in airline_filter
                ):
                    continue

                # Optional stop filter (Python-side fine-filter)
                if max_stops is not None and stops > max_stops:
                    continue

                results.append({
                    "origin": origin,
                    "destination": destination,
                    "outbound_date": outbound_date,
                    "return_date": return_date,
                    "price": float(price),
                    "duration_minutes": int(total_duration),
                    "airline": airline,
                    "stops": stops,
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
