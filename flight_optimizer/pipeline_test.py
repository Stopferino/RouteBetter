"""
Flight Optimizer - Pipeline Debug / Test Script
================================================
Run with:
    python -m flight_optimizer.pipeline_test
    python flight_optimizer/pipeline_test.py

What this script does:
  1. Checks whether SERPAPI_KEY is set
  2. Calls the SerpApi with a sample route / date and reports success or failure
  3. Verifies the cache (check_cache_integrity)
  4. Reports how many flights are stored in the cache
  5. Generates a batch of mock flights and shows a sample

Example output:
    ── Step 1: API key check ──────────────────────────────────────
    ✓ SERPAPI_KEY is set (last 4 chars: ****xxxx)

    ── Step 2: Live API call ──────────────────────────────────────
    Fetching: HKG -> FRA | 2026-07-25 <-> 2026-08-02
    ✓ API SUCCESS — 8 flight(s) returned

    ── Step 3: Cache integrity ────────────────────────────────────
    ✓ Cache OK — 3 entries, 24 flights stored in cache

    ── Step 4: Mock data generation ──────────────────────────────
    ✓ 24 mock flight(s) generated from cache
      Sample mock #1: Qatar Airways  HKG→FRA  €1052.30  1055 min  1 stop
"""

import logging
import os
import sys
from pathlib import Path

# ── Path setup so this runs both as a module and as a plain script ─────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

from flight_optimizer import config
from flight_optimizer.mock_data import check_cache_integrity, load_mock_flights_from_cache

# ── Helpers ───────────────────────────────────────────────────────────────────

