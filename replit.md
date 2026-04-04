# Workspace

## Overview

pnpm workspace monorepo using TypeScript. Each package manages its own dependencies.

## Flight Optimizer (Python MVP)

Ein Python-Tool zum Optimieren von Roundtrip-Flügen nach Kosten + Reisezeit.

### Ausführen

```bash
python run_optimizer.py
```

### Projektstruktur

```
flight_optimizer/
├── config.py          ← Konfiguration (Flughäfen, Daten, Value-of-Time, Filter)
├── main.py            ← Hauptprogramm
├── serpapi_client.py  ← SerpApi Google Flights API-Client
├── scorer.py          ← Score-Berechnung (Preis + Dauer × VoT)
├── exporter.py        ← Excel-Export (openpyxl)
├── printer.py         ← Konsolenausgabe
├── date_utils.py      ← Datumsfenster-Hilfsfunktionen
└── requirements.txt   ← Python-Abhängigkeiten
run_optimizer.py       ← Startskript (Wurzelverzeichnis)
```

### Konfigurierbare Parameter (config.py)

| Parameter | Beschreibung | Standard |
|---|---|---|
| `ORIGIN_AIRPORTS` | Abflughäfen (IATA) | HKG, SZX, CAN |
| `DESTINATION_AIRPORTS` | Zielflughäfen (IATA) | FRA, MUC, NUE |
| `OUTBOUND_DATE` | Wunsch-Hinflugdatum | 2025-06-15 |
| `RETURN_DATE` | Wunsch-Rückflugdatum | 2025-06-29 |
| `DATE_WINDOW_DAYS` | ±Tage Datumsfenster | 1 |
| `VALUE_OF_TIME_EUR_PER_HOUR` | Value-of-Time (€/h) | 50.0 |
| `AIRLINE_FILTER` | Airline-Whitelist (leer = alle) | [] |
| `MAX_STOPS` | Max. Stopps (None = alle) | None |
| `TOP_N` | Anzahl Top-Ergebnisse | 5 |
| `EXCEL_OUTPUT_FILE` | Ausgabedateiname | flight_results.xlsx |

### Secrets

- `SERPAPI_KEY` — SerpApi API-Key für Google Flights

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
