"""
Flight Optimizer - Entry point
Run with: python run_optimizer.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flight_optimizer.main import main

if __name__ == "__main__":
    main()
