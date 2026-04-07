"""
Flight Decision Engine

Provides the recommendation layer on top of the scoring pipeline.

Public API:
  validate_recommendation(best_flight, stats) -> bool
  classify_deal(price, median_price, duration, median_duration) -> str
  generate_decision_explanation(best_flight, stats, deal_label,
                                alternatives, max_personality) -> str
  run_decision_engine(flights, debug=False, max_personality=True) -> dict
"""

import logging
import statistics
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
GOOD_DEAL_THRESHOLD = 0.90      # price <= median * this → GOOD DEAL
OVERPRICED_THRESHOLD = 1.10     # price >= median * this → OVERPRICED
LOW_CONFIDENCE_THRESHOLD = 3    # fewer than this many valid flights → LOW confidence
MEDIUM_CONFIDENCE_THRESHOLD = 5  # >= this many valid flights → at least MEDIUM confidence
HIGH_CONFIDENCE_THRESHOLD = 10   # >= this many valid flights AND small spread → HIGH confidence
HIGH_CONFIDENCE_SPREAD_LIMIT = 1.5  # (max_price - min_price) / median_price < this → eligible for HIGH
VALID_DEAL_LABELS = frozenset({"GOOD DEAL", "MARKET PRICE", "OVERPRICED"})
SHORT_ROUTE_DURATION_MINUTES = 90   # routes with median < this skip duration filter
PRICE_OUTLIER_MULTIPLIER = 1.5      # price > median * this → outlier, reject
DEAL_DOWNGRADE_DURATION_MULTIPLIER = 1.2   # duration > median * this → downgrade GOOD DEAL
DEAL_EXTREME_DURATION_MULTIPLIER = 1.5     # duration > median * this → downgrade MARKET PRICE


# ── Statistics ────────────────────────────────────────────────────────────────

def _compute_stats(flights: list[dict]) -> dict:
    """Compute price and duration statistics for a list of flights."""
    prices = [
        float(f["price"])
        for f in flights
        if f.get("price") is not None
    ]
    durations = [
        float(f["duration_minutes"])
        for f in flights
        if f.get("duration_minutes") is not None
    ]
    return {
        "median_price":    statistics.median(prices)    if prices    else 0.0,
        "min_price":       min(prices)                  if prices    else 0.0,
        "max_price":       max(prices)                  if prices    else 0.0,
        "median_duration": statistics.median(durations) if durations else 0.0,
        "flight_count":    len(flights),
    }


# ── Deal classification ───────────────────────────────────────────────────────

def classify_deal(
    price: float,
    median_price: float,
    duration: Optional[float] = None,
    median_duration: Optional[float] = None,
) -> str:
    """
    Classify a flight's price relative to the market median.

    Optionally accepts *duration* and *median_duration* to apply a
    duration-aware downgrade:
      - GOOD DEAL → MARKET PRICE  if duration > DEAL_DOWNGRADE_DURATION_MULTIPLIER × median_duration
      - MARKET PRICE → OVERPRICED if duration > DEAL_EXTREME_DURATION_MULTIPLIER  × median_duration

    Returns one of: "GOOD DEAL", "MARKET PRICE", "OVERPRICED"
    """
    if median_price <= 0:
        return "MARKET PRICE"
    ratio = price / median_price
    if ratio <= GOOD_DEAL_THRESHOLD:
        label = "GOOD DEAL"
    elif ratio >= OVERPRICED_THRESHOLD:
        label = "OVERPRICED"
    else:
        label = "MARKET PRICE"

    # Duration-aware downgrade
    if duration is not None and median_duration and median_duration > 0:
        if label == "GOOD DEAL" and duration > DEAL_DOWNGRADE_DURATION_MULTIPLIER * median_duration:
            label = "MARKET PRICE"
        elif label == "MARKET PRICE" and duration > DEAL_EXTREME_DURATION_MULTIPLIER * median_duration:
            label = "OVERPRICED"

    return label


# ── Confidence ────────────────────────────────────────────────────────────────

