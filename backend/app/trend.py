"""Trend recente di un PS dallo storico del poller (ps_snapshots, un giro ogni ~15 min).

Solo differenze OSSERVATE, mai previsioni. Per ogni PS:
  current, delta_15m, delta_30m, delta_60m  (persone in attesa nei codici pressure_codes, default 3-4-5)
  direction: increasing | stable | decreasing | insufficient_data
Regole (docs/FATTIBILITA.md §6): direction si calcola SOLO su delta_60m; serve uno snapshot recente
(<= trend.recent_max_age_min) e uno a 60 ± tolerance_min; crescente se delta >= abs_min E >= rel_min del valore
di un'ora fa (soglia assoluta E relativa: +2 su 3 persone è un'ambulanza, non un trend).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .config import DB_PATH, ranking_config


def _series(conn: sqlite3.Connection, eid: str, codes: tuple[str, ...], hours: float = 1.5) -> list[tuple[datetime, int]]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    q = (f"SELECT ts, SUM(total) FROM ps_snapshots WHERE emergency_id=? AND ts>=? "
         f"AND group_code IN ({','.join('?' * len(codes))}) GROUP BY ts ORDER BY ts")
    return [(datetime.fromisoformat(ts), tot or 0) for ts, tot in conn.execute(q, (eid, since, *codes))]


def _at(series: list[tuple[datetime, int]], target: datetime, tol_min: float) -> tuple[datetime, int] | None:
    if not series:
        return None
    best = min(series, key=lambda r: abs((r[0] - target).total_seconds()))
    return best if abs((best[0] - target).total_seconds()) <= tol_min * 60 else None


def trend_from_series(series: list[tuple[datetime, int]], now: datetime | None = None, cfg: dict | None = None) -> dict:
    cfg = cfg or ranking_config()["trend"]
    now = now or datetime.now(timezone.utc)
    base = {"current": None, "delta_15m": None, "delta_30m": None, "delta_60m": None,
            "direction": "insufficient_data", "samples": len(series), "observed_at": None, "text": None}
    if not series:
        return base
    t_now, v_now = series[-1]
    base["current"], base["observed_at"] = v_now, t_now.isoformat()
    if (now - t_now) > timedelta(minutes=cfg["recent_max_age_min"]):
        base["text"] = "nessuno snapshot recente"
        return base
    for m in (15, 30, 60):
        p = _at(series, t_now - timedelta(minutes=m), cfg["tolerance_min"])
        if p:
            base[f"delta_{m}m"] = v_now - p[1]
    p60 = _at(series, t_now - timedelta(minutes=60), cfg["tolerance_min"])
    if not p60:
        base["text"] = "manca lo snapshot di un'ora fa"
        return base
    delta = v_now - p60[1]
    rel = delta / p60[1] if p60[1] else (1.0 if delta > 0 else 0.0)
    if delta >= cfg["abs_min"] and rel >= cfg["rel_min"]:
        d = "increasing"
    elif delta <= -cfg["abs_min"] and rel <= -cfg["rel_min"]:
        d = "decreasing"
    else:
        d = "stable"
    minutes = round((t_now - p60[0]).total_seconds() / 60)
    base["direction"] = d
    base["text"] = f"negli ultimi {minutes} min le persone in attesa sono passate da {p60[1]} a {v_now} ({delta:+d})"
    return base


def trend(eid: str, conn: sqlite3.Connection | None = None) -> dict:
    codes = tuple(ranking_config()["wait"]["pressure_codes"])
    own = conn is None
    if own:
        if not DB_PATH.exists():
            return trend_from_series([])
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return trend_from_series(_series(conn, eid, codes))
    finally:
        if own:
            conn.close()


def trends(eids: list[str]) -> dict[str, dict]:
    if not DB_PATH.exists():
        return {e: trend_from_series([]) for e in eids}
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return {e: trend(e, conn) for e in eids}
    finally:
        conn.close()
