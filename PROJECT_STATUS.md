# RouteBetter — Project Status Summary

_Prepared for the CEO · April 2026_

---

## What We've Built

**RouteBetter** is a personalised flight search platform that ranks flights by **true door-to-door cost** — not just ticket price. It combines airfare, total travel time (valued at a configurable €/hour rate), stop penalties, and ground transport to produce a single comparable score, so travellers can see at a glance which itinerary is genuinely cheapest once all factors are considered.

---

## Current State: Functional MVP

The product is **live and working end-to-end**. The core of what makes RouteBetter valuable is already in place:

| Area | Status |
|---|---|
| Flight search (Google Flights via SerpApi) | ✅ Live |
| Composite scoring engine | ✅ Live |
| Real-time web UI (streaming results) | ✅ Live |
| Command-line interface + Excel export | ✅ Live |
| Door-to-door ground transport estimates | ✅ Live |
| SerpApi result caching (48-hour TTL) | ✅ Live |
| API quota tracking & display | ✅ Live |

A user can open the web app, enter airports, dates, and their home address, and within seconds receive a ranked list of flights with a full breakdown of every cost component. Results stream in real time and can be exported to Excel for further review.

---

## Key Differentiators

1. **Transparent scoring** — every penalty (time cost, stop penalty, night departure, excess layover, ground transport) is shown individually. Users understand *why* a flight ranks where it does.
2. **Door-to-door accuracy** — most search tools compare gate-to-gate price. RouteBetter adds home-to-airport and airport-to-destination cost/time, giving a more honest comparison.
3. **Date-window search** — a single search automatically covers ±N days around the target dates, surfacing cheaper dates the user might not have checked.
4. **Quota-efficient caching** — the free SerpApi tier allows 100 searches/month; the 48-hour cache and parallel request controls ensure that limit goes much further.

---

## What Is Still Missing

The MVP is solid but several areas need investment before a broader rollout:

| Gap | Impact |
|---|---|
| **No automated tests** | Regressions can go undetected; difficult to add features confidently |
| **No authentication or user accounts** | The search endpoint is open; no saved searches or personalised history |
| **No rate limiting on the public endpoint** | A single user could exhaust the monthly API quota |
| **TypeScript / Node.js layer incomplete** | An API server and React client library have been scaffolded but are not integrated |
| **Database not active** | Drizzle ORM is configured but unused; no persistence for search history |
| **No direct booking links** | The app shows the best flight but users must complete booking externally |
| **No mobile-first design validation** | The UI is responsive but has not been tested systematically on mobile |
| **No CI/CD pipeline** | No automated build, lint, or test runs on pull requests |

---

## Technical Snapshot

| Metric | Detail |
|---|---|
| Primary language | Python 3.12 |
| Web framework | FastAPI + Alpine.js + Tailwind CSS |
| External flight data | SerpApi (Google Flights) |
| Ground transport data | OpenStreetMap Nominatim + OSRM |
| Codebase size | ~2,600 lines of Python · ~1,100 lines of HTML/JS |
| Test coverage | 0% (no test files exist) |
| Deployment | Uvicorn on Replit (single process) |

---

## Recommended Next Steps

### Short-term (1–2 months)
1. **Add a test suite** — unit tests for the scoring engine and integration tests for the search flow are the single highest-leverage investment.
2. **Add rate limiting** — protect the SerpApi quota with per-IP or per-session request limits.
3. **Integrate authentication** — even a simple API-key or OAuth flow would allow user-level search history.

### Medium-term (3–6 months)
4. **Complete the TypeScript API layer** — migrate the backend to the already-scaffolded Node/Express server so the Python engine can be called as a service; enables a proper React frontend.
5. **Activate the database layer** — use the Drizzle ORM setup to persist searches, enable saved itineraries, and track usage per user.
6. **CI/CD pipeline** — automated tests and deployments on every pull request.

### Longer-term
7. **Booking integration** — direct affiliate links or a booking API to convert ranked results into revenue.
8. **Multi-city support** — extend ground transport and scoring to hub-and-spoke or multi-leg trips.
9. **Calendar-view price map** — visualise the full date-window results as a heat map so users can pick the cheapest window at a glance.

---

## Bottom Line

RouteBetter has a **working, differentiated product** that goes meaningfully beyond existing flight search tools. The core value proposition is proven; what it lacks is the engineering infrastructure (tests, auth, CI/CD, database) required to scale it safely and reliably. Investing in those foundations now will allow the feature roadmap to move faster with less risk.
