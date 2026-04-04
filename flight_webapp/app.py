"""
Flight Optimizer - Web Application
FastAPI backend that serves the UI and streams search results via SSE.
"""

import asyncio
import io
import json
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse

app = FastAPI(title="Flight Optimizer")
_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "index.html")


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/search/stream")
async def search_stream(
    origins: str = Query(..., description="Comma-separated origin codes"),
    destinations: str = Query(..., description="Comma-separated destination codes"),
    outbound_date: str = Query(...),
    return_date: str = Query(...),
    value_of_time: float = Query(20.0),
    top_n: int = Query(5),
    max_stops: Optional[int] = Query(None),
    use_cache: bool = Query(True),
):
    origin_list = [o.strip().upper() for o in origins.split(",") if o.strip()]
    dest_list = [d.strip().upper() for d in destinations.split(",") if d.strip()]

    async def event_generator():
        from flight_optimizer.serpapi_client import fetch_flights, enrich_with_return_legs
        from flight_optimizer.scorer import calculate_scores, apply_filters
        from flight_optimizer.exporter import export_to_excel
        from flight_optimizer.cache import load_cache, get_cached, set_cached, save_cache
        import pandas as pd

        loop = asyncio.get_event_loop()

        def sse(data: dict) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        cache = {}
        cache_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "flight_cache.json")
        if use_cache:
            cache = await loop.run_in_executor(None, load_cache, cache_file)

        all_flights = []
        combinations = [(o, d) for o in origin_list for d in dest_list]
        total = len(combinations)

        yield sse({"type": "log", "message": f"Starting search: {total} route combination(s)"})

        for idx, (origin, dest) in enumerate(combinations):
            label = f"{origin} → {dest}  ({outbound_date} ↔ {return_date})"
            yield sse({
                "type": "progress",
                "percent": int((idx / total) * 60),
                "label": f"Searching {label}…",
            })

            cached = get_cached(cache, origin, dest, outbound_date, return_date) if use_cache else None
            if cached is not None:
                yield sse({"type": "log", "message": f"✓ Cache hit: {label}  ({len(cached)} result(s))"})
                all_flights.extend(cached)
                continue

            yield sse({"type": "log", "message": f"⟳ Fetching live data: {label}"})

            def do_fetch(o=origin, d=dest):
                return fetch_flights(
                    origin=o, destination=d,
                    outbound_date=outbound_date, return_date=return_date,
                    currency="EUR", hl="en", gl="us",
                    max_stops=max_stops,
                )

            flights = await loop.run_in_executor(None, do_fetch)

            if use_cache and flights:
                set_cached(cache, origin, dest, outbound_date, return_date, flights)
                await loop.run_in_executor(None, save_cache, cache, cache_file)

            all_flights.extend(flights)
            yield sse({"type": "log", "message": f"✓ Found {len(flights)} flight(s) for {label}"})

        if not all_flights:
            yield sse({"type": "error", "message": "No flights found. Please check your parameters and API key."})
            return

        yield sse({"type": "progress", "percent": 65, "label": "Calculating scores…"})
        df = await loop.run_in_executor(
            None,
            lambda: calculate_scores(all_flights, value_of_time=value_of_time),
        )
        df = await loop.run_in_executor(
            None,
            lambda: apply_filters(df, max_stops=max_stops),
        )
        df = df.reset_index(drop=True)

        yield sse({"type": "log", "message": f"Scored {len(df)} flights, fetching return leg details for top {top_n}…"})
        yield sse({"type": "progress", "percent": 70, "label": "Fetching return leg details…"})

        top_flights = df.head(top_n).to_dict("records")

        for rank_idx, flight in enumerate(top_flights):
            token = flight.get("departure_token", "")
            if not token:
                continue
            yield sse({
                "type": "progress",
                "percent": 70 + int((rank_idx / max(top_n, 1)) * 25),
                "label": f"Return leg for #{rank_idx + 1}: {flight.get('outbound_route', '?')}…",
            })

            from flight_optimizer.cache import get_cached_return, set_cached_return

            cached_ret = get_cached_return(cache, token) if use_cache else None
            if cached_ret:
                flight.update(cached_ret)
                top_flights[rank_idx] = flight
                yield sse({"type": "log", "message": f"✓ Return leg #{rank_idx + 1} from cache"})
                continue

            from flight_optimizer.serpapi_client import fetch_return_legs

            def do_return(t=token, f=flight):
                return fetch_return_legs(
                    departure_token=t,
                    origin=f["origin"], destination=f["destination"],
                    outbound_date=f["outbound_date"], return_date=f["return_date"],
                    currency="EUR", hl="en", gl="us",
                )

            ret = await loop.run_in_executor(None, do_return)
            if ret:
                flight.update(ret)
                top_flights[rank_idx] = flight
                if use_cache:
                    set_cached_return(cache, token, ret)
                    await loop.run_in_executor(None, save_cache, cache, cache_file)
                yield sse({"type": "log", "message": f"✓ Return leg #{rank_idx + 1} fetched"})

            await asyncio.sleep(1.0)

        yield sse({"type": "progress", "percent": 97, "label": "Preparing results…"})

        results_out = []
        for rank_idx, f in enumerate(top_flights):
            results_out.append({
                "rank": rank_idx + 1,
                "score": round(f.get("score", 0), 2),
                "price": f.get("price", 0),
                "airline": f.get("airline", ""),
                "origin": f.get("origin", ""),
                "destination": f.get("destination", ""),
                "outbound_date": f.get("outbound_date", ""),
                "return_date": f.get("return_date", ""),
                "outbound_route": f.get("outbound_route", ""),
                "return_route": f.get("return_route", ""),
                "duration_str": f.get("duration_str", ""),
                "stops": f.get("stops", 0),
                "return_stops": int(f.get("return_stops", 0)) if f.get("return_stops") is not None else None,
                "return_duration_minutes": f.get("return_duration_minutes"),
                "outbound_segments": f.get("outbound_segments") or [],
                "outbound_layovers": f.get("outbound_layovers") or [],
                "return_segments": f.get("return_segments") or [],
                "return_layovers": f.get("return_layovers") or [],
            })

        import tempfile, uuid
        tmp_id = str(uuid.uuid4())[:8]
        tmp_path = os.path.join(tempfile.gettempdir(), f"flight_results_{tmp_id}.xlsx")
        final_df = pd.DataFrame(top_flights + df.iloc[top_n:].to_dict("records"))
        await loop.run_in_executor(None, lambda: export_to_excel(final_df, tmp_path))

        yield sse({
            "type": "results",
            "flights": results_out,
            "total_found": len(df),
            "export_id": tmp_id,
        })
        yield sse({"type": "progress", "percent": 100, "label": "Done!"})
        yield sse({"type": "done"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/export/{export_id}")
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
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
