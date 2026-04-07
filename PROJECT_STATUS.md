# RouteBetter — Flight Optimizer MVP: Project Status

> **Date:** April 2026  
> **Status:** MVP complete — ready for internal demo / pilot

---

## 1. Technical Summary

### Implemented Features & Modules

| Module | Location | Description |
|---|---|---|
| **Decision Engine** | `flight_optimizer/decision_engine.py` | Core recommendation layer: deal classification, confidence scoring, fallback logic, personality voice |
| **Scoring Pipeline** | `flight_optimizer/scorer.py` | Composite score: price + time × value-of-time + stop penalties + night-departure penalties + excess layover penalties + ground transport |
| **SerpApi Client** | `flight_optimizer/serpapi_client.py` | Google Flights data fetcher via SerpApi; raises typed errors (`QuotaExhaustedError`, `PastDateError`, `InvalidApiKeyError`) |
| **Cache** | `flight_optimizer/cache.py` | JSON-based flight result cache; outbound keys `"{origin}_{dest}_{outbound}_{return}"`; return-leg keys prefixed `"return__{token[:32]}"` |
| **Mock / Simulation** | `flight_optimizer/mock_data.py` | `generate_mock_flights()`, `load_mock_flights_from_cache()`, `check_cache_integrity()`; toggled via `USE_MOCK_DATA` and `MOCK_FALLBACK` in `config.py` |
| **Ground Transport** | `flight_optimizer/ground_transport.py` | Door-to-door cost and time via Nominatim (geocoding) + OSRM (routing) + optional AI transport-mode selection |
| **Web Application** | `flight_webapp/app.py` | FastAPI backend serving SSE-streamed search results, JSON recommendation endpoint, usage tracking, debug pipeline |
| **CLI** | `run_optimizer.py` / `flight_optimizer/main.py` | Batch search with console output and Excel export |
| **Excel Export** | `flight_optimizer/exporter.py` | Full ranked results exported to `.xlsx` via `openpyxl` |
| **Usage Tracker** | `flight_optimizer/usage_tracker.py` | Monthly SerpApi quota tracking; falls back to local counter when live API is unreachable |

### API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Serves the Alpine.js + Tailwind CSS single-page UI |
| `GET` | `/health` | Liveness probe |
| `GET` | `/flight/usage` | Live SerpApi quota (falls back to local counter) |
| `GET` | `/debug/pipeline` | Pipeline integrity report (API key, cache, mock availability) |
| `GET` | `/search/stream` | SSE-streamed real-time flight search |
| `GET` | `/flight/recommend` | Single structured recommendation with deal analysis |
| `GET` | `/export/{id}` | Download Excel report |

### Decision Engine — Key Behaviours

- **Deal classification:** `GOOD DEAL` (price ≤ 90% of median), `MARKET PRICE`, `OVERPRICED` (price ≥ 110% of median).
- **Duration-aware downgrade:** a `GOOD DEAL` becomes `MARKET PRICE` if the flight is > 20% longer than the median duration; `MARKET PRICE` becomes `OVERPRICED` if > 50% longer.
- **Confidence levels:** `HIGH` (≥ 10 valid flights, tight price spread), `MEDIUM` (≥ 5 flights), `LOW` (< 5 flights).
- **Sanity validation:** rejects flights with missing fields, duration > 1.5× median (unless short-haul), ≥ 3 stops, or price > 1.5× median (price outlier).
- **Fallback ladder:**
  1. Economy class filter → if empty, fall back to all classes (`meta.premium_only = true`).
  2. Sanity check rejects all candidates → fall back to top-3 diverse (unique stops + airline) scored candidates.
  3. Still empty → accept the single best-scored candidate unconditionally.
- **Explanation voice:** "Max" personality mode (default) gives opinionated, user-friendly explanations including alternatives summary; `max_personality=false` returns neutral factual text.
- **Debug mode:** exposes `median_price`, `median_duration`, `rejected_flights_count`, `fallback_triggered`, `validation_rejection_reasons`, `price_vs_median`, and `max_personality_tip`.

### Edge-Case Handling

- **Past dates:** rejected before any date-window expansion; clear error message returned.
- **Empty date-window result:** secondary filter discards any window-expanded date combos that fall before today.
- **Concurrency:** max 3 simultaneous search sessions; 8 parallel outbound fetches per session; 5 parallel return-leg fetches.
- **NaN / Inf values:** `_sanitize_nan()` scrubs all API responses before JSON serialisation.
- **Ground transport failure:** logged as a warning; search continues without the ground-transport component.
- **Short-haul routes:** duration sanity check is skipped for routes whose median duration is under 90 minutes.

### Known Limitations

- **API quota:** SerpApi free tier = 100 searches/month. Each origin × destination × date combination is one search. High date-window values or many airport combinations exhaust quota quickly.
- **No authentication:** the web app has no user accounts, rate-limiting, or access control.
- **No affiliate/booking integration:** results are informational only; users must book through a third-party site.
- **Ground transport coverage:** depends on Nominatim/OSRM availability and quality of address geocoding; AI routing is optional.
- **Return-leg detail:** return-leg data (fetched via SerpApi departure tokens) may be incomplete or unavailable for some routes.

### Test Coverage

