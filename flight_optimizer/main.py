"""
Flight Optimizer - Main Program
================================
Steps:
  1. Build all OD combinations x date windows from config.py
  2. Fetch flight data via SerpApi
  3. Calculate score (Price + Duration_h * Value-of-Time)
  4. Print top-N flights to the console
  5. Export all results to Excel

Run:
  python run_optimizer.py
  or:
  python -m flight_optimizer.main
"""

import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flight_optimizer import config
from flight_optimizer.date_utils import generate_date_range
from flight_optimizer.serpapi_client import fetch_all_combinations, enrich_with_return_legs
from flight_optimizer.scorer import calculate_scores, apply_filters
from flight_optimizer.printer import print_top_flights, print_summary_table
from flight_optimizer.exporter import export_to_excel
from flight_optimizer.cache import load_cache


def main():
    logger.info("=" * 60)
    logger.info("  Flight Optimizer MVP started")
    logger.info("=" * 60)

    # ── 1. Generate date lists ─────────────────────────────────────
    outbound_dates = generate_date_range(config.OUTBOUND_DATE, config.DATE_WINDOW_DAYS)
    return_dates = generate_date_range(config.RETURN_DATE, config.DATE_WINDOW_DAYS)

    logger.info(f"Origin airports:   {config.ORIGIN_AIRPORTS}")
    logger.info(f"Destination:       {config.DESTINATION_AIRPORTS}")
    logger.info(f"Outbound window:   {outbound_dates}")
    logger.info(f"Return window:     {return_dates}")
    logger.info(f"Value of Time:     {config.VALUE_OF_TIME_EUR_PER_HOUR} EUR/h")
    logger.info(f"Airline filter:    {config.AIRLINE_FILTER or 'none'}")
    logger.info(f"Max stops:         {config.MAX_STOPS if config.MAX_STOPS is not None else 'unlimited'}")
    logger.info(f"Cache enabled:     {config.USE_CACHE} ({config.CACHE_FILE})")
    logger.info(f"Mock mode:         USE_MOCK_DATA={config.USE_MOCK_DATA}  MOCK_FALLBACK={config.MOCK_FALLBACK}")

    total_queries = (
        len(config.ORIGIN_AIRPORTS)
        * len(config.DESTINATION_AIRPORTS)
        * len(outbound_dates)
        * len(return_dates)
    )
    logger.info(f"Possible queries:  {total_queries} (cache skips already-fetched ones)")
    logger.info("-" * 60)

    # ── 2. Load cache ──────────────────────────────────────────────
    cache = load_cache(config.CACHE_FILE) if config.USE_CACHE else None

    # ── 3. Fetch flight data ───────────────────────────────────────
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
        cache=cache,
        cache_file=config.CACHE_FILE if config.USE_CACHE else None,
        use_mock=config.USE_MOCK_DATA,
        mock_fallback=config.MOCK_FALLBACK,
    )

    if not flights:
        logger.warning("No flights found. Please check your configuration and API key.")
        sys.exit(1)

    logger.info(f"\nTotal flights retrieved: {len(flights)}")

    # ── 4. Calculate scores ────────────────────────────────────────
    df = calculate_scores(flights, value_of_time=config.VALUE_OF_TIME_EUR_PER_HOUR)

    # Optional post-filter (in case not already applied during API fetch)
    df = apply_filters(df, airline_filter=config.AIRLINE_FILTER, max_stops=config.MAX_STOPS)

    # ── 5. Fetch return leg details for top-N ─────────────────────
    logger.info(f"Fetching return leg details for top {config.TOP_N} flight(s)...")
    top_flights_list = df.head(config.TOP_N).to_dict("records")
    enriched = enrich_with_return_legs(
        flights=top_flights_list,
        top_n=config.TOP_N,
        cache=cache,
        cache_file=config.CACHE_FILE if config.USE_CACHE else None,
        currency=config.CURRENCY,
        hl=config.HL,
        gl=config.GL,
    )
    # Write enriched return data back into the DataFrame
    import pandas as pd
    enriched_df = pd.DataFrame(enriched)
    for col in ("return_segments", "return_layovers", "return_route",
                "return_duration_minutes", "return_stops"):
        if col in enriched_df.columns:
            df.loc[df.index[:config.TOP_N], col] = enriched_df[col].values

    # ── 6. Print results ───────────────────────────────────────────
    print_top_flights(df, top_n=config.TOP_N, value_of_time=config.VALUE_OF_TIME_EUR_PER_HOUR)
    print_summary_table(df, top_n=config.TOP_N)

    # ── 7. Export to Excel ─────────────────────────────────────────
    output_path = export_to_excel(df, output_path=config.EXCEL_OUTPUT_FILE)
    if output_path:
        logger.info(f"Excel file saved: {output_path}")
    else:
        logger.warning("Excel export failed.")

    logger.info("Flight Optimizer finished.")


if __name__ == "__main__":
    main()
