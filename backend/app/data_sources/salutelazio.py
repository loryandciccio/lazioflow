"""Stato live dei Pronto Soccorso da SaluteLazio (API pubblica non documentata), con cache breve e fallback
sull'ultimo snapshot del poller (data/lazioflow.db). Ogni risultato dichiara la sua freschezza:
  live        = risposta dell'API ottenuta adesso
  recent      = snapshot del poller entro freshness.recent_max_age_s
  stale       = snapshot più vecchio (usato, ma con avviso esplicito)
  unavailable = niente: né live né snapshot (es. Gemelli e Campus Bio-Medico: errore GIPSE 422)
Il payload dell'API non ha timestamp: `data_timestamp` è l'ora della nostra richiesta/poll.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import datetime, timezone

import httpx

from ..config import (DB_PATH, LIVE_CONCURRENCY, LIVE_DISABLED, LIVE_TIMEOUT_S, SALUTELAZIO_BASE,
                      SALUTELAZIO_HEADERS, SALUTELAZIO_SOURCE_URL, ranking_config)

_cache: dict[str, tuple[float, dict]] = {}
_last_error: dict[str, str] = {}
LIVE_BATCH_TIMEOUT_S = 12.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _groups_from_api(payload: dict) -> dict[str, dict]:
    """Non trasformare payload incompleti in un PS senza attesa."""
    if not isinstance(payload, dict) or not isinstance(payload.get("groups"), list):
        raise ValueError("payload senza gruppi validi")
    out = {}
    for g in payload.get("groups") or []:
        code = str(g["group"]["code"])
        if code in out:
            raise ValueError("gruppo duplicato")
        total = _nonnegative_int(g.get("total"))
        if total is None:
            raise ValueError("conteggio assente o non valido")
        out[code] = {"total": total, "avg_wait_s": _nonnegative_int(g.get("avgWaitSeconds")),
                     "max_wait_s": _nonnegative_int(g.get("maxWaitSeconds")), "label": (g["group"].get("labels") or {}).get("it")}
    required = ranking_config()["wait"]["pressure_codes"]
    if not all(code in out for code in required):
        raise ValueError("gruppi di attesa incompleti")
    return out


def _nonnegative_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
        return number if number >= 0 and float(value) == number else None
    except (TypeError, ValueError, OverflowError):
        return None


def _fallback_status(groups: dict, ts: str) -> dict | None:
    try:
        observed = datetime.fromisoformat(ts)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - observed).total_seconds()
    except (TypeError, ValueError):
        return None
    fr = ranking_config()["freshness"]
    if age < 0 or age > fr["stale_max_age_s"]:
        return None
    if age <= fr["recent_max_age_s"]:
        freshness, note = "recent", f"ultima osservazione disponibile ({round(age / 60)} min fa)"
    else:
        freshness, note = "stale", f"dato NON aggiornato: snapshot di {round(age / 60)} min fa"
    return _status(groups, freshness, observed.isoformat(), _now_iso(), note)


def _status(groups: dict, freshness: str, ts: str, retrieved_at: str, note: str | None = None) -> dict:
    return {"groups": groups, "freshness": freshness, "data_timestamp": ts, "retrieved_at": retrieved_at,
            "source_name": "SaluteLazio (Regione Lazio)", "source_url": SALUTELAZIO_SOURCE_URL, "note": note}


def unavailable(note: str) -> dict:
    return {"groups": None, "freshness": "unavailable", "data_timestamp": None, "retrieved_at": _now_iso(),
            "source_name": "SaluteLazio (Regione Lazio)", "source_url": SALUTELAZIO_SOURCE_URL, "note": note}


async def _fetch_one(client: httpx.AsyncClient, sem: asyncio.Semaphore, eid: str) -> dict | None:
    async with sem:
        try:
            r = await client.get(f"{SALUTELAZIO_BASE}/emergency-status", params={"facilityId": eid})
            r.raise_for_status()
            data = r.json()
            if "groups" not in data:
                raise ValueError("payload senza 'groups'")
            st = _status(_groups_from_api(data), "live", _now_iso(), _now_iso())
            _cache[eid] = (time.time(), st)
            _last_error.pop(eid, None)
            return st
        except Exception as e:  # rete, 422 GIPSE, WAF...
            _last_error[eid] = f"{type(e).__name__}: {str(e)[:120]}"
            return None


def snapshot_fallback(eid: str, conn: sqlite3.Connection | None = None) -> dict | None:
    """Ultimo snapshot del poller per un PS, con freshness recent/stale in base all'età."""
    own = conn is None
    try:
        if own:
            if not DB_PATH.exists():
                return None
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=0.2)
        row = conn.execute("SELECT MAX(ts) FROM ps_snapshots WHERE emergency_id=?", (eid,)).fetchone()
        if not row or not row[0]:
            return None
        ts = row[0]
        groups = {}
        for code, total, avg_w, max_w in conn.execute(
                "SELECT group_code, total, avg_wait_s, max_wait_s FROM ps_snapshots WHERE emergency_id=? AND ts=?", (eid, ts)):
            value = _nonnegative_int(total)
            if value is None:
                return None
            groups[str(code)] = {"total": value, "avg_wait_s": _nonnegative_int(avg_w),
                                 "max_wait_s": _nonnegative_int(max_w), "label": None}
        if not all(code in groups for code in ranking_config()["wait"]["pressure_codes"]):
            return None
        return _fallback_status(groups, ts)
    except (sqlite3.Error, OSError):
        return None
    finally:
        if own and conn is not None:
            conn.close()


async def live_status(emergency_ids: list[str]) -> dict[str, dict]:
    """Per ogni PS: live (cache o API) -> snapshot poller -> unavailable. Non solleva mai."""
    emergency_ids = list(dict.fromkeys(emergency_ids))
    out: dict[str, dict] = {}
    ttl = ranking_config()["freshness"]["live_cache_s"]
    todo = []
    for eid in emergency_ids:
        c = _cache.get(eid)
        if c and time.time() - c[0] <= ttl:
            out[eid] = c[1]
        else:
            todo.append(eid)
    if todo and not LIVE_DISABLED:
        sem = asyncio.Semaphore(LIVE_CONCURRENCY)
        try:
            async with httpx.AsyncClient(headers=SALUTELAZIO_HEADERS, timeout=LIVE_TIMEOUT_S) as client:
                tasks = [asyncio.create_task(_fetch_one(client, sem, eid)) for eid in todo]
                try:
                    done, pending = await asyncio.wait(tasks, timeout=LIVE_BATCH_TIMEOUT_S)
                    results = [task.result() if task in done else None for task in tasks]
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except (httpx.HTTPError, OSError):
            results = [None] * len(todo)
        for eid, st in zip(todo, results):
            if st:
                out[eid] = st
    conn = None
    try:
        if DB_PATH.exists():
            try:
                conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=0.2)
            except (sqlite3.Error, OSError):
                pass
        for eid in emergency_ids:
            if eid in out:
                continue
            snap = snapshot_fallback(eid, conn) if conn else None
            cached = _cache.get(eid)
            old_live = _fallback_status(cached[1]["groups"], cached[1]["data_timestamp"]) if cached else None
            available = [s for s in (snap, old_live) if s]
            out[eid] = max(available, key=lambda s: s["data_timestamp"]) if available else unavailable("stato live non disponibile")
    finally:
        if conn:
            conn.close()
    return out


def clear_cache() -> None:
    _cache.clear()
    _last_error.clear()
