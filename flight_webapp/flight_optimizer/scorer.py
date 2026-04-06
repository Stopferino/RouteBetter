"""
Flight Optimizer - Score Calculation

Score = Price
      + (Total round-trip flight hours) × VoT
      + Total stops × stop_penalty_eur
      + Night departure flag × flight_hours × VoT × night_vot_factor
      + Excess layover hours (beyond threshold) × VoT × layover_vot_factor
      + Ground transport cost & time (applied in app.py after this module)

Lower score = better value.
"""

import re
import pandas as pd
from typing import Optional

_DE_AIRPORTS: frozenset = frozenset({
    "FRA", "MUC", "NUE", "DUS", "HAM", "BER", "TXL", "STR", "CGN",
    "HAJ", "LEJ", "DRS", "HHN", "FKB", "PAD", "ERF", "FDH", "SCN",
    "DTM", "KSF", "GWT", "FMO", "NRN", "LBC", "RLG", "QFB", "ZQW",
    "SXF", "THF",
})


def _count_de_domestic(segments) -> int:
    if not isinstance(segments, list):
        return 0
    return sum(
        1 for s in segments
        if isinstance(s, dict)
        and s.get("from_airport") in _DE_AIRPORTS
        and s.get("to_airport") in _DE_AIRPORTS
    )


def _parse_dep_hour(segments: list) -> float | None:
    """Extract departure hour (0.0–23.99) from the first segment's from_time.
    Handles SerpApi time strings like '11:55 PM', '1:15 AM'.
    Returns None if unparseable.
    """
    if not isinstance(segments, list) or not segments:
        return None
    first = segments[0]
    if not isinstance(first, dict):
        return None
    time_str = str(first.get("from_time") or "")
    if not time_str:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)", time_str.upper())
    if not m:
        return None
    h = int(m.group(1)) % 12          # 12:xx AM → 0, 12:xx PM → 12
    if m.group(3) == "PM":
        h += 12
    return h + int(m.group(2)) / 60.0


def _excess_layover_hours(layovers: list, threshold_h: float = 2.0) -> float:
    """Sum of layover hours beyond threshold_h across all layovers in the list."""
    if not isinstance(layovers, list):
        return 0.0
    total = 0.0
    for lay in layovers:
        if not isinstance(lay, dict):
            continue
        dur_h = float(lay.get("duration_minutes") or 0) / 60.0
        if dur_h > threshold_h:
            total += dur_h - threshold_h
    return total


def calculate_scores(
    flights: list[dict],
    value_of_time: float = 50.0,
) -> pd.DataFrame:
    """
    Preliminary score using outbound duration only (return not yet fetched).
    Used for initial ranking to select candidates for the return-leg API call.

    Score formula (preliminary):
        score = price + outbound_hours × value_of_time

    Returns a DataFrame sorted by score ascending.
    """
    if not flights:
        return pd.DataFrame()

    df = pd.DataFrame(flights)
    df["duration_hours"] = df["duration_minutes"] / 60.0
    df["score"] = df["price"] + df["duration_hours"] * value_of_time
    df["duration_str"] = df["duration_minutes"].apply(_format_duration)
    df["score_rounded"] = df["score"].round(2)
    df = df.sort_values("score").reset_index(drop=True)
    return df


