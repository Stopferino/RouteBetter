"""
Flight Optimizer - Date Utility Functions
"""

from datetime import date, timedelta


def generate_date_range(base_date_str: str, window_days: int) -> list[str]:
    """
    Generates a list of date strings in YYYY-MM-DD format
    for the window [base_date - window_days, ..., base_date, ..., base_date + window_days].

    Args:
        base_date_str: Base date as string 'YYYY-MM-DD'
        window_days:   Number of days before and after the base date

    Returns:
        List of date strings, e.g. ['2026-06-14', '2026-06-15', '2026-06-16']
    """
    base = date.fromisoformat(base_date_str)
    dates = []
    for delta in range(-window_days, window_days + 1):
        dates.append((base + timedelta(days=delta)).isoformat())
    return dates
