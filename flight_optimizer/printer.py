"""
Flight Optimizer - Console Output
"""

import pandas as pd


def _fmt(minutes: int) -> str:
    """Format minutes as Xh Ym."""
    return f"{minutes // 60}h {minutes % 60:02d}m"


def print_top_flights(df: pd.DataFrame, top_n: int = 5, value_of_time: float = 50.0):
    """Prints the top-N flights with full outbound segment detail."""
    if df.empty:
        print("\n  No flights found. Please check your configuration.")
        return

    print("\n" + "=" * 72)
    print(f"  TOP {min(top_n, len(df))} FLIGHTS BY SCORE")
    print(f"  Score = Price + Outbound duration (h) x {value_of_time:.0f} EUR/h Value-of-Time")
    print("=" * 72)

    for i, row in df.head(top_n).iterrows():
        rank = i + 1
        segments = row.get("outbound_segments") or []
        layovers = row.get("outbound_layovers") or []

        route = row.get("outbound_route") or f"{row['origin']}->{row['destination']}"
        print(f"\n  [{rank}]  {route}  "
              f"| {row['airline']}  |  {row['stops']} stop(s)  |  {row['duration_str']}")
        print(f"       Outbound date: {row['outbound_date']}   Return date: {row['return_date']}")
        print(f"       Price:  {row['price']:.2f} EUR (round-trip)   "
              f"Score:  {row['score']:.2f} EUR")

        # ── Outbound leg detail ────────────────────────────────────────────
        if segments:
            print()
            print("       OUTBOUND LEG:")
            for idx, seg in enumerate(segments):
                overnight = "  [overnight]" if seg.get("overnight") else ""
                print(f"         {seg['from_airport']} {seg['from_time'][-5:] if seg['from_time'] else '?'}"
                      f"  ->  {seg['to_airport']} {seg['to_time'][-5:] if seg['to_time'] else '?'}"
                      f"  |  {seg['flight_number']}  {seg['airline']}"
                      f"  |  {_fmt(seg['duration_minutes'])}"
                      f"  |  {seg['aircraft']}{overnight}")
                # Layover after this segment (if not the last segment)
                if idx < len(layovers):
                    lay = layovers[idx]
                    print(f"             [ Layover: {lay['airport_id']}  {lay['airport']}  "
                          f"{_fmt(lay['duration_minutes'])} ]")
        else:
            print(f"\n       OUTBOUND LEG: {row['origin']} -> {row['destination']}  "
                  f"| {_fmt(row['duration_minutes'])}  | {row['stops']} stop(s)")

        # ── Return leg note ────────────────────────────────────────────────
        print()
        print(f"       RETURN LEG:   {row['destination']} -> {row['origin']}  "
              f"on {row['return_date']}  (included in price — select on Google Flights)")
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
        "outbound_date": "Outbound",
        "return_date": "Return",
        "airline": "Airline",
        "stops": "Stops",
        "price": "Price EUR",
        "duration_str": "Out.Duration",
        "score": "Score EUR",
    }

    available = {k: v for k, v in display_cols.items() if k in top.columns}
    # Fallback if outbound_route not present (old cache entries)
    if "outbound_route" not in top.columns:
        display_cols.pop("outbound_route")
        available = {k: v for k, v in display_cols.items() if k in top.columns}

    table = top[list(available.keys())].rename(columns=available)

    if "Price EUR" in table.columns:
        table["Price EUR"] = table["Price EUR"].map(lambda x: f"{x:.2f}")
    if "Score EUR" in table.columns:
        table["Score EUR"] = table["Score EUR"].map(lambda x: f"{x:.2f}")

    print("\n" + table.to_string(index=False))
    print()
