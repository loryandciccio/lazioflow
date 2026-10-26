"""Distanze, tempo di viaggio stimato (parametri dichiarati) e link mappa."""
from __future__ import annotations

import math
from urllib.parse import urlencode


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def travel_minutes(km_air: float, cfg: dict) -> float:
    """Stima dichiarata: km stradali = km aria × road_factor; 30 km/h sui primi 10 km, 60 oltre (config/ranking.yaml)."""
    t = cfg["travel"]
    road = km_air * t["road_factor"]
    first = min(road, 10.0)
    beyond = max(road - 10.0, 0.0)
    return first / t["speed_kmh_first_10km"] * 60 + beyond / t["speed_kmh_beyond"] * 60


def maps_link(lat: float, lng: float, address: str | None = None) -> str:
    return "https://www.google.com/maps/dir/?" + urlencode({"api": 1, "destination": address or f"{lat},{lng}"})


def fmt_km(km: float) -> str:
    return f"{km * 1000:.0f} m" if km < 1 else f"{km:.1f} km".replace(".", ",")
