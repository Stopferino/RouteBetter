"""
Flight Optimizer - Konfiguration
Hier kannst du alle Parameter einfach anpassen.
"""

# ─── Flughäfen ────────────────────────────────────────────────────────────────
ORIGIN_AIRPORTS = ["HKG", "SZX", "CAN"]
DESTINATION_AIRPORTS = ["FRA", "MUC", "NUE"]

# ─── Reisedaten ───────────────────────────────────────────────────────────────
# Gewünschtes Hinflugdatum (YYYY-MM-DD)
OUTBOUND_DATE = "2026-07-25"
# Gewünschtes Rückflugdatum (YYYY-MM-DD)
RETURN_DATE = "2026-08-02"

# Datumsfenster: +/- Tage um das Wunschdatum herum
DATE_WINDOW_DAYS = 0

# ─── Score-Berechnung ─────────────────────────────────────────────────────────
# Value of Time (€ pro Stunde) – wie viel ist dir eine Stunde Reisezeit wert?
VALUE_OF_TIME_EUR_PER_HOUR = 20.0

# ─── Optionale Filter (leer = kein Filter) ────────────────────────────────────
# Beispiel: ["Lufthansa", "Cathay Pacific"]
AIRLINE_FILTER = []

# Maximale Anzahl Stopps (None = keine Einschränkung, 0 = nur Direktflüge)
MAX_STOPS = None

# ─── Cache ────────────────────────────────────────────────────────────────────
# True = bereits abgerufene Anfragen aus Datei laden, spart API-Kontingent
USE_CACHE = True
CACHE_FILE = "flight_cache.json"

# ─── Ausgabe ──────────────────────────────────────────────────────────────────
TOP_N = 5
EXCEL_OUTPUT_FILE = "flight_results.xlsx"

# ─── Währung ──────────────────────────────────────────────────────────────────
# Währung für SerpApi (ISO 4217)
CURRENCY = "EUR"

# ─── Sprache / Region ─────────────────────────────────────────────────────────
# hl = Sprache, gl = Land
HL = "de"
GL = "de"
