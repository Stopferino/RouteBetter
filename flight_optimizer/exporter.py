"""
Flight Optimizer - Excel Export
"""

import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

# Summary columns for the Top-5 and All Flights sheets
EXPORT_COLUMNS = [
    "rank",
    "score_rounded",
    "price",
    "outbound_route",
    "duration_str",
    "duration_hours",
    "airline",
    "stops",
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
    "duration_str": "Outbound Duration",
    "duration_hours": "Outbound Duration (h)",
    "airline": "Airline",
    "stops": "Outbound Stops",
    "origin": "Origin",
    "destination": "Destination",
    "outbound_date": "Outbound Date",
    "return_date": "Return Date",
}


def _fmt(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _build_segments_text(row: pd.Series) -> str:
    """Builds a human-readable outbound segment breakdown for one row."""
    segments = row.get("outbound_segments") or []
    layovers = row.get("outbound_layovers") or []
    if not segments:
        return ""
    lines = []
    for idx, seg in enumerate(segments):
        overnight = " [overnight]" if seg.get("overnight") else ""
        dep_time = seg["from_time"][-5:] if seg.get("from_time") else "?"
        arr_time = seg["to_time"][-5:] if seg.get("to_time") else "?"
        lines.append(
            f"{seg['from_airport']} {dep_time} -> {seg['to_airport']} {arr_time}"
            f"  |  {seg['flight_number']}  {seg['airline']}"
            f"  |  {_fmt(seg['duration_minutes'])}  |  {seg['aircraft']}{overnight}"
        )
        if idx < len(layovers):
            lay = layovers[idx]
            lines.append(
                f"    Layover: {lay['airport_id']} ({lay['airport']})  {_fmt(lay['duration_minutes'])}"
            )
    return "\n".join(lines)


def export_to_excel(df: pd.DataFrame, output_path: str = "flight_results.xlsx") -> str:
    """
    Exports results to an Excel file with two sheets:
      - "Top 5"        : Summary of the 5 best flights
      - "All Flights"  : Full list sorted by score
      - "Outbound Detail": One row per flight segment (outbound only)
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

    # ── Outbound segment detail sheet ─────────────────────────────────────────
    segment_rows = []
    for _, row in df.iterrows():
        segments = row.get("outbound_segments") or []
        layovers = row.get("outbound_layovers") or []
        for idx, seg in enumerate(segments):
            segment_rows.append({
                "Rank": row["rank"],
                "Score (EUR)": round(row["score"], 2),
                "Price EUR (round-trip)": row["price"],
                "Origin": row["origin"],
                "Destination": row["destination"],
                "Outbound Date": row["outbound_date"],
                "Return Date": row["return_date"],
                "Leg #": idx + 1,
                "From": seg["from_airport"],
                "Departure Time": seg.get("from_time", ""),
                "To": seg["to_airport"],
                "Arrival Time": seg.get("to_time", ""),
                "Flight Number": seg.get("flight_number", ""),
                "Airline": seg.get("airline", ""),
                "Aircraft": seg.get("aircraft", ""),
                "Leg Duration": _fmt(seg["duration_minutes"]),
                "Overnight": "Yes" if seg.get("overnight") else "No",
                "Layover After (airport)": layovers[idx]["airport_id"] if idx < len(layovers) else "",
                "Layover After (duration)": _fmt(layovers[idx]["duration_minutes"]) if idx < len(layovers) else "",
            })
    detail_df = pd.DataFrame(segment_rows) if segment_rows else pd.DataFrame()

    output_path = Path(output_path)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        top5_df.to_excel(writer, sheet_name="Top 5", index=False)
        _autofit_columns(writer.sheets["Top 5"], top5_df)

        export_df.to_excel(writer, sheet_name="All Flights", index=False)
        _autofit_columns(writer.sheets["All Flights"], export_df)

        if not detail_df.empty:
            detail_df.to_excel(writer, sheet_name="Outbound Detail", index=False)
            _autofit_columns(writer.sheets["Outbound Detail"], detail_df)

    abs_path = str(output_path.resolve())
    logger.info(f"Excel file saved: {abs_path}")
    return abs_path


def _autofit_columns(worksheet, df: pd.DataFrame):
    """Auto-fits column widths to content."""
    for idx, col in enumerate(df.columns, 1):
        max_len = max(
            len(str(col)),
            df.iloc[:, idx - 1].astype(str).map(len).max() if not df.empty else 0,
        )
        col_letter = worksheet.cell(row=1, column=idx).column_letter
        worksheet.column_dimensions[col_letter].width = min(max_len + 4, 50)
