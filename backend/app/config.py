"""Configurazione backend: percorsi, parametri di ranking (config/ranking.yaml), costanti API SaluteLazio."""
from __future__ import annotations

import os
import json
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")   # il parser LLM gira in questo processo: senza questo ANTHROPIC_API_KEY non arriva

DATA_DIR = ROOT / "data"
FACILITIES_PATH = DATA_DIR / "normalized" / "facilities.json"
CATEGORIES_PATH = DATA_DIR / "normalized" / "categories.json"
SYNTHETIC_DATA = bool(json.loads(FACILITIES_PATH.read_text(encoding="utf-8")).get("meta", {}).get("synthetic"))
def database_path(value: str | None = None) -> Path:
    path = Path(value or os.getenv("LAZIOFLOW_DB") or DATA_DIR / "lazioflow.db").expanduser()
    return path if path.is_absolute() else ROOT / path


DB_PATH = database_path()
RANKING_PATH = ROOT / "config" / "ranking.yaml"

SALUTELAZIO_BASE = "https://server.salutelazio.it/server/external-services/facilities/structures"
SALUTELAZIO_HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://salutelazio.it", "Accept": "application/json"}
SALUTELAZIO_SOURCE_URL = "https://salutelazio.it"
LIVE_TIMEOUT_S = float(os.getenv("LIVE_TIMEOUT_S", "8"))
LIVE_CONCURRENCY = int(os.getenv("LIVE_CONCURRENCY", "8"))
LIVE_DISABLED = SYNTHETIC_DATA or os.getenv("LAZIOFLOW_LIVE", "0") == "0"


@lru_cache(maxsize=1)
def ranking_config() -> dict:
    with open(RANKING_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)
