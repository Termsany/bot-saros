"""The strategies, from lib/strategies.json — the one list the site, the API and the scripts share (development-plan 3.4).

API side only: bot.py and the modules the real-money bot imports keep their own lists (no file to read at start-up on
the order path); backend/tests/test_strategy_catalog.py fails CI when any of them drifts from this file.
"""
import json, os
from pathlib import Path

PATH = Path(os.getenv("RAQM_STRATEGIES_JSON") or Path(__file__).resolve().parent.parent.parent / "lib" / "strategies.json")
CATALOG = tuple(json.loads(PATH.read_text(encoding="utf-8"))["strategies"])

IDS = tuple(s["id"] for s in CATALOG)                                   # every strategy, in the plans' order
PLANNED = tuple(s["id"] for s in CATALOG if s["planned"])               # what the plans unlock, in order
NAME_AR = {s["id"]: s["nameAr"] for s in CATALOG}
LIVE_FILE = {s["id"]: s["live"] for s in CATALOG}                       # the bot's status file, without .json
DEMO_SAMPLE = {s["id"]: s["demoSample"] for s in CATALOG}