def recalculate_scores_with_return(
    flights: list[dict],
    value_of_time: float,
    stop_penalty_eur: float = 75.0,
    night_vot_factor: float = 0.5,    # extra VoT fraction for night departures
    layover_threshold_h: float = 2.0,  # hours before excess layover kicks in
    layover_vot_factor: float = 0.5,   # extra VoT fraction per excess layover hour
) -> list[dict]:
    """
    Final score using full round-trip data + contextual penalties.

    Penalties (all transparent and shown in UI):
      - Stop penalty:   (outbound_stops + return_stops) × stop_penalty_eur
      - Night penalty:  if departure between 00:00–06:00,
                        leg_hours × VoT × night_vot_factor (50% extra by default)
      - Layover penalty: excess hours beyond layover_threshold_h × VoT × layover_vot_factor

    Each penalty component is stored on the flight dict for UI display.
    Returns the list sorted by final score ascending.
    """
    for f in flights:
        outbound_min = float(f.get("duration_minutes") or 0)
        return_min   = float(f.get("return_duration_minutes") or 0)
        outbound_h   = outbound_min / 60.0
        return_h     = return_min / 60.0

        # ── Base time cost ────────────────────────────────────────────────────
        time_cost_base = (outbound_h + return_h) * value_of_time

        # ── Night departure penalty ───────────────────────────────────────────
        out_dep_h = _parse_dep_hour(f.get("outbound_segments") or [])
        ret_dep_h = _parse_dep_hour(f.get("return_segments") or [])
        night_penalty = 0.0
        out_is_night = out_dep_h is not None and 0.0 <= out_dep_h < 6.0
        ret_is_night = ret_dep_h is not None and 0.0 <= ret_dep_h < 6.0
        if out_is_night:
            night_penalty += outbound_h * value_of_time * night_vot_factor
        if ret_is_night:
            night_penalty += return_h * value_of_time * night_vot_factor

        # ── Layover penalty ───────────────────────────────────────────────────
        out_excess_h = _excess_layover_hours(
            f.get("outbound_layovers") or [], layover_threshold_h
        )
        ret_excess_h = _excess_layover_hours(
            f.get("return_layovers") or [], layover_threshold_h
        )
        layover_penalty = (out_excess_h + ret_excess_h) * value_of_time * layover_vot_factor

        # ── Stops penalty ─────────────────────────────────────────────────────
        out_stops = int(f.get("stops") or 0)
        ret_stops_raw = f.get("return_stops")
        try:
            ret_stops = int(ret_stops_raw) if ret_stops_raw is not None and str(ret_stops_raw) not in ("nan", "None") else 0
        except (ValueError, TypeError):
            ret_stops = 0
        stops_penalty = (out_stops + ret_stops) * stop_penalty_eur

        # ── Total score ───────────────────────────────────────────────────────
        f["score"]          = round(float(f.get("price") or 0) + time_cost_base + night_penalty + layover_penalty + stops_penalty, 2)
        f["time_cost_base"] = round(time_cost_base, 2)
        f["night_penalty"]  = round(night_penalty, 2)
        f["layover_penalty"]= round(layover_penalty, 2)
        f["stops_penalty"]  = round(stops_penalty, 2)
        f["out_is_night"]   = out_is_night
        f["ret_is_night"]   = ret_is_night
        # Raw VoT-independent fields — used for client-side re-scoring
        out_night_h = outbound_h if out_is_night else 0.0
        ret_night_h = return_h   if ret_is_night else 0.0
        f["total_flight_h"]   = round(outbound_h + return_h, 4)
        f["night_hours"]      = round(out_night_h + ret_night_h, 4)
        f["excess_layover_h"] = round(out_excess_h + ret_excess_h, 4)

    flights.sort(key=lambda f: f["score"])
    return flights


def get_top_n(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    return df.head(n).copy()


def _format_duration(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h}h {m:02d}m"


def apply_filters(
    df: pd.DataFrame,
    airline_filter: Optional[list[str]] = None,
    max_stops: Optional[int] = None,
    max_de_domestic: int = 1,
) -> pd.DataFrame:
    if airline_filter:
        pattern = "|".join(airline_filter)
        df = df[df["airline"].str.contains(pattern, case=False, na=False)]

    if max_stops is not None:
        df = df[df["stops"] <= max_stops]

    if max_de_domestic is not None and "outbound_segments" in df.columns:
        df = df[
            df["outbound_segments"].apply(
                lambda segs: _count_de_domestic(segs) <= max_de_domestic
            )
        ]

    return df.reset_index(drop=True)
