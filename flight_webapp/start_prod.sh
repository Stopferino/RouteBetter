#!/bin/bash
exec python3 -m uvicorn flight_webapp.app:app --host 0.0.0.0 --port "${PORT:-8000}"
