# RouteBetter ✈️

**RouteBetter** finds the best round-trip flights using a transparent, personalised score that combines price, travel time, stops, and door-to-door ground transport — going well beyond traditional price-only flight searches.

---

## Features

- **Composite score** — ranks flights by `price + time × value-of-time + stop penalties + layover penalties + night-departure penalties + ground transport`
- **Interactive web UI** — real-time streaming results with detailed flight cards (airline, route, duration, stops, layovers)
- **Command-line interface** — batch processing with Excel export
- **Date window search** — automatically searches ±N days around your target dates
- **Ground transport** — optional door-to-door cost and time from home to departure airport, and from arrival airport to destination (geocoded via OpenStreetMap + AI routing)
- **SerpApi caching** — saves API quota by reusing previously fetched results
- **Excel export** — full ranked results saved to `flight_results.xlsx`

---

## Scoring Formula

> **Lower score = better value**

```
score = price
      + (outbound_hours + return_hours) × value_of_time
      + (outbound_stops + return_stops) × stop_penalty
      + night_departure_hours × value_of_time × 0.5     (if departure 00:00–06:00)
      + excess_layover_hours   × value_of_time × 0.5    (hours beyond 2 h threshold)
      + ground_transport_cost
      + ground_transport_time_hours × value_of_time
```

All penalty components are shown individually in the UI so you can see exactly what drives each score.

---

## Getting Started

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| pip | any recent |
| SerpApi account | [serpapi.com](https://serpapi.com) (free tier: 100 searches/month) |

### Installation

```bash
# 1. Clone the repo
git clone https://github.com/Stopferino/RouteBetter.git
cd RouteBetter

# 2. Install Python dependencies
pip install -r requirements.txt
```

### Set the API key

Set your SerpApi key as an environment variable:

```bash
export SERPAPI_KEY="your_serpapi_key_here"
```

On Replit, add `SERPAPI_KEY` as a secret in the Secrets panel.

---

## Usage

### Web UI (recommended)

Start the FastAPI server:

```bash
uvicorn flight_webapp.app:app --host 0.0.0.0 --port 8000 --reload
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

**Search form fields:**

| Field | Description |
|---|---|
| Origin airports | Comma-separated IATA codes (e.g. `HKG, SZX, CAN`) |
| Destination airports | Comma-separated IATA codes (e.g. `FRA, MUC, NUE`) |
| Outbound date | Target departure date |
| Return date | Target return date |
| Value of Time | EUR per hour of travel time (personalises the score) |
| Top N | Maximum results to display |
| Max stops | Leave blank for no limit; `0` for non-stop only |
| Date window | Search ±N days around each target date |
| Home address | Your home address (enables door-to-door ground transport cost) |
| Destination address | Address at your destination |
| Stop penalty | EUR penalty applied per stop (outbound + return) |

Results stream in real time as each flight is fetched and scored.

### Command-line interface

1. Edit [`flight_optimizer/config.py`](#configuration) to set your airports, dates, and preferences.
2. Run:

```bash
python run_optimizer.py
```

Top-ranked flights are printed to the console and the full results are saved to `flight_results.xlsx`.

---

## Configuration (`flight_optimizer/config.py`)

| Parameter | Description | Default |
|---|---|---|
| `ORIGIN_AIRPORTS` | Departure airport IATA codes | `["HKG", "SZX", "CAN"]` |
| `DESTINATION_AIRPORTS` | Arrival airport IATA codes | `["FRA", "MUC", "NUE"]` |
| `OUTBOUND_DATE` | Desired outbound date (`YYYY-MM-DD`) | `"2026-07-25"` |
| `RETURN_DATE` | Desired return date (`YYYY-MM-DD`) | `"2026-08-02"` |
| `DATE_WINDOW_DAYS` | ±days around each target date to search | `0` |
| `VALUE_OF_TIME_EUR_PER_HOUR` | How much one hour of travel time is worth to you (€/h) | `20.0` |
| `AIRLINE_FILTER` | Airline whitelist — empty list means all airlines | `[]` |
| `MAX_STOPS` | Maximum stops (`None` = no limit, `0` = non-stop only) | `None` |
| `USE_CACHE` | Load previously fetched results to save API quota | `True` |
| `CACHE_FILE` | Path to the JSON cache file | `"flight_cache.json"` |
| `TOP_N` | Number of top results to display in the CLI | `5` |
| `EXCEL_OUTPUT_FILE` | Output filename for the Excel export | `"flight_results.xlsx"` |
| `CURRENCY` | Currency for SerpApi (ISO 4217) | `"EUR"` |
| `HL` / `GL` | Language / country for SerpApi results | `"en"` / `"us"` |

---

## Project Structure

```
RouteBetter/
├── flight_optimizer/          # Core flight optimization engine
│   ├── config.py              # All configurable parameters
│   ├── main.py                # CLI workflow (fetch → score → print → export)
│   ├── serpapi_client.py      # Google Flights data via SerpApi
│   ├── scorer.py              # Score calculation with all penalty components
│   ├── exporter.py            # Excel export (openpyxl)
│   ├── printer.py             # Console output formatting
│   ├── date_utils.py          # Date window helpers
│   ├── cache.py               # JSON-based flight result caching
│   ├── ground_transport.py    # Door-to-door cost/time (Nominatim + OSRM + AI)
│   └── usage_tracker.py       # SerpApi monthly quota tracking
├── flight_webapp/             # FastAPI web application
│   ├── app.py                 # API backend (SSE streaming, /search/stream)
│   └── templates/
│       └── index.html         # Alpine.js + Tailwind CSS single-page UI
├── run_optimizer.py           # CLI entry point
├── requirements.txt           # Python dependencies
└── flight_cache.json          # Cached flight data (auto-generated)
```

---

## Ground Transport

When you provide a **home address** and a **destination address**, RouteBetter estimates the time and cost of getting from your home to the departure airport, and from the arrival airport to your final destination. This is added to the flight score so you always compare on a true door-to-door basis.

Routing uses:
1. **Nominatim (OpenStreetMap)** — free geocoding, no API key required
2. **AI-powered routing** (via Replit AI proxy, optional) — contextual transport mode selection (metro, bus, taxi, etc.)
3. **OSRM** — fallback raw driving distance calculation

Results are cached in `ground_transport_cache.json` so the same address pair is only looked up once.

---

## API Quota

RouteBetter uses [SerpApi](https://serpapi.com) to fetch Google Flights data. The free plan includes **100 searches per month**.

- Each origin × destination × date combination counts as one search.
- Enable `USE_CACHE = True` (default) to avoid re-fetching data you already have.
- The web UI displays your current monthly usage at the bottom of the page.

---

## Dependencies

**Python:**

| Package | Purpose |
|---|---|
| `fastapi` | Web framework |
| `uvicorn` | ASGI server |
| `requests` | HTTP client for SerpApi |
| `pandas` | Data manipulation and scoring |
| `openpyxl` | Excel export |

---

## License

This project is open source. See [LICENSE](LICENSE) for details.
