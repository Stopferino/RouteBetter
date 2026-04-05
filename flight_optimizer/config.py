"""
Flight Optimizer - Configuration
Adjust all parameters here.
"""

# ─── Airports ─────────────────────────────────────────────────────────────────
ORIGIN_AIRPORTS = ["HKG", "SZX", "CAN"]
DESTINATION_AIRPORTS = ["FRA", "MUC", "NUE"]

# ─── Travel Dates ─────────────────────────────────────────────────────────────
# Desired outbound date (YYYY-MM-DD) — must be in the future!
OUTBOUND_DATE = "2026-07-25"
# Desired return date (YYYY-MM-DD) — must be after the outbound date!
RETURN_DATE = "2026-08-02"

# Date window: +/- days around the desired date (0 = exact date only)
DATE_WINDOW_DAYS = 0

# ─── Score Calculation ────────────────────────────────────────────────────────
# Value of Time (EUR per hour) — how much is one hour of travel time worth to you?
VALUE_OF_TIME_EUR_PER_HOUR = 20.0

# ─── Optional Filters (empty = no filter) ────────────────────────────────────
# Example: ["Lufthansa", "Cathay Pacific"]
AIRLINE_FILTER = []

# Maximum number of stops (None = no limit, 0 = non-stop only)
MAX_STOPS = None

# ─── Cache ────────────────────────────────────────────────────────────────────
# True = load previously fetched results from file, saves API quota
USE_CACHE = True
CACHE_FILE = "flight_cache.json"

# ─── Output ───────────────────────────────────────────────────────────────────
TOP_N = 5
EXCEL_OUTPUT_FILE = "flight_results.xlsx"

# ─── Currency ─────────────────────────────────────────────────────────────────
# Currency for SerpApi (ISO 4217)
CURRENCY = "EUR"

# ─── Language / Region ────────────────────────────────────────────────────────
# hl = language, gl = country
HL = "en"
GL = "us"
