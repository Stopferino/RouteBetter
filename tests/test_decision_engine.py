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
    """Fewer than 3 valid flights → confidence = LOW."""
    flights = _sorted_flights([
        _make_flight(price=400.0, score=550.0),
        _make_flight(price=500.0, score=650.0),
    ])
    result = run_decision_engine(flights)
    assert result["deal"]["confidence"] == "LOW"


def test_high_confidence_large_dataset():
    """5+ valid flights → confidence = HIGH."""
    flights = _sorted_flights([
        _make_flight(price=400.0 + i * 20, score=550.0 + i * 30)
        for i in range(6)
    ])
    result = run_decision_engine(flights)
    assert result["deal"]["confidence"] == "HIGH"


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
    assert result["deal"]["confidence"] in {"HIGH", "LOW"}

    # explanation constraints
    assert isinstance(result["explanation"], str)
    assert len(result["explanation"]) > 0

    # alternatives constraints
    assert isinstance(result["alternatives"], list)
    assert len(result["alternatives"]) <= 3

    # meta constraints
    assert "total_flights"  in result["meta"]
    assert "valid_flights"  in result["meta"]
    assert "premium_only"   in result["meta"]


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
