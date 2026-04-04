"""
Flight Optimizer - Score-Berechnung
Score = Preis + (Flugdauer in Stunden * Value of Time)
"""

import pandas as pd
from typing import Optional


def calculate_scores(
    flights: list[dict],
    value_of_time: float = 50.0,
) -> pd.DataFrame:
    """
    Berechnet den Score für jeden Flug und gibt ein DataFrame zurück.

    Score-Formel:
        score = price + (duration_hours * value_of_time)

    Args:
        flights: Liste von Flug-Dictionaries (Ausgabe von serpapi_client)
        value_of_time: Wert einer Reisestunde in EUR

    Returns:
        DataFrame mit allen Feldern + 'duration_hours' + 'score', sortiert nach Score
    """
    if not flights:
        return pd.DataFrame()

    df = pd.DataFrame(flights)

    # Dauer in Stunden umrechnen
    df["duration_hours"] = df["duration_minutes"] / 60.0

    # Score berechnen
    df["score"] = df["price"] + (df["duration_hours"] * value_of_time)

    # Hilfsspalten für lesbare Darstellung
    df["duration_str"] = df["duration_minutes"].apply(_format_duration)
    df["score_rounded"] = df["score"].round(2)

    # Sortieren nach Score (niedrigster Score = bestes Angebot)
    df = df.sort_values("score").reset_index(drop=True)

    return df


def get_top_n(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Gibt die Top-N Flüge (niedrigster Score) zurück."""
    return df.head(n).copy()


def _format_duration(minutes: int) -> str:
    """Formatiert Minuten als 'Xh Ym'."""
    h = minutes // 60
    m = minutes % 60
    return f"{h}h {m:02d}m"


def apply_filters(
    df: pd.DataFrame,
    airline_filter: Optional[list[str]] = None,
    max_stops: Optional[int] = None,
) -> pd.DataFrame:
    """
    Optionale Nachfilterung (kann auch schon im API-Abruf passieren).
    Wird hier für spätere Erweiterungen bereitgehalten.

    Args:
        df: Vollständiges DataFrame
        airline_filter: Liste von Airline-Namen (Teilstring-Match)
        max_stops: Maximale Anzahl Stopps

    Returns:
        Gefiltertes DataFrame
    """
    if airline_filter:
        pattern = "|".join(airline_filter)
        df = df[df["airline"].str.contains(pattern, case=False, na=False)]

    if max_stops is not None:
        df = df[df["stops"] <= max_stops]

    return df.reset_index(drop=True)