def _compute_confidence(valid_flights: list[dict], stats: dict) -> str:
    """
    Return confidence level based on dataset size and price spread.

    - HIGH:   num_valid >= HIGH_CONFIDENCE_THRESHOLD and spread < HIGH_CONFIDENCE_SPREAD_LIMIT
    - MEDIUM: num_valid >= MEDIUM_CONFIDENCE_THRESHOLD
    - LOW:    otherwise
    """
    num_valid    = len(valid_flights)
    median_price = float(stats.get("median_price") or 0)
    min_price    = float(stats.get("min_price")    or 0)
    max_price    = float(stats.get("max_price")    or 0)

    spread = (max_price - min_price) / median_price if median_price > 0 else 0.0

    if num_valid >= HIGH_CONFIDENCE_THRESHOLD and spread < HIGH_CONFIDENCE_SPREAD_LIMIT:
        return "HIGH"
    if num_valid >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "MEDIUM"
    return "LOW"


# ── Sanity validation ─────────────────────────────────────────────────────────

def validate_recommendation(
    best_flight: dict,
    stats: dict,
    _reasons: list | None = None,
) -> bool:
    """
    Sanity-check a candidate flight recommendation.

    Rules:
      1. Completeness: price, duration_minutes, and stops must all be present.
      2. Duration sanity: duration_minutes <= median_duration * 1.5
         (skipped when median_duration < SHORT_ROUTE_DURATION_MINUTES)
      3. Stops sanity:    stops < 3
      4. Price outlier:   price <= median_price * PRICE_OUTLIER_MULTIPLIER

    Pass *_reasons* (a list) to collect human-readable rejection reasons.
    Returns True if the flight passes all checks, False otherwise.
    """
    # 1. Completeness
    for field in ("price", "duration_minutes", "stops"):
        if best_flight.get(field) is None:
            logger.warning(
                "validate_recommendation: missing required field '%s'", field
            )
            if _reasons is not None:
                _reasons.append(f"missing field: {field}")
            return False

    price    = float(best_flight["price"])
    duration = float(best_flight["duration_minutes"])
    stops    = int(best_flight["stops"])

    median_duration = float(stats.get("median_duration") or 0)
    median_price    = float(stats.get("median_price") or 0)

    # 2. Duration sanity (skip for short-haul routes)
    if median_duration >= SHORT_ROUTE_DURATION_MINUTES:
        if median_duration > 0 and duration > median_duration * 1.5:
            limit = median_duration * 1.5
            logger.warning(
                "validate_recommendation: duration %.0fmin > median*1.5 (%.0fmin) — rejected",
                duration,
                limit,
            )
            if _reasons is not None:
                _reasons.append(
                    f"duration too long: {duration:.0f}min > {limit:.0f}min"
                )
            return False

    # 3. Stops sanity
    if stops >= 3:
        logger.warning(
            "validate_recommendation: %d stops >= 3 — rejected", stops
        )
        if _reasons is not None:
            _reasons.append(f"too many stops: {stops}")
        return False

    # 4. Price outlier check
    if median_price > 0 and price > PRICE_OUTLIER_MULTIPLIER * median_price:
        limit = PRICE_OUTLIER_MULTIPLIER * median_price
        logger.warning(
            "validate_recommendation: price %.2f > %.1f × median_price %.2f — rejected",
            price,
            PRICE_OUTLIER_MULTIPLIER,
            median_price,
        )
        if _reasons is not None:
            _reasons.append(
                f"price outlier: {price:.2f} > {limit:.2f} "
                f"({PRICE_OUTLIER_MULTIPLIER}× median_price {median_price:.2f})"
            )
        return False

    return True


# ── Explanation generator ─────────────────────────────────────────────────────

