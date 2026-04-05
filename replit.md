# Workspace

## Overview

pnpm workspace monorepo using TypeScript. Each package manages its own dependencies.

## Flight Optimizer

### Web App (UI)
Runs on port **8000** via the "Flight Optimizer Web App" workflow.
- Stack: Python FastAPI + Alpine.js + Tailwind CSS (CDN)
- Entry: `flight_webapp/app.py`
- Template: `flight_webapp/templates/index.html`
- Features: real-time SSE search progress, flight cards with full outbound + return leg detail, Excel export

### Command-line script

```bash
python run_optimizer.py
```

### Project structure

```
flight_optimizer/
├── config.py              ← Configuration (airports, dates, value-of-time, filters)
├── main.py                ← CLI entry point
├── serpapi_client.py      ← SerpApi Google Flights API client
├── scorer.py              ← Score calculation (price + duration × VoT + penalties)
├── exporter.py            ← Excel export (openpyxl)
├── printer.py             ← Console output formatting
├── date_utils.py          ← Date window helpers
├── cache.py               ← JSON-based flight result caching
├── ground_transport.py    ← Door-to-door ground transport cost/time
├── usage_tracker.py       ← SerpApi monthly quota tracking
└── requirements.txt       ← Python dependencies
run_optimizer.py           ← Root entry point script
```

### Configurable parameters (config.py)

| Parameter | Description | Default |
|---|---|---|
| `ORIGIN_AIRPORTS` | Departure airports (IATA codes) | HKG, SZX, CAN |
| `DESTINATION_AIRPORTS` | Arrival airports (IATA codes) | FRA, MUC, NUE |
| `OUTBOUND_DATE` | Desired outbound date | 2026-07-25 |
| `RETURN_DATE` | Desired return date | 2026-08-02 |
| `DATE_WINDOW_DAYS` | ±days around each target date | 0 |
| `VALUE_OF_TIME_EUR_PER_HOUR` | Value of time (€/h) | 20.0 |
| `AIRLINE_FILTER` | Airline whitelist (empty = all airlines) | [] |
| `MAX_STOPS` | Max stops (None = no limit) | None |
| `TOP_N` | Number of top results to show in CLI | 5 |
| `EXCEL_OUTPUT_FILE` | Output filename for Excel export | flight_results.xlsx |

### Secrets

- `SERPAPI_KEY` — SerpApi API key for Google Flights

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)

## Key Commands

- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- `pnpm --filter @workspace/api-server run dev` — run API server locally

See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details.
