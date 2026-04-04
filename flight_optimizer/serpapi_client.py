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
    """Prüft, ob die Daten in der Zukunft liegen und ob Rückflug nach Hinflug ist."""
    today = date.today()
    out = date.fromisoformat(outbound_date)
    ret = date.fromisoformat(return_date)

    if out <= today:
        raise ValueError(
            f"Hinflugdatum {outbound_date} liegt in der Vergangenheit (heute: {today}). "
            "Bitte ein zukünftiges Datum in config.py eintragen."
        )
    if ret <= out:
        raise ValueError(
            f"Rückflugdatum {return_date} muss nach dem Hinflugdatum {outbound_date} liegen."
        )


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
        raise EnvironmentError(
            "SERPAPI_KEY nicht gesetzt. Bitte als Umgebungsvariable / Secret setzen."
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
        "type": "1",  # 1 = Roundtrip
        "api_key": api_key,
    }

    # Optionaler nativer Stopp-Filter (SerpApi: 0=nur Direkt, 1=max 1 Stopp, 2=max 2 Stopps)
    if max_stops is not None and max_stops in (0, 1, 2):
        params["stops"] = str(max_stops)

    logger.info(f"Abrufe: {origin} → {destination} | {outbound_date} ↔ {return_date}")

    max_retries = 3
    retry_delay = 5  # Sekunden zwischen Wiederholungen
    data = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(SERPAPI_BASE_URL, params=params, timeout=60)
            data = response.json()
            break  # Erfolgreich → Schleife beenden
        except requests.Timeout:
            if attempt < max_retries:
                logger.warning(
                    f"Timeout bei {origin}→{destination} (Versuch {attempt}/{max_retries}), "
                    f"warte {retry_delay}s und versuche erneut..."
                )
                time.sleep(retry_delay)
            else:
                logger.warning(
                    f"Timeout bei {origin}→{destination} nach {max_retries} Versuchen — übersprungen."
                )
                return []
        except requests.RequestException as e:
            logger.warning(f"Netzwerkfehler bei {origin}→{destination}: {e} — übersprungen.")
            return []
        except ValueError as e:
            logger.error(f"Ungültige JSON-Antwort: {e}")
            return []

    if data is None:
        return []

    # Fehlerprüfung in der API-Antwort (auch bei HTTP 4xx/5xx)
    if "error" in data:
        err_msg = data["error"]

        # Keine Ergebnisse = normaler Fall, kein echter Fehler
        if "hasn't returned any results" in err_msg or "no results" in err_msg.lower():
            logger.warning(f"Keine Ergebnisse für {origin}→{destination} | {outbound_date}↔{return_date} (übersprungen)")
            return []

        # Echte Fehler → ERROR + ggf. Abbruch
        logger.error(f"SerpApi-Fehler: {err_msg}")

        if "past" in err_msg.lower():
            logger.error(
                "  → Das Datum liegt in der Vergangenheit! "
                "Bitte OUTBOUND_DATE und RETURN_DATE in config.py auf ein zukünftiges Datum setzen."
            )
            sys.exit(1)
        if "api_key" in err_msg.lower() or "invalid" in err_msg.lower():
            logger.error("  → Ungültiger oder abgelaufener SERPAPI_KEY.")
            sys.exit(1)
        return []

    results = []

    # "best_flights" und "other_flights" auswerten
    for section in ("best_flights", "other_flights"):
        for itinerary in data.get(section, []):
            try:
                price = itinerary.get("price")
                if price is None:
                    continue

                # Gesamtdauer des Roundtrips
                total_duration = itinerary.get("total_duration")
                if total_duration is None:
                    # Fallback: Summe aller Legs
                    total_duration = sum(
                        leg.get("duration", 0) for leg in itinerary.get("flights", [])
                    )

                # Airline (erste Fluglinie im Itinerary)
                flights_legs = itinerary.get("flights", [])
                airline = (
                    flights_legs[0].get("airline", "Unbekannt")
                    if flights_legs
                    else "Unbekannt"
                )

                # Anzahl Stopps (Layovers)
                stops = len(itinerary.get("layovers", []))

                # Optionaler Airline-Filter (Teilstring-Match)
                if airline_filter and not any(
                    af.lower() in airline.lower() for af in airline_filter
                ):
                    continue

                # Optionaler Stopp-Filter (Feinfilterung nach Python-Seite)
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
    # Datumsvalidierung vor dem ersten API-Aufruf
    for out_date in outbound_dates:
        for ret_date in return_dates:
            _validate_dates(out_date, ret_date)

    all_results = []
    total = len(origins) * len(destinations) * len(outbound_dates) * len(return_dates)
    count = 0

    for origin in origins:
        for destination in destinations:
            for out_date in outbound_dates:
                for ret_date in return_dates:
                    count += 1
                    logger.info(
                        f"[{count}/{total}] {origin}→{destination} | {out_date}↔{ret_date}"
                    )

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