def generate_decision_explanation(
    best_flight: dict,
    stats: dict,
    deal_label: str,
    alternatives: Optional[list] = None,
    max_personality: bool = True,
) -> str:
    """
    Generate a human-readable explanation of the recommendation.

    Always includes one positive aspect and one negative tradeoff so users
    are fully informed.

    When *max_personality* is True, injects Max's opinionated voice:
      - Expresses dislikes (long layovers, multi-stop routes, overpaying)
      - Highlights acceptable tradeoffs (e.g. "1 stop worth €X saved")
      - Appends a brief summary of alternatives

    When *max_personality* is False, returns a neutral factual explanation.
    """
    price        = float(best_flight.get("price") or 0)
    duration_min = int(best_flight.get("duration_minutes") or 0)
    stops        = int(best_flight.get("stops") or 0)
    airline      = best_flight.get("airline") or ""

    median_price    = float(stats.get("median_price") or price)
    median_duration = float(stats.get("median_duration") or duration_min)

    duration_h = duration_min // 60
    duration_m = duration_min % 60
    dur_str    = f"{duration_h}h {duration_m:02d}m"
    stops_str  = "non-stop" if stops == 0 else f"{stops} stop{'s' if stops != 1 else ''}"

    # ── Positive aspect ───────────────────────────────────────────────────
    if deal_label == "GOOD DEAL" and median_price > 0:
        pct_below = round((1 - price / median_price) * 100)
        if max_personality:
            positive = (
                f"Max's pick: €{price:.0f} is {pct_below}% below market — that's real savings"
            )
        else:
            positive = f"Excellent value at €{price:.0f} — {pct_below}% below market median"
    elif deal_label == "OVERPRICED" and median_price > 0:
        pct_above = round((price / median_price - 1) * 100)
        if max_personality:
            positive = (
                f"Heads up: €{price:.0f} is {pct_above}% above market — "
                "Max wouldn't overpay unless there's no alternative"
            )
        else:
            positive = f"Premium option at €{price:.0f} — {pct_above}% above market median"
    else:
        if max_personality:
            positive = f"Solid market-rate option at €{price:.0f}"
        else:
            positive = f"Fair market price at €{price:.0f}"

    # ── Negative tradeoff (always present) ───────────────────────────────
    if stops >= 2:
        if max_personality:
            tradeoff = (
                f"Max dislikes multi-stop routes — {stops_str} means more connections "
                "and longer layover time"
            )
        else:
            tradeoff = f"requires {stops_str}, adding connection time and complexity"
    elif stops == 1:
        savings_str = ""
        if deal_label == "GOOD DEAL" and median_price > 0:
            saved = round(median_price - price)
            if saved > 0:
                savings_str = f", saving you €{saved} vs. the market"
        if max_personality:
            if savings_str:
                tradeoff = (
                    f"it's 1 stop{savings_str} — Max thinks that tradeoff is worth it, "
                    f"though the total journey is {dur_str}"
                )
            else:
                tradeoff = (
                    f"requires 1 stop and total journey time is {dur_str} — "
                    "Max finds multi-leg travel a bit tiring"
                )
        else:
            tradeoff = (
                f"requires {stops_str} and total flight time is {dur_str}, "
                "which may be tiring"
            )
    elif median_duration > 0 and duration_min > median_duration * 1.1:
        if max_personality:
            tradeoff = (
                f"the {dur_str} flight is longer than usual for this route "
                f"({int(median_duration // 60)}h {int(median_duration % 60):02d}m typical) — "
                "Max prefers shorter options when they exist"
            )
        else:
            tradeoff = (
                f"the flight duration of {dur_str} is above average for this route "
                f"({int(median_duration // 60)}h {int(median_duration % 60):02d}m typical)"
            )
    else:
        if max_personality:
            tradeoff = "limited availability may mean fewer options — book early to lock in this price"
        else:
            tradeoff = "limited availability may reduce booking flexibility"

    # ── Assemble base explanation ─────────────────────────────────────────
    parts = [positive]
    if airline:
        parts.append(f"operated by {airline}")
    parts.append(f"({stops_str}, {dur_str})")
    parts.append(f"— though {tradeoff}.")

    explanation = " ".join(parts)

    # ── Alternatives summary (personality mode only) ──────────────────────
    if max_personality and alternatives:
        alt_summaries: list[str] = []
        for alt in alternatives[:3]:
            alt_price   = float(alt.get("price") or 0)
            alt_stops   = int(alt.get("stops") or 0)
            alt_airline = alt.get("airline") or "Unknown"
            alt_stops_str = (
                "non-stop" if alt_stops == 0
                else f"{alt_stops} stop{'s' if alt_stops != 1 else ''}"
            )
            if alt_price > 0:
                alt_summaries.append(f"{alt_airline} {alt_stops_str} at €{alt_price:.0f}")
        if alt_summaries:
            explanation += f" Also consider: {'; '.join(alt_summaries)}."

    return explanation


