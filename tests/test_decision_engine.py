"""
Tests for flight_optimizer/decision_engine.py

Covers:
  - Deal classification (GOOD DEAL, MARKET PRICE, OVERPRICED)
  - Confidence levels (HIGH / LOW based on dataset size)
  - Sanity/validation layer (duration filter, stops filter)
  - Edge cases (premium fallback, no valid flights)
  - Explanation quality (must include a negative tradeoff)
  - Response structure
"""

import sys
import os

# Ensure the project root is on sys.path so imports work without installation
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flight_optimizer.decision_engine import (
    run_decision_engine,
    validate_recommendation,
    classify_deal,
    VALID_DEAL_LABELS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_flight(**kwargs) -> dict:
    """Return a minimal valid flight dict with sensible defaults."""
    defaults: dict = {
        "price":            500.0,
        "duration_minutes": 600,
        "stops":            1,
        "airline":          "Test Airlines",
        "origin":           "HKG",
        "destination":      "FRA",
        "booking_class":    "Economy",
        "outbound_date":    "2026-07-25",
        "return_date":      "2026-08-02",
        "score":            700.0,
    }
    defaults.update(kwargs)
    return defaults


def _make_stats(**kwargs) -> dict:
    """Return a minimal valid stats dict with sensible defaults."""
    defaults: dict = {
        "median_price":    500.0,
        "min_price":       300.0,
        "max_price":       900.0,
        "median_duration": 600.0,
        "flight_count":    10,
    }
    defaults.update(kwargs)
    return defaults


def _sorted_flights(flights: list[dict]) -> list[dict]:
    """Sort flights by score ascending (best first), as the scorer would."""
    return sorted(flights, key=lambda f: f["score"])


# ── Deal classification tests ─────────────────────────────────────────────────

def test_good_deal_classification():
    """A cheap flight vs median → GOOD DEAL."""
    # 1 cheap flight (score=450) + 9 market-rate flights (score=650)
    # median_price = 500  →  400/500 = 0.80 < 0.85 → GOOD DEAL
    flights = _sorted_flights(
        [_make_flight(price=400.0, score=450.0)]
        + [_make_flight(price=500.0, score=650.0 + i) for i in range(9)]
    )
    result = run_decision_engine(flights)
    assert result["deal"]["label"] == "GOOD DEAL"


def test_overpriced_classification():
    """An expensive flight that ranks first by score → OVERPRICED."""
    # 1 expensive flight (best score=500) + 9 market-rate flights (score=650)
    # median_price = 500  →  700/500 = 1.40 > 1.15 → OVERPRICED
    flights = _sorted_flights(
        [_make_flight(price=700.0, score=500.0)]
        + [_make_flight(price=500.0, score=650.0 + i) for i in range(9)]
    )
    result = run_decision_engine(flights)
    assert result["deal"]["label"] == "OVERPRICED"


def test_market_price_classification():
    """A flight priced close to the median → MARKET PRICE."""
    # All flights at the same price → ratio exactly 1.0 → MARKET PRICE
    flights = _sorted_flights(
        [_make_flight(price=500.0, score=600.0 + i) for i in range(5)]
    )
    result = run_decision_engine(flights)
    assert result["deal"]["label"] == "MARKET PRICE"


def test_classify_deal_direct():
    """Unit-test the classify_deal helper directly."""
    assert classify_deal(400.0, 500.0) == "GOOD DEAL"
    assert classify_deal(500.0, 500.0) == "MARKET PRICE"
    assert classify_deal(700.0, 500.0) == "OVERPRICED"
    # Edge: zero median should not raise, returns MARKET PRICE
    assert classify_deal(500.0, 0.0) == "MARKET PRICE"


# ── Confidence tests ──────────────────────────────────────────────────────────

def test_low_confidence_small_dataset():
    """Fewer than 5 valid flights → confidence = LOW."""
    flights = _sorted_flights([
        _make_flight(price=400.0, score=550.0),
        _make_flight(price=500.0, score=650.0),
    ])
    result = run_decision_engine(flights)
    assert result["deal"]["confidence"] == "LOW"


def test_medium_confidence_dataset():
    """5–9 valid flights → confidence = MEDIUM."""
    flights = _sorted_flights([
        _make_flight(price=400.0 + i * 20, score=550.0 + i * 30)
        for i in range(6)
    ])
    result = run_decision_engine(flights)
    assert result["deal"]["confidence"] == "MEDIUM"


def test_high_confidence_large_dataset():
    """10+ valid flights with small price spread → confidence = HIGH."""
    flights = _sorted_flights([
        _make_flight(price=490.0 + i * 2, score=550.0 + i * 10)
        for i in range(10)
    ])
    result = run_decision_engine(flights)
    assert result["deal"]["confidence"] == "HIGH"


def test_high_confidence_wide_spread_downgrades_to_medium():
    """10+ valid flights but wide price spread → confidence = MEDIUM, not HIGH."""
    # prices span 200–900 → spread = (900-200)/median > 1.5 → not HIGH
    flights = _sorted_flights([
        _make_flight(price=200.0 + i * 80, score=550.0 + i * 10)
        for i in range(10)
    ])
    result = run_decision_engine(flights)
    assert result["deal"]["confidence"] == "MEDIUM"


# ── Validation (sanity check) tests ──────────────────────────────────────────

def test_duration_filter():
    """Flight with duration > 1.5× median → rejected."""
    flight = _make_flight(duration_minutes=1000, stops=0)  # 1000 > 600 × 1.5 = 900
    stats  = _make_stats(median_duration=600.0, max_price=900.0)
    assert validate_recommendation(flight, stats) is False


def test_stops_filter():
    """Flight with 3 or more stops → rejected."""
    flight = _make_flight(stops=3)
    stats  = _make_stats()
    assert validate_recommendation(flight, stats) is False


def test_stops_filter_exact_three():
    """Flight with exactly 3 stops → rejected (boundary condition)."""
    flight = _make_flight(stops=3)
    stats  = _make_stats()
    assert validate_recommendation(flight, stats) is False


def test_stops_filter_two_passes():
    """Flight with 2 stops and acceptable duration → accepted."""
    flight = _make_flight(stops=2, duration_minutes=600)
    stats  = _make_stats(median_duration=600.0, max_price=900.0)
    assert validate_recommendation(flight, stats) is True


def test_missing_price_fails_validation():
    """Flight missing 'price' field → rejected."""
    flight = _make_flight()
    del flight["price"]
    stats = _make_stats()
    assert validate_recommendation(flight, stats) is False


def test_missing_duration_fails_validation():
    """Flight missing 'duration_minutes' field → rejected."""
    flight = _make_flight()
    del flight["duration_minutes"]
    stats = _make_stats()
    assert validate_recommendation(flight, stats) is False


def test_valid_flight_passes_validation():
    """Normal flight with no issues → accepted."""
    flight = _make_flight(duration_minutes=600, stops=1, price=500.0)
    stats  = _make_stats(median_duration=600.0, max_price=900.0)
    assert validate_recommendation(flight, stats) is True


# ── Edge case tests ───────────────────────────────────────────────────────────

def test_premium_fallback():
    """When no economy flights exist → premium_only = True in meta."""
    flights = _sorted_flights([
        _make_flight(price=700.0, booking_class="Business", score=800.0),
        _make_flight(price=800.0, booking_class="Business", score=900.0),
        _make_flight(price=900.0, booking_class="First",    score=1000.0),
    ])
    result = run_decision_engine(flights)
    assert result["meta"]["premium_only"] is True


def test_economy_flights_not_flagged_premium():
    """Economy flights present → premium_only = False in meta."""
    flights = _sorted_flights([
        _make_flight(price=500.0, booking_class="Economy", score=650.0 + i)
        for i in range(4)
    ])
    result = run_decision_engine(flights)
    assert result["meta"]["premium_only"] is False


def test_empty_flights_raises():
    """Empty flight list → ValueError."""
    with pytest.raises(ValueError):
        run_decision_engine([])


def test_sanity_fallback_when_all_rejected():
    """If all flights fail sanity checks, fall back to unfiltered list (no crash)."""
    # All flights have 3 stops (fail stops check)
    flights = _sorted_flights([
        _make_flight(stops=3, price=500.0 + i * 10, score=600.0 + i * 10)
        for i in range(5)
    ])
    # Should not raise; falls back gracefully
    result = run_decision_engine(flights)
    assert result["best_flight"] is not None
    assert result["explanation"]


# ── Explanation quality tests ─────────────────────────────────────────────────

def test_explanation_contains_negative():
    """Explanation must include a negative tradeoff marker."""
    flights = _sorted_flights([
        _make_flight(price=500.0 + i * 10, stops=1, score=650.0 + i * 10)
        for i in range(5)
    ])
    result      = run_decision_engine(flights)
    explanation = result["explanation"].lower()
    negative_markers = ("though", "but", "—", "however", "tiring", "complex", "above average")
    assert any(m in explanation for m in negative_markers), (
        f"Explanation missing negative tradeoff: {result['explanation']!r}"
    )


def test_explanation_is_non_empty():
    """Explanation is always a non-empty string."""
    flights = _sorted_flights([
        _make_flight(price=500.0, score=650.0 + i)
        for i in range(4)
    ])
    result = run_decision_engine(flights)
    assert isinstance(result["explanation"], str)
    assert len(result["explanation"]) > 0


# ── Response structure tests ──────────────────────────────────────────────────

def test_endpoint_response_structure():
    """Full decision output matches the expected schema."""
    flights = _sorted_flights([
        _make_flight(price=450.0 + i * 50, stops=i % 2, score=600.0 + i * 40)
        for i in range(8)
    ])
    result = run_decision_engine(flights)

    # Required top-level keys
    assert "best_flight"  in result
    assert "deal"         in result
    assert "explanation"  in result
    assert "alternatives" in result
    assert "meta"         in result

    # best_flight constraints
    assert result["best_flight"] is not None

    # deal constraints
    assert result["deal"]["label"]      in VALID_DEAL_LABELS
    assert result["deal"]["confidence"] in {"HIGH", "MEDIUM", "LOW"}

    # explanation constraints
    assert isinstance(result["explanation"], str)
    assert len(result["explanation"]) > 0

    # alternatives constraints
    assert isinstance(result["alternatives"], list)
    assert len(result["alternatives"]) <= 3

    # meta constraints
    assert "total_flights"   in result["meta"]
    assert "valid_flights"   in result["meta"]
    assert "premium_only"    in result["meta"]
    assert "price_vs_median" in result["meta"]


def test_debug_fields_present_when_requested():
    """When debug=True, extra debug fields are included."""
    flights = _sorted_flights([
        _make_flight(price=500.0 + i * 10, score=650.0 + i * 10)
        for i in range(5)
    ])
    result = run_decision_engine(flights, debug=True)
    assert "debug" in result
    assert "median_duration"        in result["debug"]
    assert "median_price"           in result["debug"]
    assert "rejected_flights_count" in result["debug"]


def test_debug_fields_absent_by_default():
    """When debug is not requested, no 'debug' key in response."""
    flights = _sorted_flights([
        _make_flight(price=500.0 + i * 10, score=650.0 + i * 10)
        for i in range(5)
    ])
    result = run_decision_engine(flights)
    assert "debug" not in result


def test_alternatives_max_three():
    """alternatives list never exceeds 3 entries, even with many flights."""
    flights = _sorted_flights([
        _make_flight(price=500.0 + i * 10, score=600.0 + i * 10)
        for i in range(20)
    ])
    result = run_decision_engine(flights)
    assert len(result["alternatives"]) <= 3


# ── New threshold / validation tests (Steps 1–5) ─────────────────────────────

def test_deal_thresholds_updated():
    """
    Verify the updated boundaries:
      - price == 0.90 × median → GOOD DEAL  (inclusive)
      - price == 1.10 × median → OVERPRICED (inclusive)
      - price between 0.90 and 1.10 × median → MARKET PRICE
    """
    from flight_optimizer.decision_engine import classify_deal

    median = 500.0
    # Exactly at the GOOD DEAL boundary
    assert classify_deal(median * 0.90, median) == "GOOD DEAL"
    # Exactly at the OVERPRICED boundary
    assert classify_deal(median * 1.10, median) == "OVERPRICED"
    # Just inside MARKET PRICE from below (0.91 × median)
    assert classify_deal(median * 0.91, median) == "MARKET PRICE"
    # Just inside MARKET PRICE from above (1.09 × median)
    assert classify_deal(median * 1.09, median) == "MARKET PRICE"


def test_price_outlier_rejection():
    """A flight priced > 1.5× median is rejected by validate_recommendation."""
    # median_price = 500, so 1.5 × 500 = 750; price 800 is an outlier
    flight = _make_flight(price=800.0, duration_minutes=600, stops=0)
    stats  = _make_stats(median_price=500.0, median_duration=600.0)
    assert validate_recommendation(flight, stats) is False


def test_price_outlier_boundary_passes():
    """A flight priced exactly at 1.5× median passes (boundary is exclusive)."""
    flight = _make_flight(price=750.0, duration_minutes=600, stops=0)
    stats  = _make_stats(median_price=500.0, median_duration=600.0)
    assert validate_recommendation(flight, stats) is True


def test_short_route_duration_skip():
    """
    When median_duration < 90 minutes, the duration filter is skipped
    entirely so that short-haul routes are not over-filtered.
    """
    # median 60 min → skip duration filter; flight's 200 min should be accepted
    flight = _make_flight(price=100.0, duration_minutes=200, stops=0)
    stats  = _make_stats(median_price=100.0, median_duration=60.0)
    assert validate_recommendation(flight, stats) is True


def test_duration_filter_still_applied_above_threshold():
    """Duration filter applies when median_duration >= 90 minutes."""
    # median 120 min → filter active; 300 > 120 × 1.5 = 180 → rejected
    flight = _make_flight(price=500.0, duration_minutes=300, stops=0)
    stats  = _make_stats(median_price=500.0, median_duration=120.0)
    assert validate_recommendation(flight, stats) is False


def test_safe_fallback_top3_only():
    """
    When all flights fail validation, the fallback only considers top-3 by
    score.  The best_flight must come from those top-3, not from the rest.
    """
    # 5 flights with 3 stops (all fail validation)
    # Scores: 600, 610, 620, 630, 640 — top-3 lowest-scored (best) are 600, 610, 620
    flights = _sorted_flights([
        _make_flight(stops=3, price=500.0 + i * 10, score=600.0 + i * 10)
        for i in range(5)
    ])
    result = run_decision_engine(flights)
    # best_flight must be one of the top-3-scored flights
    top3_prices = {500.0, 510.0, 520.0}
    assert result["best_flight"]["price"] in top3_prices
    assert result["best_flight"] is not None


def test_valid_flight_selection_logic():
    """
    All valid flights are collected first, then the best (lowest-scored) is
    chosen.  A high-scored expensive flight ranked first should NOT be chosen
    over a lower-scored cheaper flight that also passes validation.
    """
    # cheap flight has best score (lowest), expensive has second-best score
    cheap_flight     = _make_flight(price=400.0, duration_minutes=600, stops=0, score=500.0)
    expensive_flight = _make_flight(price=900.0, duration_minutes=600, stops=0, score=600.0)
    normal_flights   = [
        _make_flight(price=500.0, duration_minutes=600, stops=1, score=700.0 + i)
        for i in range(8)
    ]
    flights = _sorted_flights([cheap_flight, expensive_flight] + normal_flights)
    result  = run_decision_engine(flights)
    # The cheap flight (best score, passes validation) should be chosen
    assert result["best_flight"]["price"] == 400.0


def test_never_recommend_extreme_duration():
    """
    A very cheap flight with duration > 2× median must NOT be selected
    as best_flight when better alternatives exist.

    Step 6 human sanity test.
    """
    # cheap_extreme: great price, but 2 × 600 = 1200 min duration (way over 1.5 × median)
    cheap_extreme = _make_flight(
        price=100.0, duration_minutes=1300, stops=0, score=400.0
    )
    # normal flights: reasonable price and duration
    normal_flights = _sorted_flights([
        _make_flight(price=500.0, duration_minutes=600, stops=1, score=600.0 + i)
        for i in range(5)
    ])
    # median_duration will be ~600 (set by the normal flights); 1300 > 600 × 1.5 = 900
    flights = _sorted_flights([cheap_extreme] + normal_flights)
    result  = run_decision_engine(flights)
    assert result["best_flight"]["duration_minutes"] != 1300, (
        "Extreme-duration flight must never be selected as best_flight"
    )


def test_extreme_duration_rejection():
    """validate_recommendation directly rejects a flight with extreme duration."""
    flight = _make_flight(price=100.0, duration_minutes=1500, stops=0)
    # median 600 min, 1500 > 900 → rejected
    stats  = _make_stats(median_price=500.0, median_duration=600.0)
    assert validate_recommendation(flight, stats) is False


# ── Debug output new fields ───────────────────────────────────────────────────

def test_debug_new_fields_present():
    """debug block contains the new fields added in Step 8."""
    flights = _sorted_flights([
        _make_flight(price=500.0 + i * 10, score=650.0 + i * 10)
        for i in range(5)
    ])
    result = run_decision_engine(flights, debug=True)
    debug  = result["debug"]
    assert "fallback_used"                in debug
    assert "num_valid_flights"            in debug
    assert "validation_rejection_reasons" in debug
    assert isinstance(debug["validation_rejection_reasons"], list)
    assert isinstance(debug["fallback_used"], bool)
    assert isinstance(debug["num_valid_flights"], int)


def test_debug_fallback_used_true_when_all_rejected():
    """fallback_used is True in debug when all flights fail validation."""
    flights = _sorted_flights([
        _make_flight(stops=3, score=600.0 + i * 10)
        for i in range(5)
    ])
    result = run_decision_engine(flights, debug=True)
    assert result["debug"]["fallback_used"] is True


def test_debug_rejection_reasons_populated():
    """validation_rejection_reasons is non-empty when at least one flight is rejected."""
    # 1 outlier flight (duration=2000), 4 normal (duration=600)
    # median_duration = 600; 2000 > 600×1.5=900 → rejected and reason recorded
    flights = _sorted_flights(
        [_make_flight(duration_minutes=2000, stops=0, score=400.0)]
        + [
            _make_flight(duration_minutes=600, stops=0, score=600.0 + i * 10)
            for i in range(4)
        ]
    )
    result = run_decision_engine(flights, debug=True)
    assert len(result["debug"]["validation_rejection_reasons"]) > 0


# ── New feature tests ─────────────────────────────────────────────────────────

def test_duration_aware_good_deal_downgrade():
    """
    GOOD DEAL → MARKET PRICE when duration > 1.2 × median_duration.
    The cheap flight (price=350, score=400) has duration=800 min;
    median_duration from other flights is ~600 min → 800 > 1.2*600=720 → downgrade.
    """
    from flight_optimizer.decision_engine import classify_deal

    # Direct unit-test of classify_deal with duration params
    assert classify_deal(350.0, 500.0, duration=800.0, median_duration=600.0) == "MARKET PRICE"
    # Without duration params the price alone would be a GOOD DEAL
    assert classify_deal(350.0, 500.0) == "GOOD DEAL"


def test_duration_aware_market_price_extreme_downgrade():
    """
    MARKET PRICE → OVERPRICED when duration > 1.5 × median_duration.
    """
    from flight_optimizer.decision_engine import classify_deal

    # price is MARKET PRICE by ratio, but extreme duration → OVERPRICED
    assert classify_deal(500.0, 500.0, duration=950.0, median_duration=600.0) == "OVERPRICED"
    # duration just below extreme threshold → still MARKET PRICE
    assert classify_deal(500.0, 500.0, duration=899.0, median_duration=600.0) == "MARKET PRICE"


def test_duration_aware_downgrade_in_engine():
    """
    run_decision_engine applies duration-aware downgrade: a cheap but slow
    best flight is reported as MARKET PRICE, not GOOD DEAL.
    """
    # Best flight: cheap (GOOD DEAL by price) but slow (duration = 800 > 1.2*600=720)
    slow_cheap = _make_flight(price=350.0, duration_minutes=800, stops=0, score=400.0)
    # Normal flights: market price, median duration ~600
    normal_flights = [
        _make_flight(price=500.0, duration_minutes=600, stops=1, score=600.0 + i)
        for i in range(9)
    ]
    flights = _sorted_flights([slow_cheap] + normal_flights)
    result = run_decision_engine(flights)
    # Price alone would be GOOD DEAL, but long duration downgrades it
    assert result["deal"]["label"] == "MARKET PRICE"


def test_fallback_diversity_unique_routes():
    """
    In the fallback path, flights sharing the same route signature
    (stops + airline) are deduplicated so up to 3 distinct routes are chosen.
    """
    # 4 flights all failing validation (3 stops), but 3 different airlines
    flights = _sorted_flights([
        _make_flight(stops=3, airline="AirA", price=500.0, score=600.0),
        _make_flight(stops=3, airline="AirA", price=510.0, score=610.0),  # duplicate sig
        _make_flight(stops=3, airline="AirB", price=520.0, score=620.0),
        _make_flight(stops=3, airline="AirC", price=530.0, score=630.0),
    ])
    result = run_decision_engine(flights, debug=True)
    # fallback was used
    assert result["debug"]["fallback_used"] is True
    # best flight comes from the diversity-filtered set (first unique → AirA, price=500)
    assert result["best_flight"]["airline"] == "AirA"
    assert result["best_flight"]["price"]   == 500.0


def test_fallback_diversity_excludes_duplicate_signature():
    """
    When multiple flights share the same (stops, airline), only the first
    (best-scored) one enters the fallback candidate list.
    """
    # 5 flights, all 3 stops, all same airline → only 1 enters fallback
    flights = _sorted_flights([
        _make_flight(stops=3, airline="SameAir", price=500.0 + i * 10, score=600.0 + i * 10)
        for i in range(5)
    ])
    result = run_decision_engine(flights)
    # Must not crash; best_flight comes from the single unique candidate
    assert result["best_flight"]["price"] == 500.0


def test_price_vs_median_in_meta():
    """meta.price_vs_median is the best flight's price divided by median, rounded to 2dp."""
    # All flights at same price → price_vs_median == 1.0
    flights = _sorted_flights([
        _make_flight(price=500.0, score=600.0 + i)
        for i in range(5)
    ])
    result = run_decision_engine(flights)
    assert "price_vs_median" in result["meta"]
    assert result["meta"]["price_vs_median"] == 1.0


def test_price_vs_median_good_deal_ratio():
    """price_vs_median reflects a below-median price correctly."""
    # best flight price=400, median will be ~500 (mix of 400 and 500s)
    flights = _sorted_flights(
        [_make_flight(price=400.0, score=450.0)]
        + [_make_flight(price=500.0, score=650.0 + i) for i in range(9)]
    )
    result = run_decision_engine(flights)
    median = 500.0  # median of [400, 500, 500, …, 500]
    expected = round(400.0 / median, 2)
    assert result["meta"]["price_vs_median"] == expected


def test_price_vs_median_none_when_no_median():
    """price_vs_median is None in meta when median_price is 0 (all prices are zero)."""
    flights = _sorted_flights([
        _make_flight(price=0.0, score=600.0 + i)
        for i in range(5)
    ])
    result = run_decision_engine(flights)
    assert result["meta"]["price_vs_median"] is None

