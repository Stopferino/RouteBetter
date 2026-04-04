"""
Flight Optimizer - Console Output
"""

import pandas as pd


def _fmt(minutes: int) -> str:
    """Format minutes as Xh Ym."""
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _print_segments(segments: list, layovers: list, label: str):
    """Shared helper: prints leg segments and layovers."""
    print(f"\n       {label}:")
    for idx, seg in enumerate(segments):
        overnight = "  [overnight]" if seg.get("overnight") else ""
        dep_t = seg["from_time"][-5:] if seg.get("from_time") else "?"
        arr_t = seg["to_time"][-5:] if seg.get("to_time") else "?"
        print(
            f"         {seg['from_airport']} {dep_t}"
            f"  ->  {seg['to_airport']} {arr_t}"
            f"  |  {seg['flight_number']}  {seg['airline']}"
            f"  |  {_fmt(seg['duration_minutes'])}"
            f"  |  {seg['aircraft']}{overnight}"
        )
        if idx < len(layovers):
            lay = layovers[idx]
            overnight_lay = "  [overnight]" if lay.get("overnight") else ""
            print(
                f"             [ Layover: {lay['airport_id']}  {lay['airport']}"
                f"  {_fmt(lay['duration_minutes'])}{overnight_lay} ]"
            )


def print_top_flights(df: pd.DataFrame, top_n: int = 5, value_of_time: float = 50.0):
    """Prints the top-N flights with full outbound and return segment detail."""
    if df.empty:
        print("\n  No flights found. Please check your configuration.")
        return

    print("\n" + "=" * 72)
    print(f"  TOP {min(top_n, len(df))} FLIGHTS BY SCORE")
    print(f"  Score = Price + Outbound duration (h) x {value_of_time:.0f} EUR/h Value-of-Time")
    print("=" * 72)

    for i, row in df.head(top_n).iterrows():
        rank = i + 1
        out_segments = row.get("outbound_segments") or []
        out_layovers = row.get("outbound_layovers") or []
        ret_segments = row.get("return_segments") or []
        ret_layovers = row.get("return_layovers") or []

        route = row.get("outbound_route") or f"{row['origin']}->{row['destination']}"
        print(
            f"\n  [{rank}]  {route}"
            f"  |  {row['airline']}  |  {row['stops']} stop(s) outbound"
            f"  |  {row['duration_str']} outbound"
        )
        print(f"       Outbound date: {row['outbound_date']}   Return date: {row['return_date']}")
        print(
            f"       Price:  {row['price']:.2f} EUR (round-trip)   "
            f"Score:  {row['score']:.2f} EUR"
        )

        # ── Outbound leg detail ────────────────────────────────────────────
        if out_segments:
            _print_segments(out_segments, out_layovers, "OUTBOUND LEG")
        else:
            print(
                f"\n       OUTBOUND LEG: {row['origin']} -> {row['destination']}"
                f"  |  {_fmt(row['duration_minutes'])}  |  {row['stops']} stop(s)"
            )

        # ── Return leg detail ──────────────────────────────────────────────
        if ret_segments:
            ret_route = row.get("return_route") or f"{row['destination']}->{row['origin']}"
            ret_dur = row.get("return_duration_minutes")
            ret_stops = row.get("return_stops", len(ret_layovers))
            try:
                ret_stops = int(ret_stops)
            except (TypeError, ValueError):
                ret_stops = len(ret_layovers)
            ret_dur_str = f"  |  {_fmt(int(ret_dur))}" if ret_dur and str(ret_dur) != "nan" else ""
            print(
                f"\n       RETURN LEG:   {ret_route}"
                f"  |  {ret_stops} stop(s){ret_dur_str}"
            )
            _print_segments(ret_segments, ret_layovers, "  Segments")
        else:
            print(
                f"\n       RETURN LEG:   {row['destination']} -> {row['origin']}"
                f"  on {row['return_date']}  (details pending — not yet fetched)"
            )

        print("       " + "-" * 58)

    print("\n" + "=" * 72)
    print(f"  Total flights found: {len(df)}")
    print("=" * 72 + "\n")


def print_summary_table(df: pd.DataFrame, top_n: int = 5):
    """Prints a compact summary table of the top-N flights."""
    if df.empty:
        return

    top = df.head(top_n).copy()
    top.insert(0, "Rank", range(1, len(top) + 1))

    display_cols = {
        "Rank": "Rank",
        "outbound_route": "Route (Outbound)",
        "return_route": "Route (Return)",
        "outbound_date": "Outbound",
        "return_date": "Return",
        "airline": "Airline",
        "stops": "Out.Stops",
        "return_stops": "Ret.Stops",
        "price": "Price EUR",
        "duration_str": "Out.Duration",
        "score": "Score EUR",
    }

    available = {k: v for k, v in display_cols.items() if k in top.columns}
    table = top[list(available.keys())].rename(columns=available)

    if "Price EUR" in table.columns:
        table["Price EUR"] = table["Price EUR"].map(lambda x: f"{x:.2f}")
    if "Score EUR" in table.columns:
        table["Score EUR"] = table["Score EUR"].map(lambda x: f"{x:.2f}")

    print("\n" + table.to_string(index=False))
    print()
