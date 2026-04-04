"""
Flight Optimizer - Datums-Hilfsfunktionen
"""

from datetime import date, timedelta


def generate_date_range(base_date_str: str, window_days: int) -> list[str]:
    """
    Erzeugt eine Liste von Datumsstrings im Format YYYY-MM-DD
    für das Fenster [base_date - window_days, ..., base_date, ..., base_date + window_days].

    Args:
        base_date_str: Basisdatum als String 'YYYY-MM-DD'
        window_days:   Anzahl Tage vor und nach dem Basisdatum

    Returns:
        Liste von Datums-Strings, z.B. ['2025-06-14', '2025-06-15', '2025-06-16']
    """
    base = date.fromisoformat(base_date_str)
    dates = []
    for delta in range(-window_days, window_days + 1):
        dates.append((base + timedelta(days=delta)).isoformat())
    return dates
