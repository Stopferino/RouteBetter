"""
Flight Optimizer - Hauptprogramm
=================================
Ablauf:
  1. Alle OD-Kombinationen x Datumsfenster aus config.py aufbauen
  2. Flugdaten über SerpApi abrufen
  3. Score berechnen (Preis + Dauer_h * Value-of-Time)
  4. Top-N Flüge auf der Konsole ausgeben
  5. Alle Ergebnisse in Excel exportieren

Ausführen:
  python -m flight_optimizer.main
  oder:
  python flight_optimizer/main.py
"""

import logging
import sys
from pathlib import Path

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Projektverzeichnis zum Pfad hinzufügen (falls direkt ausgeführt)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flight_optimizer import config
from flight_optimizer.date_utils import generate_date_range
from flight_optimizer.serpapi_client import fetch_all_combinations
from flight_optimizer.scorer import calculate_scores, apply_filters
from flight_optimizer.printer import print_top_flights, print_summary_table
from flight_optimizer.exporter import export_to_excel


def main():
    logger.info("=" * 60)
    logger.info("  Flight Optimizer MVP gestartet")
    logger.info("=" * 60)

    # ── 1. Datumslisten generieren ─────────────────────────────────
    outbound_dates = generate_date_range(config.OUTBOUND_DATE, config.DATE_WINDOW_DAYS)
    return_dates = generate_date_range(config.RETURN_DATE, config.DATE_WINDOW_DAYS)

    logger.info(f"Abflughäfen:       {config.ORIGIN_AIRPORTS}")
    logger.info(f"Zielflughäfen:     {config.DESTINATION_AIRPORTS}")
    logger.info(f"Hinflug-Fenster:   {outbound_dates}")
    logger.info(f"Rückflug-Fenster:  {return_dates}")
    logger.info(f"Value of Time:     {config.VALUE_OF_TIME_EUR_PER_HOUR} €/h")
    logger.info(f"Airline-Filter:    {config.AIRLINE_FILTER or 'keiner'}")
    logger.info(f"Max. Stopps:       {config.MAX_STOPS if config.MAX_STOPS is not None else 'unbegrenzt'}")

    total_queries = (
        len(config.ORIGIN_AIRPORTS)
        * len(config.DESTINATION_AIRPORTS)
        * len(outbound_dates)
        * len(return_dates)
    )
    logger.info(f"Gesamte API-Anfragen: {total_queries}")
    logger.info("-" * 60)

    # ── 2. Flugdaten abrufen ───────────────────────────────────────
    flights = fetch_all_combinations(
        origins=config.ORIGIN_AIRPORTS,
        destinations=config.DESTINATION_AIRPORTS,
        outbound_dates=outbound_dates,
        return_dates=return_dates,
        currency=config.CURRENCY,
        hl=config.HL,
        gl=config.GL,
        max_stops=config.MAX_STOPS,
        airline_filter=config.AIRLINE_FILTER,
        delay_seconds=1.0,
    )

    if not flights:
        logger.warning("Keine Flüge gefunden. Bitte Konfiguration und API-Key prüfen.")
        sys.exit(1)

    logger.info(f"\nGesamt abgerufene Flüge: {len(flights)}")

    # ── 3. Score berechnen ────────────────────────────────────────
    df = calculate_scores(flights, value_of_time=config.VALUE_OF_TIME_EUR_PER_HOUR)

    # Optionale Nachfilterung (falls nicht schon in API-Abruf erfolgt)
    df = apply_filters(df, airline_filter=config.AIRLINE_FILTER, max_stops=config.MAX_STOPS)

    # ── 4. Ergebnisse ausgeben ────────────────────────────────────
    print_top_flights(df, top_n=config.TOP_N, value_of_time=config.VALUE_OF_TIME_EUR_PER_HOUR)
    print_summary_table(df, top_n=config.TOP_N)

    # ── 5. Excel-Export ───────────────────────────────────────────
    output_path = export_to_excel(df, output_path=config.EXCEL_OUTPUT_FILE)
    if output_path:
        logger.info(f"✓ Excel-Datei gespeichert: {output_path}")
    else:
        logger.warning("Excel-Export fehlgeschlagen.")

    logger.info("Flight Optimizer abgeschlossen.")


if __name__ == "__main__":
    main()
