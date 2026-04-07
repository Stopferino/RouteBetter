"""
Flight Optimizer - Web Application
FastAPI backend that serves the UI and streams search results via SSE.
"""

import asyncio
import json
import logging
import math
import os
import sys
from datetime import date as _date, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse

logger = logging.getLogger(__name__)


def _sanitize_nan(obj):
    """Recursively replace float NaN/Inf with None so json.dumps produces valid JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    return obj


app = FastAPI(title="Flight Optimizer")
_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "index.html")

# ── Concurrency guards ─────────────────────────────────────────────────────────
_active_searches: int = 0
MAX_CONCURRENT_SEARCHES: int = 3      # max simultaneous user search sessions
OUTBOUND_CONCURRENCY: int = 8         # parallel outbound SerpApi calls per search
RETURN_CONCURRENCY: int = 5           # parallel return-leg SerpApi calls per search


def _date_variants(d: str, window: int) -> list:
    base = _date.fromisoformat(d)
    return [str(base + timedelta(days=i)) for i in range(-window, window + 1)]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/flight/usage")
async def api_usage():
    """
    Fetches live usage from SerpApi's /account.json endpoint.
    Falls back to the local counter if SerpApi is unreachable or the key is missing.
    """
    import urllib.request
    import urllib.error
    from flight_optimizer.usage_tracker import get_usage, MONTHLY_LIMIT

    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    if serpapi_key:
        try:
            url = f"https://serpapi.com/account.json?api_key={serpapi_key}"
            req = urllib.request.Request(url, headers={"User-Agent": "FlightOptimizer/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            used  = int(data.get("this_month_usage", 0))
            limit = int(data.get("searches_per_month", MONTHLY_LIMIT))
            return {
                "count":     used,
                "month":     data.get("account_last_searches_at", "")[:7],
                "limit":     limit,
                "remaining": max(0, limit - used),
                "pct_used":  round(used / limit * 100, 1) if limit else 0,
                "source":    "serpapi",
            }
        except Exception as exc:
            logger.warning(f"SerpApi account fetch failed: {exc}")

    local = get_usage()
    local["source"] = "local"
    return local


@app.get("/debug/pipeline")
async def debug_pipeline():
    """
    Runs the pipeline integrity check and returns a JSON report:
      - api_key_present: bool
      - cache: check_cache_integrity() result
      - mock_flights_available: bool
      - mock_flights_count: int
    """
    from flight_optimizer.mock_data import check_cache_integrity, load_mock_flights_from_cache
    from flight_optimizer import config

    cache_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "flight_cache.json"
    )
    api_key_present = bool(os.environ.get("SERPAPI_KEY", ""))
    cache_report = check_cache_integrity(cache_file)
    mock_flights = load_mock_flights_from_cache(cache_file)

    return {
        "api_key_present":     api_key_present,
        "use_mock_data":       config.USE_MOCK_DATA,
        "mock_fallback":       config.MOCK_FALLBACK,
        "cache":               cache_report,
        "mock_flights_available": len(mock_flights) > 0,
        "mock_flights_count":  len(mock_flights),
    }



@app.get("/search/stream")
async def search_stream(
    origins: str = Query(..., description="Comma-separated origin codes"),
    destinations: str = Query(..., description="Comma-separated destination codes"),
    outbound_date: str = Query(...),
    return_date: str = Query(...),
    value_of_time: float = Query(20.0),
    top_n: int = Query(30),
    max_stops: Optional[int] = Query(None),
    use_cache: bool = Query(True),
    date_window: int = Query(0),
    home_address: str = Query("", description="Home address near departure airport"),
    dest_address: str = Query("", description="Destination address near arrival airport"),
    ground_cost_per_km: float = Query(1.5, description="Kept for backward compat"),
    stop_penalty: float = Query(75.0, description="EUR penalty per stop (outbound+return)"),
    use_mock: bool = Query(False, description="Use mock/simulated data instead of live API"),
):
    origin_list = [o.strip().upper() for o in origins.split(",") if o.strip()]
    dest_list = [d.strip().upper() for d in destinations.split(",") if d.strip()]

    outbound_variants = _date_variants(outbound_date, date_window)
    return_variants = _date_variants(return_date, date_window)

    date_combos = [
        (od, rd)
        for od in outbound_variants
        for rd in return_variants
        if od < rd
    ]

    async def event_generator():
        global _active_searches

        def sse(data: dict) -> str:
            return f"data: {json.dumps(_sanitize_nan(data), ensure_ascii=False)}\n\n"

        if _active_searches >= MAX_CONCURRENT_SEARCHES:
            yield sse({
                "type": "error",
                "message": "Server is busy — too many concurrent searches. Please try again in a moment.",
            })
            return

        _active_searches += 1
        try:
            from flight_optimizer.serpapi_client import (
                fetch_flights, fetch_return_legs,
                QuotaExhaustedError, PastDateError, InvalidApiKeyError,
            )
            from flight_optimizer.scorer import calculate_scores, apply_filters, recalculate_scores_with_return
            from flight_optimizer.exporter import export_to_excel
            from flight_optimizer.cache import (
                load_cache, get_cached, get_cache_age_hours, set_cached, save_cache,
                get_cached_return, set_cached_return,
            )
            from flight_optimizer.ground_transport import calculate_ground_transport
            import pandas as pd

            loop = asyncio.get_event_loop()
            cache_age_hours_list: list[float] = []

            # ── Strict boundary validation on raw user-input dates ─────────────
            # This fires BEFORE any ±1-day window expansion so a past outbound
            # date is always rejected, even if the window would produce some
            # future variants.
            today = _date.today().isoformat()
            if outbound_date < today:
                yield sse({
                    "type": "error",
                    "message": (
                        f"Outbound date {outbound_date} is in the past. "
                        "Please choose a future departure date."
                    ),
                })
                return
            if return_date <= today:
                yield sse({
                    "type": "error",
                    "message": (
                        f"Return date {return_date} is in the past or today. "
                        "Please choose a future return date."
                    ),
                })
                return
            if return_date <= outbound_date:
                yield sse({
                    "type": "error",
                    "message": (
                        f"Return date {return_date} must be after outbound date {outbound_date}."
                    ),
                })
                return

            # ── Secondary filter: drop any window-expanded combos that slipped past today ─
            # (date_window expansion may produce negative-offset variants in the past)
            active_combos = [(od, rd) for od, rd in date_combos if od >= today and rd > today]
            if not active_combos:
                yield sse({
                    "type": "error",
                    "message": (
                        "No valid date combinations remain after applying the ±1 day window. "
                        "Please choose future dates and try again."
                    ),
                })
                return

            cache_file = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "flight_cache.json"
            )
            cache = await loop.run_in_executor(None, load_cache, cache_file)

            # ── Ground transport geocoding ─────────────────────────────────────
            ground_transport = None
            if home_address.strip() and dest_address.strip():
                yield sse({"type": "progress", "percent": 2, "label": "Geocoding addresses…"})
                yield sse({"type": "log", "message": f"Geocoding: '{home_address}' & '{dest_address}'"})
                try:
                    ground_transport = await loop.run_in_executor(
                        None,
                        lambda: calculate_ground_transport(
                            home_address.strip(), dest_address.strip(),
                            origin_airports=origin_list,
                            dest_airports=dest_list,
                        ),
                    )
                    if ground_transport["home_coords"]:
                        yield sse({"type": "log", "message": f"✓ Home → {ground_transport['home_display'][:60]}"})
                    else:
                        yield sse({"type": "log", "message": "⚠ Could not geocode home address — ground transport skipped"})
                        ground_transport = None
                    if ground_transport and ground_transport["dest_coords"]:
                        yield sse({"type": "log", "message": f"✓ Dest → {ground_transport['dest_display'][:60]}"})
                    else:
                        yield sse({"type": "log", "message": "⚠ Could not geocode destination address — ground transport skipped"})
                        ground_transport = None
                    if ground_transport:
                        leg_summary = ", ".join(
                            f"{k}: {v['time_minutes']:.0f}min/€{v['cost_eur']:.0f}"
                            for k, v in ground_transport["legs"].items() if v
                        )
                        yield sse({"type": "log", "message": f"✓ Ground legs: {leg_summary}"})
                        yield sse({"type": "ground_transport", "data": {
                            "home_display": ground_transport["home_display"][:80],
                            "dest_display": ground_transport["dest_display"][:80],
                            "ai_powered":   ground_transport.get("ai_powered", False),
                            "legs": ground_transport["legs"],
                        }})
                except Exception as gt_err:
                    logger.warning(f"Ground transport error: {gt_err}")
                    yield sse({"type": "log", "message": f"⚠ Ground transport unavailable: {gt_err}"})
                    ground_transport = None

            all_flights = []
            combinations = [
                (o, d, od, rd)
                for o in origin_list
                for d in dest_list
                for (od, rd) in active_combos
            ]
            total = len(combinations)

            if use_mock:
                yield sse({"type": "log", "message": "⚙ Simulation mode: using mock data (real API skipped)"})

            yield sse({
                "type": "log",
                "message": f"Starting search: {total} combination(s) "
                           f"({'±1 day window' if date_window else 'exact dates'}) — "
                           f"fetching up to {min(total, OUTBOUND_CONCURRENCY)} in parallel",
            })

            # ── Parallel outbound fetch ────────────────────────────────────────
            # Each route is fetched concurrently; a semaphore caps live API calls
            # at OUTBOUND_CONCURRENCY to stay within SerpApi rate limits.
            outbound_sem = asyncio.Semaphore(OUTBOUND_CONCURRENCY)
            quota_hit = False
            past_date_hit = False
            api_key_hit = False

            async def fetch_one_route(origin, dest, od, rd):
                nonlocal quota_hit, past_date_hit, api_key_hit
                label = f"{origin}→{dest}  {od} ↔ {rd}"

                # ── Simulation mode: serve mock data immediately ───────────────
                if use_mock:
                    from flight_optimizer.mock_data import load_mock_flights_from_cache
                    mocks = await loop.run_in_executor(
                        None,
                        lambda cf=cache_file, od_=od, rd_=rd: load_mock_flights_from_cache(
                            cf, outbound_date=od_, return_date=rd_
                        ),
                    )
                    return mocks, False, None, label

                cached = get_cached(cache, origin, dest, od, rd) if use_cache else None
                if cached is not None:
                    age = get_cache_age_hours(cache, origin, dest, od, rd)
                    return cached, True, age, label
                if quota_hit or past_date_hit or api_key_hit:
                    return [], False, None, label
                async with outbound_sem:
                    def _do(o=origin, d=dest, outd=od, retd=rd):
                        return fetch_flights(
                            origin=o, destination=d,
                            outbound_date=outd, return_date=retd,
                            currency="EUR", hl="en", gl="us",
                            max_stops=max_stops,
                        )
                    try:
                        flights = await loop.run_in_executor(None, _do)
                    except QuotaExhaustedError:
                        quota_hit = True
                        # Fallback to mock on quota exhaustion
                        from flight_optimizer.mock_data import load_mock_flights_from_cache
                        mocks = await loop.run_in_executor(
                            None,
                            lambda cf=cache_file, od_=od, rd_=rd: load_mock_flights_from_cache(
                                cf, outbound_date=od_, return_date=rd_
                            ),
                        )
                        if mocks:
                            return mocks, False, None, label
                        return [], False, None, label
                    except PastDateError:
                        past_date_hit = True
                        return [], False, None, label
                    except InvalidApiKeyError:
                        api_key_hit = True
                        # Fallback to mock on invalid key
                        from flight_optimizer.mock_data import load_mock_flights_from_cache
                        mocks = await loop.run_in_executor(
                            None,
                            lambda cf=cache_file, od_=od, rd_=rd: load_mock_flights_from_cache(
                                cf, outbound_date=od_, return_date=rd_
                            ),
                        )
                        if mocks:
                            return mocks, False, None, label
                        return [], False, None, label
                    if flights:
                        set_cached(cache, origin, dest, od, rd, flights)
                    return flights, False, None, label

            tasks = [
                asyncio.create_task(fetch_one_route(o, d, od, rd))
                for (o, d, od, rd) in combinations
            ]

            completed_outbound = 0
            cache_dirty = False
            for coro in asyncio.as_completed(tasks):
                flights, from_cache, age, label = await coro
                completed_outbound += 1
                yield sse({
                    "type": "progress",
                    "percent": int((completed_outbound / total) * 60),
                    "label": f"{completed_outbound}/{total} routes done…",
                })
                if from_cache:
                    if age is not None:
                        cache_age_hours_list.append(age)
                    yield sse({"type": "log", "message": f"✓ Cache: {label} ({len(flights)} result(s))"})
                elif use_mock or any(f.get("_is_mock") for f in flights):
                    yield sse({"type": "log", "message": f"⚙ Mock: {label} ({len(flights)} simulated flight(s))"})
                else:
                    yield sse({"type": "log", "message": f"✓ Live: {label} ({len(flights)} flight(s))"})
                    if flights:
                        cache_dirty = True
                all_flights.extend(flights)

            # Single cache write after all parallel fetches (not per-fetch)
            if cache_dirty:
                await loop.run_in_executor(None, save_cache, cache, cache_file)

            # Surface hard errors first — these abort the search with a clear message
            if api_key_hit and not all_flights:
                yield sse({
                    "type": "error",
                    "message": (
                        "Invalid or expired SerpApi API key. "
                        "Check that SERPAPI_KEY is set correctly in your environment."
                    ),
                })
                return
            elif api_key_hit:
                yield sse({
                    "type": "log",
                    "message": (
                        "⚠ Invalid API key detected — showing mock/cached data as fallback."
                    ),
                })
            if past_date_hit and not all_flights:
                yield sse({
                    "type": "error",
                    "message": (
                        "The search dates are in the past. "
                        "Please choose future dates and try again."
                    ),
                })
                return
            if quota_hit and not all_flights:
                yield sse({
                    "type": "error",
                    "message": (
                        "SerpApi monthly quota exhausted — no live results available. "
                        "Enable 'Use Cache' to see previously fetched flights, "
                        "or upgrade your SerpApi plan at serpapi.com/manage-api-key."
                    ),
                })
                return
            elif quota_hit:
                yield sse({
                    "type": "log",
                    "message": (
                        "⚠ SerpApi quota exhausted mid-search — showing cached/mock results. "
                        "Some routes may be missing."
                    ),
                })
            elif not all_flights:
                yield sse({"type": "error", "message": "No flights found. Try different dates or airports, or check your API quota."})
                return

            yield sse({"type": "progress", "percent": 65, "label": "Calculating scores…"})
            df = await loop.run_in_executor(
                None,
                lambda: calculate_scores(all_flights, value_of_time=value_of_time),
            )

            for _col, _default in [("booking_class", "Economy"), ("currency", "EUR")]:
                if _col in df.columns:
                    df[_col] = df[_col].fillna(_default)
            if "fare_brand" in df.columns:
                df["fare_brand"] = df["fare_brand"].where(df["fare_brand"].notna(), other="")

            try:
                df = await loop.run_in_executor(
                    None,
                    lambda: apply_filters(df, max_stops=max_stops),
                )
            except Exception as filter_err:
                logger.error(f"apply_filters failed: {filter_err}", exc_info=True)
                yield sse({"type": "error", "message": f"Filter error: {filter_err}"})
                return
            df = df.reset_index(drop=True)

            effective_top_n = min(top_n, len(df))
            if effective_top_n == 0:
                yield sse({"type": "error", "message": f"No scoreable flights found after filtering ({len(all_flights)} collected, {len(df)} after filter). Try relaxing stops or date range."})
                return

            CANDIDATE_BUFFER = 3
            MIN_CANDIDATES = 10
            candidate_n = min(max(effective_top_n + CANDIDATE_BUFFER, MIN_CANDIDATES), len(df))

            yield sse({
                "type": "log",
                "message": (
                    f"Scored {len(df)} flights (outbound). "
                    f"Fetching return details for {candidate_n} candidates…"
                ),
            })
            yield sse({"type": "progress", "percent": 70, "label": "Fetching return leg details…"})

            candidate_flights = df.head(candidate_n).to_dict("records")

            # ── Parallel return-leg fetch ──────────────────────────────────────
            return_sem = asyncio.Semaphore(RETURN_CONCURRENCY)
            ret_quota_hit = False

            async def fetch_return_one(rank_idx, flight):
                nonlocal ret_quota_hit
                token = flight.get("departure_token", "")
                if not token:
                    return rank_idx, flight, None, False
                cached_ret = get_cached_return(cache, token) if use_cache else None
                if cached_ret:
                    flight.update(cached_ret)
                    return rank_idx, flight, None, True  # (idx, flight, ret_data, from_cache)
                if ret_quota_hit:
                    return rank_idx, flight, None, False
                async with return_sem:
                    def _do_ret(t=token, f=flight):
                        return fetch_return_legs(
                            departure_token=t,
                            origin=f["origin"], destination=f["destination"],
                            outbound_date=f["outbound_date"], return_date=f["return_date"],
                            currency="EUR", hl="en", gl="us",
                        )
                    try:
                        ret = await loop.run_in_executor(None, _do_ret)
                    except QuotaExhaustedError:
                        ret_quota_hit = True
                        logger.warning(f"Return leg {rank_idx + 1}: quota exhausted")
                        ret = None
                    except Exception as ret_err:
                        logger.warning(f"Return leg {rank_idx + 1} fetch raised: {ret_err}")
                        ret = None
                    if ret:
                        flight.update(ret)
                    return rank_idx, flight, ret, False

            return_tasks = [
                asyncio.create_task(fetch_return_one(i, f))
                for i, f in enumerate(candidate_flights)
            ]

            completed_returns = 0
            return_cache_dirty = False
            for coro in asyncio.as_completed(return_tasks):
                rank_idx, updated_flight, ret_data, from_cache = await coro
                candidate_flights[rank_idx] = updated_flight
                completed_returns += 1
                yield sse({
                    "type": "progress",
                    "percent": 70 + int((completed_returns / max(candidate_n, 1)) * 22),
                    "label": f"Return legs: {completed_returns}/{candidate_n} done…",
                })
                if from_cache:
                    yield sse({"type": "log", "message": f"✓ Return leg {rank_idx + 1} from cache"})
                elif ret_data:
                    set_cached_return(cache, updated_flight.get("departure_token", ""), ret_data)
                    return_cache_dirty = True
                    yield sse({"type": "log", "message": f"✓ Return leg {rank_idx + 1} fetched"})
                else:
                    yield sse({"type": "log", "message": f"⚠ Return leg {rank_idx + 1} unavailable — using outbound score"})

            if return_cache_dirty:
                await loop.run_in_executor(None, save_cache, cache, cache_file)

            if ret_quota_hit:
                yield sse({
                    "type": "log",
                    "message": (
                        "⚠ SerpApi quota exhausted during return-leg fetch — "
                        "some return details may be incomplete. Scores based on outbound data."
                    ),
                })

            yield sse({"type": "progress", "percent": 93, "label": "Re-ranking by round-trip score…"})
            candidate_flights = recalculate_scores_with_return(
                candidate_flights, value_of_time, stop_penalty_eur=stop_penalty
            )

            if ground_transport:
                for f in candidate_flights:
                    dep_leg = ground_transport["legs"].get(f.get("origin", ""))
                    arr_leg = ground_transport["legs"].get(f.get("destination", ""))
                    dep_min  = dep_leg["duration_minutes"] if dep_leg else 0.0
                    arr_min  = arr_leg["duration_minutes"] if arr_leg else 0.0
                    dep_cost = dep_leg["cost"] if dep_leg else 0.0
                    arr_cost = arr_leg["cost"] if arr_leg else 0.0
                    ground_time_h = 2.0 * (dep_min + arr_min) / 60.0
                    ground_cost   = 2.0 * (dep_cost + arr_cost)
                    f["ground_dep_minutes"] = dep_min
                    f["ground_arr_minutes"] = arr_min
                    f["ground_dep_cost"]    = dep_cost
                    f["ground_arr_cost"]    = arr_cost
                    f["ground_total_cost"]  = round(ground_cost, 2)
                    f["ground_dep_mode"]    = dep_leg.get("mode", "") if dep_leg else ""
                    f["ground_arr_mode"]    = arr_leg.get("mode", "") if arr_leg else ""
                    f["ground_dep_notes"]   = dep_leg.get("notes", "") if dep_leg else ""
                    f["ground_arr_notes"]   = arr_leg.get("notes", "") if arr_leg else ""
                    f["score"] = round(
                        float(f.get("score") or 0) + ground_cost + ground_time_h * value_of_time,
                        2,
                    )
                candidate_flights = sorted(candidate_flights, key=lambda x: x.get("score", float("inf")))
                yield sse({"type": "log", "message": "✓ Scores adjusted for door-to-door ground transport"})

            top_flights = candidate_flights[:effective_top_n]

            yield sse({"type": "progress", "percent": 97, "label": "Preparing results…"})

            results_out = []
            for rank_idx, f in enumerate(top_flights):
                ret_stops = f.get("return_stops")
                try:
                    ret_stops_int = int(ret_stops) if ret_stops is not None and str(ret_stops) not in ("nan", "None") else None
                except (ValueError, TypeError):
                    ret_stops_int = None

                results_out.append({
                    "rank": rank_idx + 1,
                    "score": round(float(f.get("score") or 0), 2),
                    "price": float(f.get("price") or 0),
                    "airline": f.get("airline", ""),
                    "origin": f.get("origin", ""),
                    "destination": f.get("destination", ""),
                    "outbound_date": f.get("outbound_date", ""),
                    "return_date": f.get("return_date", ""),
                    "outbound_route": f.get("outbound_route", ""),
                    "return_route": f.get("return_route", ""),
                    "duration_str": f.get("duration_str", ""),
                    "stops": int(f.get("stops") or 0),
                    "return_stops": ret_stops_int,
                    "return_duration_minutes": f.get("return_duration_minutes"),
                    "outbound_segments": f.get("outbound_segments") if isinstance(f.get("outbound_segments"), list) else [],
                    "outbound_layovers": f.get("outbound_layovers") if isinstance(f.get("outbound_layovers"), list) else [],
                    "return_segments": f.get("return_segments") if isinstance(f.get("return_segments"), list) else [],
                    "return_layovers": f.get("return_layovers") if isinstance(f.get("return_layovers"), list) else [],
                    "booking_class": f.get("booking_class", "Economy"),
                    "fare_brand": f.get("fare_brand"),
                    "currency": f.get("currency", "EUR"),
                    "ground_dep_minutes": f.get("ground_dep_minutes"),
                    "ground_arr_minutes": f.get("ground_arr_minutes"),
                    "ground_dep_cost":    f.get("ground_dep_cost"),
                    "ground_arr_cost":    f.get("ground_arr_cost"),
                    "ground_total_cost":  f.get("ground_total_cost"),
                    "ground_dep_mode":    f.get("ground_dep_mode", ""),
                    "ground_arr_mode":    f.get("ground_arr_mode", ""),
                    "ground_dep_notes":   f.get("ground_dep_notes", ""),
                    "ground_arr_notes":   f.get("ground_arr_notes", ""),
                    "time_cost_base":   f.get("time_cost_base"),
                    "stops_penalty":    f.get("stops_penalty"),
                    "night_penalty":    f.get("night_penalty"),
                    "layover_penalty":  f.get("layover_penalty"),
                    "out_is_night":     f.get("out_is_night", False),
                    "ret_is_night":     f.get("ret_is_night", False),
                    "duration_minutes": int(f.get("duration_minutes") or 0),
                    "total_flight_h":   f.get("total_flight_h", 0),
                    "night_hours":      f.get("night_hours", 0),
                    "excess_layover_h": f.get("excess_layover_h", 0),
                    "ground_time_h":    round(2.0 * ((f.get("ground_dep_minutes") or 0) + (f.get("ground_arr_minutes") or 0)) / 60.0, 4),
                    "booking_token":      f.get("booking_token", ""),
                    "google_flights_url": f.get("google_flights_url", ""),
                })

            import tempfile, uuid
            tmp_id = str(uuid.uuid4())[:8]
            tmp_path = os.path.join(tempfile.gettempdir(), f"flight_results_{tmp_id}.xlsx")
            remaining = df.iloc[candidate_n:].to_dict("records")
            final_df = pd.DataFrame(top_flights + remaining)
            await loop.run_in_executor(None, lambda: export_to_excel(final_df, tmp_path))

            # Compute cache age label for the UI
            cache_age_label = None
            if cache_age_hours_list and len(cache_age_hours_list) == total:
                avg_age = sum(cache_age_hours_list) / len(cache_age_hours_list)
                if avg_age < 1:
                    cache_age_label = "< 1 hour ago"
                elif avg_age < 24:
                    cache_age_label = f"{avg_age:.0f}h ago"
                else:
                    days = avg_age / 24
                    cache_age_label = f"{days:.0f}d ago"

            yield sse({
                "type": "results",
                "flights": results_out,
                "total_found": len(df),
                "export_id": tmp_id,
                "cache_age_label": cache_age_label,
            })
            yield sse({"type": "progress", "percent": 100, "label": "Done!"})
            yield sse({"type": "done"})

        finally:
            _active_searches -= 1

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/export/{export_id}")
async def download_excel(export_id: str):
    import tempfile
    path = os.path.join(tempfile.gettempdir(), f"flight_results_{export_id}.xlsx")
    if not os.path.exists(path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Export file not found")
    from fastapi.responses import FileResponse
    return FileResponse(
        path,
        filename="flight_results.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("flight_webapp.app:app", host="0.0.0.0", port=port, reload=False)
