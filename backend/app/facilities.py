"""Accesso al dataset normalizzato (data/normalized/facilities.json) e alle categorie chiuse (categories.json)."""
from __future__ import annotations

import json
from functools import lru_cache

from .config import CATEGORIES_PATH, FACILITIES_PATH


@lru_cache(maxsize=1)
def _load() -> dict:
    with open(FACILITIES_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _categories() -> dict:
    with open(CATEGORIES_PATH, encoding="utf-8") as f:
        d = json.load(f)
    return {c["id"]: c for c in d["categories"]}


def meta() -> dict:
    return _load()["meta"]


def all_facilities() -> list[dict]:
    return _load()["facilities"]


@lru_cache(maxsize=1)
def _by_id() -> dict[str, dict]:
    return {f["facility_id"]: f for f in all_facilities()}


def get(facility_id: str) -> dict | None:
    item = _by_id().get(facility_id)
    return _overlay(item) if item else None


def by_type(*types: str) -> list[dict]:
    return [_overlay(f) for f in all_facilities() if f["type"] in types]


def _overlay(item: dict) -> dict:
    from .data_sources.pharmacy_live import overlay as pharmacy_overlay
    from .data_sources.cdc_regional import overlay as regional_overlay
    from .data_sources.pharmacy_contacts import overlay as contacts_overlay
    return regional_overlay(contacts_overlay(pharmacy_overlay(item)))


def emergency_id(f: dict) -> str | None:
    return (f.get("ids") or {}).get("salutelazio_emergency_id")


def categories() -> dict[str, dict]:
    return _categories()


def category(cat_id: str) -> dict | None:
    return _categories().get(cat_id)
