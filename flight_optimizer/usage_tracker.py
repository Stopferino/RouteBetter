"""
Tracks SerpApi API calls per calendar month.
Stored in serpapi_usage.json next to this file.
Resets automatically when the month rolls over.
Limit: 250 searches/month on the free plan.
"""

import json
import os
from datetime import datetime

_USAGE_FILE = os.path.join(os.path.dirname(__file__), "serpapi_usage.json")
MONTHLY_LIMIT = 250


def _load() -> dict:
    if os.path.exists(_USAGE_FILE):
        try:
            with open(_USAGE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"month": "", "count": 0}


def _save(data: dict) -> None:
    with open(_USAGE_FILE, "w") as f:
        json.dump(data, f)


def increment() -> int:
    """Increment the counter for the current month. Returns the new count.
    Call once per real SerpApi HTTP request (NOT for cache hits).
    """
    data = _load()
    current_month = datetime.now().strftime("%Y-%m")
    if data.get("month") != current_month:
        data = {"month": current_month, "count": 0}
    data["count"] += 1
    _save(data)
    return data["count"]


def get_usage() -> dict:
    """Returns usage dict: {count, month, limit, remaining, pct_used}."""
    data = _load()
    current_month = datetime.now().strftime("%Y-%m")
    if data.get("month") != current_month:
        count = 0
    else:
        count = data.get("count", 0)
    remaining = max(0, MONTHLY_LIMIT - count)
    pct_used = round(count / MONTHLY_LIMIT * 100, 1)
    return {
        "count": count,
        "month": current_month,
        "limit": MONTHLY_LIMIT,
        "remaining": remaining,
        "pct_used": pct_used,
    }
