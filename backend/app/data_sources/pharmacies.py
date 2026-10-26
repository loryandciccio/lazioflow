"""Farmacie: disponibilità (STEP 3). Fonte orari: SOLO Comune di Roma (Ordine dei Farmacisti: h24 tutto l'anno,
h12 8-20, di turno oggi). Altrove nessun dato -> 'orario non verificato'. Distinguere sempre 'vicina' da 'aperta adesso'."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..calendar_it import is_weekend_or_holiday

NIGHT_START, NIGHT_END = 20, 8  # fascia in cui contano h24 e turni


def is_off_hours(now: datetime) -> bool:
    return now.hour >= NIGHT_START or now.hour < NIGHT_END or is_weekend_or_holiday(now.date(), rome=True)


def opening_status(facility: dict, now: datetime) -> dict:
    """`off_hours` dice al ranking se ha senso preferire le farmacie con apertura nota (notte/festivi); di giorno
    quasi tutte sono aperte e conta la distanza, con etichetta 'orario non verificato'."""
    from .pharmacy_regional import opening as provincial_opening
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("Europe/Rome"))
    provincial = provincial_opening(facility, now)
    if provincial:
        return {**provincial, "off_hours": is_off_hours(now.astimezone(ZoneInfo("Europe/Rome")))}
    op = facility.get("opening") or {}
    if now.tzinfo is not None:
        now = now.astimezone(ZoneInfo("Europe/Rome"))
    today = now.date().isoformat()
    op = dict(op)
    for kind, field in (("h24", "h24_all_year"), ("h12", "h12_8_20_all_year")):
        timestamp = op.get(kind + "_verified_at", op.get("retrieved_at"))
        if not timestamp:
            op[field] = False
            continue
        if timestamp:
            try:
                checked = datetime.fromisoformat(timestamp)
                elapsed = (now - checked).total_seconds()
            except (ValueError, TypeError):
                elapsed = float("inf")
            if not 0 <= elapsed <= 172800:
                op[field] = False
    on_duty = op.get("on_duty") or {}
    off = is_off_hours(now)
    evidence = {"source_url": op.get("source_url"), "retrieved_at": op.get("retrieved_at"),
                "checked_at": now.isoformat(), "timezone": "Europe/Rome",
                "evidence_label": "Elenco turni/orari consultato"}
    if op.get("h24_all_year"):
        return {**evidence, "status": "open", "known": True, "off_hours": off, "label": "aperta h24 tutto l'anno (Ordine Farmacisti Roma)"}
    if op.get("h12_8_20_all_year") and 8 <= now.hour < 20:
        return {**evidence, "status": "open", "known": True, "off_hours": off, "label": "aperta 8-20 tutto l'anno (Ordine Farmacisti Roma)"}
    from .source_utils import age
    duty_recent = 0 <= age(op.get("daily_retrieved_at") or op.get("retrieved_at"), now) <= 7200
    if on_duty.get("value") and on_duty.get("date") == today and duty_recent:
        return {**evidence, "source_url": op.get("daily_source_url") or evidence["source_url"],
                "retrieved_at": op.get("daily_retrieved_at") or evidence["retrieved_at"],
                "status": "unknown_hours", "known": False, "off_hours": off, "on_duty": True,
                "source_date": today, "label": "di turno oggi (Ordine Farmacisti Roma); fascia oraria non pubblicata: chiama prima"}
    if op.get("h12_8_20_all_year"):
        return {**evidence, "status": "unknown", "known": False, "off_hours": off,
                "label": "fuori dalla fascia verificata 8-20; eventuale turno notturno da verificare: chiama prima"}
    if on_duty.get("date") and on_duty.get("date") != today:
        return {**evidence, "status": "unknown", "known": False, "off_hours": off,
                "label": f"turni disponibili solo per il {on_duty['date']}: orario di oggi non verificato"}
    return {**evidence, "status": "unknown", "known": False, "off_hours": off, "label": "orario ordinario non disponibile nelle fonti collegate; consulta la scheda o chiama"}
