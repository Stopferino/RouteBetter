"""
Flight Optimizer - Console Output
"""

import pandas as pd


def print_top_flights(df: pd.DataFrame, top_n: int = 5, value_of_time: float = 50.0):
    """
    Prints the top-N flights formatted to the console.
    """
    if df.empty:
        print("\n  No flights found. Please check your configuration.")
        return

    print("\n" + "=" * 70)
    print(f"  TOP {min(top_n, len(df))} FLIGHTS BY SCORE")
    print(f"  (Score = Price + Duration in h x {value_of_time:.0f} EUR/h Value-of-Time)")
    print("=" * 70)

    for i, row in df.head(top_n).iterrows():
        rank = i + 1
        print(f"\n  [{rank}]  {row['origin']} -> {row['destination']}")
        print(f"       Outbound:   {row['outbound_date']}  |  Return: {row['return_date']}")
        print(f"       Airline:    {row['airline']}  ({row['stops']} stop(s))")
        print(f"       Price:      {row['price']:.2f} EUR")
        print(f"       Duration:   {row['duration_str']}  ({row['duration_hours']:.1f} h)")
        print(f"       > Score:    {row['score']:.2f} EUR")
        print("       " + "-" * 50)

    print("\n" + "=" * 70)
    print(f"  Total flights found: {len(df)}")
    print("=" * 70 + "\n")


def print_summary_table(df: pd.DataFrame, top_n: int = 5):
    """
    Prints a compact table of the top-N flights for a quick overview.
    """
    if df.empty:
        return

    top = df.head(top_n).copy()
    top.insert(0, "Rank", range(1, len(top) + 1))

    display_cols = {
        "Rank": "Rank",
        "origin": "From",
        "destination": "To",
        "outbound_date": "Outbound",
        "return_date": "Return",
        "airline": "Airline",
        "stops": "Stops",
        "price": "Price EUR",
        "duration_str": "Duration",
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
