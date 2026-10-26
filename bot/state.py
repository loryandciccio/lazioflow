"""Stato di sessione per utente (context.user_data) e logica di decisione PURA (testabile senza Telegram)."""
from __future__ import annotations

import time
from dataclasses import dataclass

from .config import LOCATION_TTL_S

MULTI_TYPE_HINT = {"community_house": "🏠 Casa della Comunità", "emergency_room": "🏥 Pronto Soccorso", "pharmacy": "💊 Farmacia"}
GENERIC_CATEGORY = "PROBLEMA_GENERICO_NON_URGENTE"
TYPE_TO_CATEGORY = {"emergency_room": GENERIC_CATEGORY, "community_house": "ASSISTENZA_TERRITORIALE", "pharmacy": "FARMACIA"}


def set_request(ud: dict, category: str, facility_type: str | None = None, age_group: str = "unknown", text: str = "",
                explicit_type: bool = False) -> None:
    clear_request(ud)
    ud["category"] = category
    ud["facility_type"] = facility_type
    ud["explicit_type"] = bool(facility_type) and explicit_type   # True solo se scelto dall'utente (pulsante/comando)
    ud["age_group"] = age_group
    # Il testo originale non viene conservato nella sessione.
    ud["session_expires_at"] = time.time() + LOCATION_TTL_S
    ud.setdefault("preference", "balanced")


def clear_request(ud: dict) -> None:
    """Azzera la richiesta corrente ma conserva posizione e preferenza (l'utente non deve reinviarle)."""
    for k in ("category", "facility_type", "explicit_type", "age_group", "last_text", "last_result", "last_recs", "offset",
              "allowed_types", "result_message_id", "pending_confirmation", "confirmation_message_id"):
        ud.pop(k, None)


def set_location(ud: dict, lat: float, lng: float) -> None:
    ud["session_expires_at"] = time.time() + LOCATION_TTL_S
    ud["location"] = {"lat": lat, "lng": lng, "ts": time.time()}


def location(ud: dict) -> tuple[float, float] | None:
    loc = ud.get("location")
    if loc and time.time() - loc["ts"] <= LOCATION_TTL_S:
        return loc["lat"], loc["lng"]
    ud.pop("location", None)
    return None


def expire_session(ud: dict, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if ud.get("session_expires_at", float("inf")) <= now:
        ud.clear()
        return True
    location(ud)  # rimuove fisicamente una posizione scaduta
    return False


def has_request(ud: dict) -> bool:
    return bool(ud.get("category"))


@dataclass
class Decision:
    action: str                 # SHOW_112 | SHOW_116117_AND_ASK | ASK_SERVICE_TYPE | ASK_TYPE_FOR_CATEGORY | ASK_LOCATION | RECOMMEND
    category: str | None = None
    facility_type: str | None = None
    age_group: str = "unknown"
    allowed_types: list[str] | None = None
    safety_message: str | None = None


def decide(understand: dict, categories: dict[str, dict], preselected_type: str | None = None, have_location: bool = False) -> Decision:
    """Dal risultato di /understand alla prossima azione. Il safety layer vince sempre."""
    safety, parsed = understand["safety"], understand["parse"]["parsed"]
    nxt = understand["next_step"]
    if nxt == "SHOW_112":
        return Decision("SHOW_112", safety_message=safety.get("message"))
    if nxt == "SHOW_116117_AND_ASK":
        return Decision("SHOW_116117_AND_ASK", category=parsed["category"], age_group=parsed["age_group"], safety_message=safety.get("message"))
    if nxt == "ASK_SERVICE_TYPE":
        return Decision("ASK_SERVICE_TYPE", age_group=parsed["age_group"], category=parsed.get("requested_service"))
    cat = categories.get(parsed["category"]) or {}
    allowed = list(cat.get("allowed_types") or [])
    if not allowed:  # EMERGENZA senza red flag deterministica: comunque 112 (vince la cautela)
        return Decision("SHOW_112", safety_message=safety.get("message"))
    ftype = preselected_type if preselected_type in allowed else None
    if ftype is None and parsed.get("requested_service") in allowed:
        ftype = parsed["requested_service"]
    if ftype is None and len(allowed) > 1:
        return Decision("ASK_TYPE_FOR_CATEGORY", category=parsed["category"], age_group=parsed["age_group"], allowed_types=allowed)
    ftype = ftype or allowed[0]
    return Decision("RECOMMEND" if have_location else "ASK_LOCATION", category=parsed["category"], facility_type=ftype, age_group=parsed["age_group"])


def category_for_explicit_type(ud: dict, ftype: str, categories: dict[str, dict]) -> str:
    """L'utente ha scelto ESPLICITAMENTE un tipo: se la categoria capita lo ammette la teniamo (filtra per reparto),
    altrimenti la categoria generica di quel tipo. Mai una scelta autonoma del sistema."""
    cat = ud.get("category")
    allowed = (categories.get(cat) or {}).get("allowed_types") or []
    if cat and cat not in ("EMERGENZA", "UNKNOWN") and ftype in allowed:
        return cat
    return TYPE_TO_CATEGORY[ftype]
