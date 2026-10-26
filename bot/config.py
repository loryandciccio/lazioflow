"""Configurazione bot Telegram: tutto da .env (mai committato). Il bot parla SOLO col backend LazioFlow via HTTP."""
import os
import json
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
DEMO_MODE = bool(json.loads((ROOT / "data/normalized/facilities.json").read_text(encoding="utf-8")).get("meta", {}).get("synthetic"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
BACKEND_TIMEOUT_S = float(os.getenv("BACKEND_TIMEOUT_S", "25"))
LOCATION_TTL_S = int(os.getenv("LOCATION_TTL_S", str(45 * 60)))  # per quanto ricordiamo la posizione dell'utente
TOP_N = 3
ALT_N = 6
TZ = "Europe/Rome"