- **Test suite:** `tests/test_decision_engine.py` — 60 tests covering deal classification, confidence levels, sanity validation, edge cases (premium fallback, empty input, all-rejected fallback), explanation quality, Max personality voice, alternatives, debug fields, and response schema.
- **Status:** ✅ All 60 tests pass against Python 3.12.
- **Coverage gaps (not yet tested):** `scorer.py`, `cache.py`, `ground_transport.py`, `serpapi_client.py`, and the FastAPI endpoints (integration tests).

---

## 2. CIO / Executive Summary

### What Has Been Built

RouteBetter is a personalised flight recommendation engine that goes beyond price comparison. It evaluates flights on a composite score that weighs price, total travel time, number of stops, night departures, excessive layovers, and door-to-door ground transport cost. The result is a ranked shortlist of the best-value flights tailored to the user's own value of time.

The MVP includes a real-time web UI, a REST API, a command-line tool, and an Excel export. All components are functional and have been validated against live (cached) data.

### Value Delivered

| Capability | Business Value |
|---|---|
| Composite scoring | Goes beyond cheapest fare — surfaces truly cost-efficient options when time is valued |
| Deal classification | Gives users an instant, trustworthy signal: GOOD DEAL / MARKET PRICE / OVERPRICED |
| Confidence indicator | Builds trust by being transparent when data is limited (LOW confidence) |
| "Max" personality voice | Differentiates the product; creates a memorable, opinionated AI assistant experience |
| Ground transport integration | Enables true door-to-door comparison — a unique feature vs. standard flight aggregators |
| Simulation / mock mode | Enables demos and development without consuming API quota |
| Real-time streaming UI | Modern, responsive user experience with live progress feedback |

### Readiness for Demo / Pilot

The system is ready for:
- **Internal demo** with any set of airports and dates (mock mode available if API quota is exhausted).
- **Pilot with real users** provided a SerpApi key with sufficient quota is in place.
- **Stakeholder presentation** — the `/flight/recommend` endpoint returns a fully structured JSON response suitable for UI integration or slide-deck screenshots.

### Dependencies, Risks & Gaps

| Item | Impact | Mitigation |
|---|---|---|
| SerpApi free-tier quota (100/month) | Limits live-data searches during demo | Use mock mode (`?use_mock=true`) or upgrade to a paid SerpApi plan |
| No user authentication | Any user can trigger searches; no personalisation storage | Acceptable for MVP; add auth layer before public launch |
| No affiliate/booking revenue | No monetisation path yet | Integrate Skyscanner, Kiwi, or Google Flights affiliate links as next step |
| Single-region deployment | No geographic redundancy | Not a concern at MVP stage |
| External API reliability (SerpApi, Nominatim, OSRM) | Outages affect live data; mock fallback mitigates | Automatic mock fallback is implemented |

---

## 3. Next Steps / Recommendations

### Immediate (Tactical — 1–2 Weeks)

- [ ] **Add SerpApi paid-tier key** to unlock sufficient quota for a live pilot.
- [ ] **Add integration tests** for the FastAPI endpoints (`/flight/recommend`, `/search/stream`) using `httpx` / `pytest-asyncio`.
- [ ] **Expand test coverage** to `scorer.py`, `cache.py`, and `ground_transport.py`.
- [ ] **Pilot with a real search** (e.g., HKG → FRA, July 2026) to validate end-to-end live data flow before the demo.
- [ ] **Polish the UI** — add a "copy shareable link" button and a visible GOOD DEAL badge on the best result.
- [ ] **Fix the README** — update the Python version requirement from `3.10+` to `3.12+` to match `pyproject.toml`.

### Medium-Term (Strategic — 1–3 Months)

- [ ] **Affiliate link integration** — embed booking deep-links (Skyscanner Partner API, Kiwi Tequila, or Google Flights affiliate) to each recommended flight to enable revenue.
- [ ] **Advanced scoring personalisation** — allow users to save preferences (value of time, stop tolerance, preferred airlines) to a profile; pre-fill the search form accordingly.
- [ ] **Scalability** — add a task queue (Celery + Redis or equivalent) to decouple search execution from the SSE stream; removes the current 3-session hard cap.
- [ ] **Rate-limiting and authentication** — add JWT-based auth and per-user API rate limits before any public launch.
- [ ] **Expand route coverage** — add more origin/destination pairs and multi-city itinerary support.
- [ ] **Historical price tracking** — store past search results to detect price trends and alert users when fares drop.

### Long-Term (Opportunities — 3–12 Months)

- [ ] **AI-driven personalisation** — fine-tune recommendations using past booking behaviour and implicit signals (e.g., clicked alternatives); integrate an LLM to answer follow-up questions about the recommendation.
- [ ] **Multi-market rollout** — support additional currencies, languages, and domestic-leg routing for markets beyond Hong Kong → Europe.
- [ ] **Flexible-date calendar view** — visualise price × quality score across a full month to surface the best travel window, not just the target date.
- [ ] **Mobile app** — package the recommendation API behind a lightweight mobile frontend for on-the-go flight monitoring.
- [ ] **Hotel and transfer bundling** — extend the composite score to include accommodation and airport transfer costs for a true total-trip value comparison.
- [ ] **B2B / white-label offering** — license the scoring engine to corporate travel management companies as a behind-the-scenes optimisation layer.
