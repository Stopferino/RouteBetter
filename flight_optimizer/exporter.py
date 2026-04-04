"""
Flight Optimizer - Excel-Export
"""

import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

# Spalten für den Excel-Export (ohne rohe flight_details)
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
    "rank": "Rang",
    "score_rounded": "Score (€)",
    "price": "Preis (€)",
    "duration_str": "Gesamtdauer",
    "duration_hours": "Dauer (h)",
    "airline": "Airline",
    "stops": "Stopps",
    "origin": "Abflughafen",
    "destination": "Zielflughafen",
    "outbound_date": "Hinflug-Datum",
    "return_date": "Rückflug-Datum",
}


def export_to_excel(df: pd.DataFrame, output_path: str = "flight_results.xlsx") -> str:
    """
    Exportiert das vollständige Ergebnis-DataFrame in eine Excel-Datei.

    Erstellt zwei Tabellenblätter:
      - "Top 5"        : Die fünf besten Flüge nach Score
      - "Alle Flüge"   : Alle gefundenen Flüge sortiert nach Score

    Args:
        df: Vollständiges DataFrame mit Score-Spalten
        output_path: Pfad der Ausgabedatei

    Returns:
        Absoluter Pfad der erzeugten Datei
    """
    if df.empty:
        logger.warning("Keine Daten zum Exportieren.")
        return ""

    # Rang-Spalte hinzufügen
    df = df.copy()
    df.insert(0, "rank", range(1, len(df) + 1))

    # Nur definierte Spalten, die tatsächlich vorhanden sind
    cols_available = [c for c in EXPORT_COLUMNS if c in df.columns]
    export_df = df[cols_available].rename(columns=COLUMN_LABELS)

    top5_df = export_df.head(5)

    output_path = Path(output_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # Tabellenblatt 1: Top 5
        top5_df.to_excel(writer, sheet_name="Top 5", index=False)
        _autofit_columns(writer.sheets["Top 5"], top5_df)

        # Tabellenblatt 2: Alle Flüge
        export_df.to_excel(writer, sheet_name="Alle Flüge", index=False)
        _autofit_columns(writer.sheets["Alle Flüge"], export_df)

    abs_path = str(output_path.resolve())
    logger.info(f"Excel-Export gespeichert: {abs_path}")
    return abs_path


def _autofit_columns(worksheet, df: pd.DataFrame):
    """Passt Spaltenbreiten automatisch an den Inhalt an."""
    for idx, col in enumerate(df.columns, 1):
        max_len = max(
            len(str(col)),
            df.iloc[:, idx - 1].astype(str).map(len).max() if not df.empty else 0,
        )
        # Openpyxl column_dimensions nutzt Buchstaben
        col_letter = worksheet.cell(row=1, column=idx).column_letter
        worksheet.column_dimensions[col_letter].width = min(max_len + 4, 50)
