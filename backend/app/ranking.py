"""Ranking gerarchico: compatibilità, disponibilità e criterio scelto.
Balanced: dati recenti prima, poi viaggio; attesa osservata come spareggio.
Nearest: viaggio. Less_crowded: attesa osservata recente.
Dati stale visibili ma esclusi dal criterio; nessuna previsione di attesa.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from .config import ranking_config
from .data_sources import cdc, pharmacies
from .geo import fmt_km, haversine_km, maps_link, travel_minutes
from .routing import Compatibility, compatibility

PRESET_LABELS = {"balanced": "Equilibrato", "nearest": "Più vicino", "less_crowded": "Attesa osservata"}


@dataclass
class Candidate:
    facility: dict
    distance_km: float
    compat: Compatibility
    opening: dict | None
    live: dict | None
    trend: dict | None
    travel_min: float
    wait_min: float | None
    waiting_total: int | None
    wait_code: str | None
    estimated_min: float | None
    preset: str
    reasons: list[str]
    warnings: list[str]


def observed_wait(live: dict | None, cfg: dict) -> tuple[float | None, int | None, str | None]:
    """(attesa osservata in minuti, persone in attesa nei codici di pressione, codice usato). None se nessun dato."""
    if not live or not live.get("groups"):
        return None, None, None
    g = live["groups"]
    if not isinstance(g, dict):
        return None, None, None
    codes = set(cfg["wait"]["pressure_codes"]) | set(cfg["wait"]["codes_priority"])
    if any(not isinstance(g.get(c), dict) or not isinstance(g[c].get("total"), int)
           or isinstance(g[c].get("total"), bool) or g[c]["total"] < 0 for c in codes):
        return None, None, None
    waiting = sum(g[c]["total"] for c in cfg["wait"]["pressure_codes"])
    for code in cfg["wait"]["codes_priority"]:
        grp = g.get(code)
        if grp and int(grp.get("total") or 0) > 0:
            maximum = grp.get("max_wait_s")
            if not isinstance(maximum, (int, float)) or isinstance(maximum, bool) or not math.isfinite(maximum) or maximum < 0:
                return None, waiting, code
            return maximum / 60.0, waiting, code
    return 0.0, waiting, None


def _opening(f: dict, now: datetime) -> dict | None:
    if f["type"] in ("community_house", "community_hospital"):
        return cdc.opening_status(f, now)
    if f["type"] == "pharmacy":
        return pharmacies.opening_status(f, now)
    return {"status": "open", "known": True, "label": "Pronto Soccorso: aperto h24"}


def build_candidate(f: dict, user_lat: float, user_lng: float, category: dict, preset: str, now: datetime,
                    live: dict | None, trend: dict | None, age_group: str | None, cfg: dict | None = None) -> Candidate | None:
    cfg = cfg or ranking_config()
    compat = compatibility(f, category, age_group)
    if not compat.compatible:
        return None
    if f.get("lat") is None or f.get("lng") is None:
        return None
    if not all(isinstance(f[k], (int, float)) and math.isfinite(f[k]) for k in ("lat", "lng")):
        return None
    km = haversine_km(user_lat, user_lng, f["lat"], f["lng"])
    if km > cfg["candidates"]["max_distance_km"]:
        return None
    opening = _opening(f, now)
    travel = travel_minutes(km, cfg)
    wait_min, waiting, code = observed_wait(live, cfg) if f["type"] == "emergency_room" else (None, None, None)
    if f["type"] != "emergency_room":
        preset = "nearest"  # Farmacie e CdC non pubblicano attese: conta il viaggio.
    usable_wait = wait_min is not None and (live or {}).get("freshness") in ("live", "recent")
    if preset == "nearest":
        est = travel
    elif preset == "balanced":
        est = travel if usable_wait else None
    else:
        est = wait_min if usable_wait else None
    reasons, warnings = list(compat.reasons), []
    reasons.append(f"distanza {fmt_km(km)} (viaggio stimato ~{round(travel)} min, velocità media dichiarata)")
    if f["type"] == "emergency_room":
        if wait_min is None:
            if waiting is None:
                warnings.append("stato live non disponibile o incompleto: nessun dato affidabile sull'attesa")
            else:
                warnings.append("durata dell'attesa osservata non disponibile")
                reasons.append(f"{waiting} persone in attesa (codici 3-5)")
        else:
            fr = (live or {}).get("freshness")
            if code:
                reasons.append(f"attesa osservata: la persona che aspetta da più tempo nel codice {code} è lì da ~{round(wait_min)} min")
                reasons.append(f"{waiting} persone in attesa (codici 3-5)")
            else:
                reasons.append("nessuno in attesa nei codici 3-5 al momento dell'osservazione")
            if fr == "stale":
                warnings.append((live or {}).get("note") or "dato non aggiornato")
            elif fr == "recent":
                reasons.append((live or {}).get("note") or "ultimo giro del poller")
        if trend and trend.get("direction") not in (None, "insufficient_data"):
            lab = {"increasing": "in aumento", "decreasing": "in diminuzione", "stable": "stabile"}[trend["direction"]]
            reasons.append(f"trend ultima ora {lab} ({trend['delta_60m']:+d} persone osservate)")
    if opening:
        if opening["status"] == "closed":
            warnings.append(opening["label"])
        elif opening["known"]:
            reasons.append(opening["label"])
        else:
            warnings.append(opening["label"])
    if compat.level == 2:
        warnings.append("requisito di reparto non verificato: contatta la struttura per confermare il servizio")
    if f["type"] == "pharmacy":
        warnings.append("posizione indicativa da fonte pubblica; verifica l'indirizzo prima di partire")
    return Candidate(f, km, compat, opening, live, trend, travel, wait_min, waiting, code, est, preset, reasons, warnings)


def sort_key(c: Candidate, cfg: dict) -> tuple:
    p = cfg["presets"][c.preset]
    closed_known = 1 if (c.opening and c.opening["status"] == "closed") else 0
    open_unknown = 2
    if c.opening and c.opening.get("off_hours") and c.distance_km <= cfg["candidates"]["pharmacy_known_open_radius_km"]:
        if c.opening["status"] == "open":
            open_unknown = 0
        elif c.opening.get("on_duty"):
            open_unknown = 1
    usable_wait = c.wait_min is not None and (c.live or {}).get("freshness") in ("live", "recent")
    wait_unknown = 1 if (p["wait"] and not usable_wait) else 0
    est = c.estimated_min if c.estimated_min is not None else c.travel_min
    return (c.compat.level, c.compat.prefer_rank, closed_known, wait_unknown, open_unknown if c.facility["type"] == "pharmacy" else 0,
            round(est, 1), c.wait_min if usable_wait and p["wait"] else 10**6,
            c.waiting_total if usable_wait and p["wait"] and c.waiting_total is not None else 10**6, round(c.distance_km, 2))


def rank(cands: list[Candidate], cfg: dict | None = None) -> list[Candidate]:
    cfg = cfg or ranking_config()
    ordered = sorted(cands, key=lambda c: sort_key(c, cfg))
    # motivazioni relative (solo per i primi): "pressione inferiore alle alternative"
    with_wait = [c for c in ordered if c.wait_min is not None and (c.live or {}).get("freshness") in ("live", "recent")]
    if len(with_wait) >= 2:
        best = min(with_wait, key=lambda c: c.wait_min)
        if best.wait_min < sorted(c.wait_min for c in with_wait)[1]:
            best.reasons.append("attesa osservata inferiore alle alternative")
    return ordered


def to_dict(c: Candidate, rank_pos: int) -> dict:
    f = c.facility
    live_out = None
    if f["type"] == "emergency_room":
        live_out = {"available": c.live is not None and bool(c.live.get("groups")),
                    "freshness": (c.live or {}).get("freshness", "unavailable"),
                    "total_waiting": c.waiting_total,
                    "observed_wait_minutes": None if c.wait_min is None else round(c.wait_min),
                    "observed_wait_code": c.wait_code,
                    "groups": (c.live or {}).get("groups"),
                    "data_timestamp": (c.live or {}).get("data_timestamp"),
                    "retrieved_at": (c.live or {}).get("retrieved_at"),
                    "note": (c.live or {}).get("note")}
    cls = f.get("classification") or {}
    return {
        "rank": rank_pos, "facility_id": f["facility_id"], "name": f["name"], "type": f["type"],
        "ps_scope": f.get("ps_scope"), "address": f.get("address"), "phone": f.get("phone"), "asl": f.get("asl"),
        "lat": f["lat"], "lng": f["lng"], "distance_km": round(c.distance_km, 1),
        "maps_url": "" if f.get("synthetic") else maps_link(f["lat"], f["lng"], f.get("address") if f["type"] == "pharmacy" else None),
        "compatible": True, "compatibility_level": c.compat.level, "compatibility_confidence": c.compat.confidence,
        "compatibility_sources": c.compat.sources,
        "classification": {k: cls.get(k) for k in ("ps_type", "dea_level", "pediatric_ps", "trauma_level", "stroke_unit") if cls.get(k) is not None},
        "opening": c.opening, "live": live_out, "trend": c.trend,
        "score": {"mode": c.preset, "mode_label": PRESET_LABELS[c.preset],
                  "travel_minutes": round(c.travel_min), "wait_minutes": None if c.wait_min is None else round(c.wait_min),
                  "estimated_minutes": None,  # Non stimiamo il tempo complessivo di accesso alle cure.
                  "wait_used_for_ranking": c.preset != "nearest" and c.wait_min is not None and (c.live or {}).get("freshness") in ("live", "recent"),
                  "formula": {"balanced": "dati recenti prima, poi viaggio stimato; attesa osservata a parità di viaggio", "nearest": "minuti = viaggio stimato",
                              "less_crowded": "attesa osservata recente; senza dato utilizzabile, viaggio stimato"}[c.preset] + " (nessun peso; parametri in config/ranking.yaml)"},
        "reasons": c.reasons, "warnings": c.warnings,
        "sources": _sources(c),
    }


def _sources(c: Candidate) -> list[dict]:
    f = c.facility
    if f.get("synthetic"):
        return [{"source_name": "Synthetic demo catalogue", "source_url": None,
                 "retrieved_at": f.get("updated_at"), "data_timestamp": None,
                 "freshness": "static", "what": "Fictional facility; not real healthcare information"}]
    out = []
    if f["type"] == "emergency_room":
        out.append({"source_name": "SaluteLazio (Regione Lazio)", "source_url": "https://salutelazio.it",
                    "retrieved_at": (c.live or {}).get("retrieved_at"), "data_timestamp": (c.live or {}).get("data_timestamp"),
                    "freshness": (c.live or {}).get("freshness", "unavailable"), "what": "stato live PS (persone in attesa, attese osservate)"})
    for k, v in (f.get("source") or {}).items():
        if isinstance(v, str) and v.startswith("http"):
            out.append({"source_name": k, "source_url": v, "retrieved_at": f.get("updated_at"), "data_timestamp": None,
                        "freshness": "static", "what": "anagrafica"})
    for cap, src in (c.compat.sources or {}).items():
        out.append({"source_name": src, "source_url": None, "retrieved_at": f.get("updated_at"), "data_timestamp": None,
                    "freshness": "static", "what": f"capability {cap}"})
    return out
