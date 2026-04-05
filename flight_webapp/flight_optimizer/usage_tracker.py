"""
Tracks SerpApi API calls per calendar month.
Stored in serpapi_usage.json next to this file.
Resets automatically when the month rolls over.
Limit: 250 searches/month on the free plan.
Also allows live fetch from SerpApi.
"""

import json
import os
from datetime import datetime
import requests

_USAGE_FILE = os.path.join(os.path.dirname(__file__), "serpapi_usage.json")
MONTHLY_LIMIT = 250

# Load SERPAPI_API_KEY from environment or .env file
def _load_api_key() -> str | None:
    key = os.environ.get("SERPAPI_API_KEY")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    env_path = os.path.normpath(env_path)
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("SERPAPI_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return None

SERPAPI_KEY = _load_api_key()


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
    """Increment the local counter for the current month. Call once per real SerpApi request."""
    data = _load()
    current_month = datetime.now().strftime("%Y-%m")
    if data.get("month") != current_month:
        data = {"month": current_month, "count": 0}
    data["count"] += 1
    _save(data)
    return data["count"]


def get_usage() -> dict:
    """Local usage summary."""
    data = _load()
    current_month = datetime.now().strftime("%Y-%m")
    count = data.get("count", 0) if data.get("month") == current_month else 0
    remaining = max(0, MONTHLY_LIMIT - count)
    pct_used = round(count / MONTHLY_LIMIT * 100, 1)
    return {
        "count": count,
        "month": current_month,
        "limit": MONTHLY_LIMIT,
        "remaining": remaining,
        "pct_used": pct_used,
    }


def get_usage_live() -> dict:
    """Fetch live usage from SerpApi."""
    if not SERPAPI_KEY:
        raise RuntimeError("SERPAPI_KEY ist nicht gesetzt")

    url = f"https://serpapi.com/account?api_key={SERPAPI_KEY}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        month = datetime.now().strftime("%Y-%m")
        count = int(data.get("this_month_usage", 0))
        limit = int(data.get("searches_per_month", MONTHLY_LIMIT))
        remaining = max(0, limit - count)
        pct_used = round(count / limit * 100, 1)
        return {
            "count": count,
            "month": month,
            "limit": limit,
            "remaining": remaining,
            "pct_used": pct_used,
        }
    except Exception as e:
        print("Fehler beim Abrufen der Live-Usage:", e)
        month = datetime.now().strftime("%Y-%m")
        return {
            "count": 0,
            "month": month,
            "limit": MONTHLY_LIMIT,
            "remaining": MONTHLY_LIMIT,
            "pct_used": 0
        }