def _sep(title: str) -> None:
    print(f"\n── {title} {'─' * max(0, 52 - len(title))}")


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _warn(msg: str) -> None:
    print(f"  ⚠ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


# ── Test steps ────────────────────────────────────────────────────────────────

def step1_check_api_key() -> bool:
    """Step 1 — Verify SERPAPI_KEY is present in the environment."""
    _sep("Step 1: API key check")
    key = os.environ.get("SERPAPI_KEY", "")
    if key:
        masked = "*" * max(0, len(key) - 4) + key[-4:]
        _ok(f"SERPAPI_KEY is set ({masked})")
        return True
    else:
        _fail(
            "SERPAPI_KEY is NOT set. "
            "Add it as an environment variable or Replit secret.\n"
            "     Simulation mode will be used instead."
        )
        return False


def step2_live_api_call(
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str,
) -> list[dict]:
    """
    Step 2 — Make one real SerpApi call and return the flights found.
    Returns an empty list on failure.
    """
    _sep("Step 2: Live API call")
    from flight_optimizer.serpapi_client import (
        fetch_flights,
        QuotaExhaustedError,
        PastDateError,
        InvalidApiKeyError,
    )

    print(f"  Fetching: {origin} -> {destination} | {outbound_date} <-> {return_date}")
    try:
        flights = fetch_flights(
            origin=origin,
            destination=destination,
            outbound_date=outbound_date,
            return_date=return_date,
            currency=config.CURRENCY,
            hl=config.HL,
            gl=config.GL,
        )
        if flights:
            _ok(f"API SUCCESS — {len(flights)} flight(s) returned")
        else:
            _warn("API call succeeded but returned 0 flights (no results for this route/date)")
        return flights

    except EnvironmentError as exc:
        _fail(f"API FAILED — missing key: {exc}")
    except InvalidApiKeyError as exc:
        _fail(f"API FAILED — invalid/expired API key: {exc}")
    except QuotaExhaustedError as exc:
        _fail(f"API FAILED — monthly quota exhausted: {exc}")
    except PastDateError as exc:
        _fail(f"API FAILED — date in the past: {exc}")
    except Exception as exc:  # noqa: BLE001
        _fail(f"API FAILED — unexpected error: {exc}")

    return []


def step3_cache_integrity(cache_file: str) -> dict:
    """Step 3 — Run check_cache_integrity and print a summary."""
    _sep("Step 3: Cache integrity")
    result = check_cache_integrity(cache_file)

    if result["ok"]:
        _ok(
            f"Cache OK — {result['entries']} entries, "
            f"{result['total_flights']} flights stored in cache"
        )
    else:
        if result["entries"] == 0:
            _warn("Cache is empty or missing — no previously fetched data available")
        else:
            _warn(f"Cache has issues ({len(result['issues'])} problem(s)):")
            for issue in result["issues"][:5]:  # show at most 5
                print(f"     • {issue}")
            if len(result["issues"]) > 5:
                print(f"     … and {len(result['issues']) - 5} more")

    return result


def step4_mock_data(
    cache_file: str,
    outbound_date: str,
    return_date: str,
) -> list[dict]:
    """Step 4 — Generate mock flights from the cache and show a sample."""
    _sep("Step 4: Mock data generation")
    mock = load_mock_flights_from_cache(
        cache_file,
        outbound_date=outbound_date,
        return_date=return_date,
    )

    if mock:
        _ok(f"{len(mock)} mock flight(s) generated from cache")
        sample = mock[0]
        route = sample.get("outbound_route", f"{sample.get('origin','?')}->{sample.get('destination','?')}")
        print(
            f"  Sample mock #1: {sample.get('airline', 'Unknown'):<20}"
            f"  {route:<15}"
            f"  €{sample.get('price', 0):<9.2f}"
            f"  {sample.get('duration_minutes', 0)} min"
            f"  {sample.get('stops', 0)} stop(s)"
            f"  [mock={sample.get('_is_mock', False)}]"
        )
    else:
        _warn(
            "No mock flights generated — cache is empty. "
            "Run a real search first (or add data to flight_cache.json) "
            "to enable simulation mode."
        )

    return mock


def step5_store_api_results_in_cache(
    flights: list[dict],
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str,
    cache_file: str,
) -> None:
    """Step 5 — Store a successful API result in the cache and confirm."""
    if not flights:
        return

    _sep("Step 5: Write to cache")
    from flight_optimizer.cache import load_cache, set_cached, save_cache

    cache = load_cache(cache_file)
    set_cached(cache, origin, destination, outbound_date, return_date, flights)
    save_cache(cache, cache_file)

    # Re-run integrity to reflect new data
    result = check_cache_integrity(cache_file)
    _ok(
        f"Wrote {len(flights)} flights to cache — "
        f"total now: {result['total_flights']} flights in {result['entries']} entries"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def run_pipeline_test(
    origin: str = "HKG",
    destination: str = "FRA",
    outbound_date: str = config.OUTBOUND_DATE,
    return_date: str = config.RETURN_DATE,
    cache_file: str | None = None,
) -> None:
    """
    Run the full pipeline debug test.

    Args:
        origin:        IATA code of the departure airport.
        destination:   IATA code of the arrival airport.
        outbound_date: Outbound date (YYYY-MM-DD).
        return_date:   Return date (YYYY-MM-DD).
        cache_file:    Path to the cache JSON. Defaults to the repo-root cache.
    """
    if cache_file is None:
        cache_file = str(_REPO_ROOT / config.CACHE_FILE)

    print("=" * 58)
    print("  Flight Optimizer — Pipeline Debug Test")
    print("=" * 58)
    print(f"  Route:  {origin} → {destination}")
    print(f"  Dates:  {outbound_date} → {return_date}")
    print(f"  Cache:  {cache_file}")
    print(f"  USE_MOCK_DATA: {config.USE_MOCK_DATA}")
    print(f"  MOCK_FALLBACK: {config.MOCK_FALLBACK}")

    # Step 1 — API key
    has_key = step1_check_api_key()

    # Step 2 — Live API (skip in mock-only mode)
    live_flights: list[dict] = []
    if config.USE_MOCK_DATA:
        _sep("Step 2: Live API call")
        _warn("Skipped — USE_MOCK_DATA=True in config.py")
    elif has_key:
        live_flights = step2_live_api_call(origin, destination, outbound_date, return_date)
    else:
        _sep("Step 2: Live API call")
        _warn("Skipped — no API key set")

    # Step 3 — Cache integrity
    step3_cache_integrity(cache_file)

    # Step 4 — Mock data
    step4_mock_data(cache_file, outbound_date, return_date)

    # Step 5 — Store live results (if any)
    if live_flights:
        step5_store_api_results_in_cache(
            live_flights, origin, destination, outbound_date, return_date, cache_file
        )

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 58)
    print("  Summary")
    print("=" * 58)

    if live_flights:
        print(f"  API:    ✓ SUCCESS — {len(live_flights)} flight(s)")
    elif config.USE_MOCK_DATA:
        print("  API:    — (simulation mode active)")
    elif has_key:
        print("  API:    ✗ FAILED or no results")
    else:
        print("  API:    ✗ FAILED (no key)")

    cache_result = check_cache_integrity(cache_file)
    if cache_result["ok"]:
        print(
            f"  Cache:  ✓ OK — {cache_result['total_flights']} flights "
            f"in {cache_result['entries']} entries"
        )
    else:
        print(f"  Cache:  ⚠ {cache_result['issues'][0] if cache_result['issues'] else 'empty'}")

    mock_flights = load_mock_flights_from_cache(cache_file, outbound_date, return_date)
    if mock_flights:
        print(f"  Mock:   ✓ {len(mock_flights)} mock flight(s) available")
    else:
        print("  Mock:   ⚠ No mock data (cache is empty)")

    print("")


if __name__ == "__main__":
    run_pipeline_test()
