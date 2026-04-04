"""
Flight Optimizer - Excel Export
"""

import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

# Columns for Excel export (excludes raw flight_details)
EXPORT_COLUMNS = [
    "rank",
    "score_rounded",
    "price",
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
    "price": "Price (EUR)",
    "duration_str": "Total Duration",
    "duration_hours": "Duration (h)",
    "airline": "Airline",
    "stops": "Stops",
    "origin": "Origin",
    "destination": "Destination",
    "outbound_date": "Outbound Date",
    "return_date": "Return Date",
}


def export_to_excel(df: pd.DataFrame, output_path: str = "flight_results.xlsx") -> str:
    """
    Exports the full results DataFrame to an Excel file.

    Creates two sheets:
      - "Top 5"      : The five best flights by score
      - "All Flights": All found flights sorted by score

    Args:
        df: Full DataFrame with score columns
        output_path: Output file path

    Returns:
        Absolute path of the created file
    """
    if df.empty:
        logger.warning("No data to export.")
        return ""

    # Add rank column
    df = df.copy()
    df.insert(0, "rank", range(1, len(df) + 1))

    # Only include defined columns that are actually present
    cols_available = [c for c in EXPORT_COLUMNS if c in df.columns]
    export_df = df[cols_available].rename(columns=COLUMN_LABELS)

    top5_df = export_df.head(5)

    output_path = Path(output_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # Sheet 1: Top 5
        top5_df.to_excel(writer, sheet_name="Top 5", index=False)
        _autofit_columns(writer.sheets["Top 5"], top5_df)

        # Sheet 2: All Flights
        export_df.to_excel(writer, sheet_name="All Flights", index=False)
        _autofit_columns(writer.sheets["All Flights"], export_df)

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
