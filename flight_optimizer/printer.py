"""
Flight Optimizer - Konsolenausgabe
"""

import pandas as pd


def print_top_flights(df: pd.DataFrame, top_n: int = 5, value_of_time: float = 50.0):
    """
    Gibt die Top-N Flüge formatiert auf der Konsole aus.
    """
    if df.empty:
        print("\n⚠  Keine Flüge gefunden. Bitte Konfiguration prüfen.")
        return

    print("\n" + "=" * 70)
    print(f"  ✈  TOP {min(top_n, len(df))} FLÜGE NACH SCORE")
    print(f"     (Score = Preis + Dauer in h × {value_of_time:.0f} €/h Value-of-Time)")
    print("=" * 70)

    for i, row in df.head(top_n).iterrows():
        rank = i + 1
        print(f"\n  [{rank}]  {row['origin']} → {row['destination']}")
        print(f"       Hinflug:    {row['outbound_date']}  |  Rückflug: {row['return_date']}")
        print(f"       Airline:    {row['airline']}  ({row['stops']} Stopp(s))")
        print(f"       Preis:      {row['price']:.2f} €")
        print(f"       Dauer:      {row['duration_str']}  ({row['duration_hours']:.1f} h)")
        print(f"       ► Score:    {row['score']:.2f} €")
        print("       " + "-" * 50)

    print("\n" + "=" * 70)
    print(f"  Gesamt gefundene Flüge: {len(df)}")
    print("=" * 70 + "\n")


def print_summary_table(df: pd.DataFrame, top_n: int = 5):
    """
    Gibt eine kompakte Tabelle der Top-N Flüge aus (für schnellen Überblick).
    """
    if df.empty:
        return

    top = df.head(top_n).copy()
    top.insert(0, "Rang", range(1, len(top) + 1))

    display_cols = {
        "Rang": "Rang",
        "origin": "Von",
        "destination": "Nach",
        "outbound_date": "Hin",
        "return_date": "Zurück",
        "airline": "Airline",
        "stops": "Stopps",
        "price": "Preis €",
        "duration_str": "Dauer",
        "score": "Score €",
    }

    available = {k: v for k, v in display_cols.items() if k in top.columns}
    table = top[list(available.keys())].rename(columns=available)

    # Runden für Lesbarkeit
    if "Preis €" in table.columns:
        table["Preis €"] = table["Preis €"].map(lambda x: f"{x:.2f}")
    if "Score €" in table.columns:
        table["Score €"] = table["Score €"].map(lambda x: f"{x:.2f}")

    print("\n" + table.to_string(index=False))
    print()
