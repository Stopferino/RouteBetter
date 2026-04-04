"""
Flight Optimizer - Score Calculation
Score = Price + (Total round-trip duration in hours * Value of Time)
"""

import pandas as pd
from typing import Optional


def calculate_scores(
    flights: list[dict],
    value_of_time: float = 50.0,
) -> pd.DataFrame:
    """
    Calculates a preliminary score using outbound duration only (return duration
    is not yet available at this stage). Used for initial ranking to pick candidates
    for the return-leg API call.

    Score formula (preliminary):
        score = price + (outbound_duration_hours * value_of_time)

    Returns:
        DataFrame with all fields + 'duration_hours' + 'score', sorted by score ascending
    """
    if not flights:
        return pd.DataFrame()

    df = pd.DataFrame(flights)

    # Convert outbound duration to hours
    df["duration_hours"] = df["duration_minutes"] / 60.0

    # Preliminary score (outbound only — will be refined after return leg fetch)
    df["score"] = df["price"] + (df["duration_hours"] * value_of_time)

    # Helper columns for readable display
    df["duration_str"] = df["duration_minutes"].apply(_format_duration)
    df["score_rounded"] = df["score"].round(2)

    # Sort by preliminary score ascending
    df = df.sort_values("score").reset_index(drop=True)

    return df


def recalculate_scores_with_return(
    flights: list[dict],
    value_of_time: float,
) -> list[dict]:
    """
    Re-calculates the score using total round-trip duration (outbound + return)
    for flights that have return_duration_minutes populated.
    Flights without return data fall back to outbound-only score.

    Score formula (final):
        score = price + ((outbound_minutes + return_minutes) / 60) * value_of_time

    Returns the list sorted by final score ascending.
    """
    for f in flights:
        outbound_min = float(f.get("duration_minutes") or 0)
        return_min = float(f.get("return_duration_minutes") or 0)
        total_h = (outbound_min + return_min) / 60.0
        f["score"] = round(f["price"] + total_h * value_of_time, 2)

    flights.sort(key=lambda f: f["score"])
    return flights


def get_top_n(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Returns the top-N flights with the lowest score."""
    return df.head(n).copy()


def _format_duration(minutes: int) -> str:
    """Formats minutes as 'Xh Ym'."""
    h = minutes // 60
    m = minutes % 60
    return f"{h}h {m:02d}m"


def apply_filters(
    df: pd.DataFrame,
    airline_filter: Optional[list[str]] = None,
    max_stops: Optional[int] = None,
) -> pd.DataFrame:
    """
    Optional post-fetch filtering (can also be applied during the API call).
    Kept here for easy future extension.

    Args:
        df: Full results DataFrame
        airline_filter: List of airline names (substring match)
        max_stops: Maximum number of stops

    Returns:
        Filtered DataFrame
    """
    if airline_filter:
        pattern = "|".join(airline_filter)
        df = df[df["airline"].str.contains(pattern, case=False, na=False)]

    if max_stops is not None:
        df = df[df["stops"] <= max_stops]

    return df.reset_index(drop=True)
