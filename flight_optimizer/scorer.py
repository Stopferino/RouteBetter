"""
Flight Optimizer - Score Calculation
Score = Price + (Flight duration in hours * Value of Time)
"""

import pandas as pd
from typing import Optional


def calculate_scores(
    flights: list[dict],
    value_of_time: float = 50.0,
) -> pd.DataFrame:
    """
    Calculates a score for each flight and returns a sorted DataFrame.

    Score formula:
        score = price + (duration_hours * value_of_time)

    Args:
        flights: List of flight dictionaries (output of serpapi_client)
        value_of_time: Value of one hour of travel time in EUR

    Returns:
        DataFrame with all fields + 'duration_hours' + 'score', sorted by score ascending
    """
    if not flights:
        return pd.DataFrame()

    df = pd.DataFrame(flights)

    # Convert duration to hours
    df["duration_hours"] = df["duration_minutes"] / 60.0

    # Calculate score
    df["score"] = df["price"] + (df["duration_hours"] * value_of_time)

    # Helper columns for readable display
    df["duration_str"] = df["duration_minutes"].apply(_format_duration)
    df["score_rounded"] = df["score"].round(2)

    # Sort by score ascending (lowest score = best option)
    df = df.sort_values("score").reset_index(drop=True)

    return df


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
