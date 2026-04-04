"""
Flight Optimizer - SerpApi Google Flights Client
"""

import os
import time
import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)

SERPAPI_BASE_URL = "https://serpapi.com/search"


def fetch_flights(
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str,
    currency: str = "EUR",
    hl: str = "de",
    gl: str = "de",
    max_stops: Optional[int] = None,
    airline_filter: Optional[list] = None,
) -> list[dict]:
    """
    Ruft Roundtrip-Flugdaten von SerpApi (Google Flights) ab.

    Gibt eine Liste von Flug-Dictionaries zurück:
      - origin, destination, outbound_date, return_date
      - price (float, EUR)
      - duration_minutes (int)
      - airline (str)
      - stops (int)
      - flight_details (dict, roh)
    """
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        raise EnvironmentError("SERPAPI_KEY nicht gesetzt. Bitte als Umgebungsvariable setzen.")

    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "currency": currency,
        "hl": hl,
        "gl": gl,
        "type": "1",  # 1 = Roundtrip
        "api_key": api_key,
    }

    logger.info(f"Abrufe: {origin} → {destination} | {outbound_date} ↔ {return_date}")

    try:
        response = requests.get(SERPAPI_BASE_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.error(f"API-Fehler für {origin}→{destination}: {e}")
        return []

    # Fehlerprüfung in der API-Antwort
    if "error" in data:
        logger.error(f"SerpApi Fehler: {data['error']}")
        return []

    results = []

    # "best_flights" und "other_flights" auswerten
    for section in ("best_flights", "other_flights"):
        for itinerary in data.get(section, []):
            try:
                price = itinerary.get("price")
                if price is None:
                    continue

                # Gesamtdauer des Roundtrips (Hin + Rück)
                total_duration = itinerary.get("total_duration")
                if total_duration is None:
                    # Fallback: Summe aller Legs
                    total_duration = sum(
                        leg.get("duration", 0) for leg in itinerary.get("flights", [])
                    )

                # Airline (erste Fluglinie im Itinerary)
                flights_legs = itinerary.get("flights", [])
                airline = flights_legs[0].get("airline", "Unbekannt") if flights_legs else "Unbekannt"

                # Anzahl Stopps (Layovers)
                stops = len(itinerary.get("layovers", []))

                # Optionaler Airline-Filter
                if airline_filter and not any(
                    af.lower() in airline.lower() for af in airline_filter
                ):
                    continue

                # Optionaler Stopp-Filter
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
                logger.warning(f"Itinerary übersprungen (Parsing-Fehler): {e}")
                continue

    logger.info(f"  → {len(results)} Ergebnis(se) gefunden")
    return results


def fetch_all_combinations(
    origins: list[str],
    destinations: list[str],
    outbound_dates: list[str],
    return_dates: list[str],
    currency: str = "EUR",
    hl: str = "de",
    gl: str = "de",
    max_stops: Optional[int] = None,
    airline_filter: Optional[list] = None,
    delay_seconds: float = 1.0,
) -> list[dict]:
    """
    Ruft alle OD-Kombinationen x Datumspaare ab.
    delay_seconds verhindert Rate-Limiting.
    """
    all_results = []

    total = len(origins) * len(destinations) * len(outbound_dates) * len(return_dates)
    count = 0

    for origin in origins:
        for destination in destinations:
            for out_date in outbound_dates:
                for ret_date in return_dates:
                    count += 1
                    logger.info(f"[{count}/{total}] {origin}→{destination} | {out_date}↔{ret_date}")

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
                    all_results.extend(flights)

                    if count < total:
                        time.sleep(delay_seconds)

    return all_results