def _generate_max_tip(best_flight: dict, stats: dict, deal_label: str) -> str:
    """Return a short Max-voice tip for debug output."""
    price        = float(best_flight.get("price") or 0)
    stops        = int(best_flight.get("stops") or 0)
    median_price = float(stats.get("median_price") or 0)

    if deal_label == "GOOD DEAL":
        saved = round(median_price - price) if median_price > 0 else 0
        if stops == 0:
            return (
                f"Max says: Non-stop and €{saved} cheaper than median — book it before it's gone."
                if saved > 0 else "Max says: Non-stop at a great price — go for it."
            )
        return (
            f"Max says: Worth the stop — you're saving €{saved}."
            if saved > 0 else "Max says: Good value even with a connection."
        )
    if deal_label == "OVERPRICED":
        return "Max says: Too pricey. Try adjusting dates or check the alternatives above."
    if stops >= 2:
        return "Max says: Multiple connections? Only if the savings are massive."
    if stops == 1:
        return "Max says: One stop is manageable — just check the layover duration."
    return "Max says: Solid non-stop at a fair price. No red flags."


# ── Main engine ───────────────────────────────────────────────────────────────

def run_decision_engine(
    flights: list[dict],
    debug: bool = False,
    max_personality: bool = True,
) -> dict:
    """
    Run the decision engine on a list of pre-scored flights.

    Expects *flights* to be sorted by score ascending (best first), which is
    the natural output of scorer.recalculate_scores_with_return().

    Parameters
    ----------
    flights:         Pre-scored flight dicts, sorted by score (best first).
    debug:           When True, include extra diagnostic fields in the result.
    max_personality: When True (default), use Max's opinionated explanation
                     voice and include alternatives commentary.

    Returns:
    {
        "best_flight":  dict,
        "deal":         {"label": str, "confidence": str},
        "explanation":  str,
        "alternatives": list[dict],   # max 3
        "meta":         dict,
        "debug":        dict | None,  # only present when debug=True
    }

    Edge-case handling:
      - Economy filter returns nothing → fall back to all classes, meta.premium_only = True
      - Fewer than LOW_CONFIDENCE_THRESHOLD valid flights → confidence = "LOW"
      - Sanity check rejects all flights → fall back to unfiltered list
    """
    if not flights:
        raise ValueError("run_decision_engine: flights list is empty")

    # ── Economy filter with fallback ─────────────────────────────────────
    premium_only = False
    economy_flights = [
        f for f in flights
        if str(f.get("booking_class") or "Economy").lower() in ("economy", "")
    ]
    if economy_flights:
        working_flights = economy_flights
    else:
        logger.warning(
            "run_decision_engine: no economy flights found — "
            "falling back to all booking classes"
        )
        working_flights = flights
        premium_only = True

    # ── Statistics ───────────────────────────────────────────────────────
    stats = _compute_stats(working_flights)

    logger.info(
        "Decision engine: %d flights | median price €%.0f | "
        "median duration %.0fmin",
        len(working_flights),
        stats["median_price"],
        stats["median_duration"],
    )

    # ── Sanity-validate candidates (Step 5: collect all valid first) ─────────
    rejection_reasons: list[str] = []
    fallback_triggered = False

    valid_flights: list[dict] = [
        f for f in working_flights
        if validate_recommendation(f, stats, rejection_reasons)
    ]
    rejected_count = len(working_flights) - len(valid_flights)

    # ── Fallback: top-3 by score with route diversity (Step 4) ───────────────────
    if not valid_flights:
        logger.warning(
            "run_decision_engine: all %d flight(s) failed sanity check — "
            "falling back to top-3 diverse scored candidates",
            rejected_count,
        )
        sorted_candidates = sorted(
            working_flights,
            key=lambda f: float(f.get("score") or 0),
        )
        # Pick up to 3 with unique route signatures (stops + airline)
        seen_signatures: set[tuple] = set()
        fallback_candidates: list[dict] = []
        for f in sorted_candidates:
            sig = (f.get("stops"), f.get("airline"))
            if sig not in seen_signatures:
                seen_signatures.add(sig)
                fallback_candidates.append(f)
            if len(fallback_candidates) == 3:
                break
        fallback_reasons: list[str] = []
        valid_flights = [
            f for f in fallback_candidates
            if validate_recommendation(f, stats, fallback_reasons)
        ]
        if not valid_flights:
            # Last resort: accept the best-scored candidate unconditionally
            valid_flights = fallback_candidates[:1]
        rejection_reasons.extend(fallback_reasons)
        fallback_triggered = True

    # ── Confidence ───────────────────────────────────────────────────────
    confidence = _compute_confidence(valid_flights, stats)

    # ── Select best and alternatives ──────────────────────────────────────
    best_flight  = valid_flights[0]
    alternatives = valid_flights[1:4]   # up to 3 more

    # ── Deal classification ───────────────────────────────────────────────
    deal_label = classify_deal(
        float(best_flight.get("price") or 0),
        stats["median_price"],
        duration=float(best_flight["duration_minutes"]) if best_flight.get("duration_minutes") is not None else None,
        median_duration=stats["median_duration"] or None,
    )

    # ── Explanation ───────────────────────────────────────────────────────
    explanation = generate_decision_explanation(
        best_flight,
        stats,
        deal_label,
        alternatives=alternatives,
        max_personality=max_personality,
    )

    # ── Structured logging ────────────────────────────────────────────────
    logger.info(
        "Decision: %s | €%.0f | %s stop(s) | %smin | %s confidence",
        deal_label,
        float(best_flight.get("price") or 0),
        best_flight.get("stops", "?"),
        best_flight.get("duration_minutes", "?"),
        confidence,
    )

    result: dict = {
        "best_flight":  best_flight,
        "deal":         {"label": deal_label, "confidence": confidence},
        "explanation":  explanation,
        "alternatives": alternatives[:3],
        "meta": {
            "total_flights":   len(flights),
            "valid_flights":   len(valid_flights),
            "premium_only":    premium_only,
            "price_vs_median": (
                round(float(best_flight.get("price") or 0) / stats["median_price"], 2)
                if stats["median_price"] > 0 else None
            ),
        },
    }

    if debug:
        result["debug"] = {
            "median_duration":              stats["median_duration"],
            "median_price":                 stats["median_price"],
            "rejected_flights_count":       rejected_count,
            "fallback_triggered":           fallback_triggered,
            "fallback_used":                fallback_triggered,
            "num_valid_flights":            len(valid_flights),
            "validation_rejection_reasons": rejection_reasons,
            "price_vs_median":              result["meta"]["price_vs_median"],
            "max_personality_tip":          _generate_max_tip(best_flight, stats, deal_label),
        }

    # ── Guards ────────────────────────────────────────────────────────────
    assert result["best_flight"] is not None, "best_flight must not be None"
    assert len(result["alternatives"]) <= 3, "alternatives must not exceed 3"
    assert result["explanation"], "explanation must be non-empty"
    assert result["deal"]["label"] in VALID_DEAL_LABELS, (
        f"invalid deal label: {result['deal']['label']!r}"
    )

    return result
