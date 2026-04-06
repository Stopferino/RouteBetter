"""
Flight Optimizer - Excel Export
"""

import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

EXPORT_COLUMNS = [
    "rank",
    "score_rounded",
    "price",
    "outbound_route",
    "return_route",
    "duration_str",
    "duration_hours",
    "airline",
    "stops",
    "return_stops",
    "origin",
    "destination",
    "outbound_date",
    "return_date",
]

COLUMN_LABELS = {
    "rank": "Rank",
    "score_rounded": "Score (EUR)",
    "price": "Price EUR (round-trip)",
    "outbound_route": "Outbound Route",
    "return_route": "Return Route",
    "duration_str": "Outbound Duration",
    "duration_hours": "Outbound Duration (h)",
    "airline": "Airline",
    "stops": "Outbound Stops",
    "return_stops": "Return Stops",
    "origin": "Origin",
    "destination": "Destination",
    "outbound_date": "Outbound Date",
    "return_date": "Return Date",
}


def _fmt(minutes) -> str:
    minutes = int(minutes)
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _build_leg_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Builds a flat table where every flight segment (outbound AND return) is one row.
    """
    rows = []
    for _, row in df.iterrows():
        rank = row.get("rank", "")
        price = row.get("price", "")
        score = round(row.get("score", 0), 2)
        origin = row.get("origin", "")
        destination = row.get("destination", "")
        out_date = row.get("outbound_date", "")
        ret_date = row.get("return_date", "")

        for direction, seg_key, lay_key in (
            ("Outbound", "outbound_segments", "outbound_layovers"),
            ("Return",   "return_segments",   "return_layovers"),
        ):
            raw_segs = row.get(seg_key)
            raw_lays = row.get(lay_key)
            # Guard against NaN (float) stored in DataFrame cells
            segments = raw_segs if isinstance(raw_segs, list) else []
            layovers = raw_lays if isinstance(raw_lays, list) else []
            if not segments:
                continue
            for idx, seg in enumerate(segments):
                overnight = "Yes" if seg.get("overnight") else "No"
                rows.append({
                    "Rank": rank,
                    "Score (EUR)": score,
                    "Price EUR (round-trip)": price,
                    "Origin": origin,
                    "Destination": destination,
                    "Outbound Date": out_date,
                    "Return Date": ret_date,
                    "Direction": direction,
                    "Leg #": idx + 1,
                    "From": seg["from_airport"],
                    "Departure Time": seg.get("from_time", ""),
                    "To": seg["to_airport"],
                    "Arrival Time": seg.get("to_time", ""),
                    "Flight Number": seg.get("flight_number", ""),
                    "Airline": seg.get("airline", ""),
                    "Aircraft": seg.get("aircraft", ""),
                    "Leg Duration": _fmt(seg["duration_minutes"]),
                    "Overnight": overnight,
                    "Layover After (airport)": layovers[idx]["airport_id"] if idx < len(layovers) else "",
                    "Layover After (duration)": _fmt(layovers[idx]["duration_minutes"]) if idx < len(layovers) else "",
                    "Layover Overnight": "Yes" if idx < len(layovers) and layovers[idx].get("overnight") else "",
                })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def export_to_excel(df: pd.DataFrame, output_path: str = "flight_results.xlsx") -> str:
    """
    Exports results to an Excel file with three sheets:
      - "Top 5"      : Summary of the best 5 flights
      - "All Flights": Full list sorted by score
      - "Leg Detail" : One row per flight segment (outbound + return)
    """
    if df.empty:
        logger.warning("No data to export.")
        return ""

    df = df.copy()
    df.insert(0, "rank", range(1, len(df) + 1))

    # ── Summary sheet ──────────────────────────────────────────────────────────
    cols_available = [c for c in EXPORT_COLUMNS if c in df.columns]
    export_df = df[cols_available].rename(columns=COLUMN_LABELS)
    top5_df = export_df.head(5)

    # ── Leg detail sheet (outbound + return segments) ─────────────────────────
    detail_df = _build_leg_rows(df)

    output_path = Path(output_path)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        top5_df.to_excel(writer, sheet_name="Top 5", index=False)
        _autofit_columns(writer.sheets["Top 5"], top5_df)

        export_df.to_excel(writer, sheet_name="All Flights", index=False)
        _autofit_columns(writer.sheets["All Flights"], export_df)

        if not detail_df.empty:
            detail_df.to_excel(writer, sheet_name="Leg Detail", index=False)
            _autofit_columns(writer.sheets["Leg Detail"], detail_df)

    abs_path = str(output_path.resolve())
    logger.info(f"Excel file saved: {abs_path}")
    return abs_path


def _autofit_columns(worksheet, df: pd.DataFrame):
    """Auto-fits column widths to content."""
    for idx, col in enumerate(df.columns, 1):
        cell_lengths = df.iloc[:, idx - 1].apply(lambda x: len(str(x))) if not df.empty else []
        max_len = max(len(str(col)), int(cell_lengths.max()) if len(cell_lengths) else 0)
        col_letter = worksheet.cell(row=1, column=idx).column_letter
        worksheet.column_dimensions[col_letter].width = min(max_len + 4, 55)
