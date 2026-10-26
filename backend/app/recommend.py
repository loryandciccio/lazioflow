"""Orchestrazione di /recommend: categoria -> candidati -> live/trend -> ranking -> Top N con motivazioni."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import facilities as F
from .config import ranking_config
from .data_sources.salutelazio import live_status
from .geo import haversine_km
from .models import RecommendRequest
from .ranking import build_candidate, rank, to_dict
from .trend import trends

DISCLAIMER = ("LazioFlow non fa diagnosi e non sostituisce il triage sanitario: mostra strutture compatibili con il tipo "
              "di richiesta, ordinate per compatibilità e criterio selezionato, con viaggio e attesa osservata separati. In emergenza chiama il 112; per un "
              "consiglio sanitario non urgente il 116117.")
ESCALATION_112 = "Per questa richiesta non cerchiamo strutture: chiama subito il 112 (Numero Unico di Emergenza)."


class RecommendError(ValueError):
    pass


def _limits(cat: dict, ftype: str | None) -> list[str]:
    out = ["I reparti dei PS vengono dal flusso ministeriale posti letto 2023 (dato annuale): un reparto assente dalle fonti è 'non verificato', non 'assente'.",
           "Il tempo di viaggio è una stima dichiarata (linea d'aria × 1,3; 30 km/h nei primi 10 km, 60 oltre).",
           "L'attesa osservata è quanto sta aspettando adesso chi aspetta da più tempo nel codice indicato: non è una previsione della tua attesa."]
    if ftype in ("community_house", "community_hospital"):
        out.append("Case della Comunità: orari per sede o singolo servizio solo dove collegati a una scheda ASL; copertura parziale. Gli orari dei prelievi non descrivono tutta la sede: chiama prima.")
    if ftype == "pharmacy":
        out.append("Farmacie: h24/8–20 e turni di Roma; calendari provinciali per Viterbo, Rieti, Frosinone e Latina. Estrazione e abbinamenti parziali: un turno può prevedere reperibilità; consulta la fonte o chiama.")
    if cat.get("note"):
        out.append(cat["note"])
    return out


async def recommend(req: RecommendRequest) -> dict:
    cat = F.category(req.category)
    if not cat:
        raise RecommendError(f"categoria sconosciuta: {req.category}. Ammesse: {', '.join(F.categories())}")
    now = datetime.now(ZoneInfo("Europe/Rome"))   # orari/festivi in ora locale
    synthetic = bool(F.meta().get("synthetic"))
    base = {"synthetic": synthetic, "generated_at": now.astimezone(timezone.utc).isoformat(), "category": cat["id"], "category_label": cat["label"],
            "preference": req.preference, "facility_type": req.facility_type, "disclaimer":
            ("DEMO: dati sintetici, strutture fittizie. Non utilizzare per cercare assistenza sanitaria. " if synthetic else "") + DISCLAIMER}
    if cat.get("action") == "call_112" or not cat.get("allowed_types"):
        return {**base, "escalation": "112", "escalation_text": ESCALATION_112, "candidates_considered": 0,
                "recommendations": [], "limits": [cat.get("note", "")]}
    allowed = list(cat["allowed_types"])
    ftype = req.facility_type
    if ftype and ftype not in allowed:
        raise RecommendError(f"tipo {ftype} non ammesso per {cat['id']} (ammessi: {allowed})")
    if ftype is None:
        ftype = allowed[0]
    types = [ftype] + (["community_hospital"] if ftype == "community_house" else [])
    cfg = ranking_config()
    pool = F.by_type(*types)
    # pre-filtro per distanza per non calcolare compat su 1800 farmacie lontane
    near = [f for f in pool if f.get("lat") is not None and f.get("lng") is not None
            and haversine_km(req.location.lat, req.location.lng, f["lat"], f["lng"]) <= cfg["candidates"]["max_distance_km"]]
    live_map: dict = {}
    trend_map: dict = {}
    if ftype == "emergency_room":
        pre = [c for c in (build_candidate(f, req.location.lat, req.location.lng, cat, req.preference, now, None, None, req.age_group, cfg) for f in near) if c]
        pre.sort(key=lambda c: (c.compat.level, c.compat.prefer_rank, c.distance_km))
        n = cfg["candidates"]["live_fetch_top_n"]
        chosen = [c for c in pre if c.compat.level == 1][:n] + [c for c in pre if c.compat.level == 2][:max(3, n // 2)]
        eids = [F.emergency_id(c.facility) for c in chosen if F.emergency_id(c.facility)]
        live_map = await live_status(eids)
        trend_map = trends(eids)
        near = [c.facility for c in chosen]
    cands = []
    for f in near:
        eid = F.emergency_id(f)
        c = build_candidate(f, req.location.lat, req.location.lng, cat, req.preference, now,
                            live_map.get(eid), trend_map.get(eid), req.age_group, cfg)
        if c:
            cands.append(c)
    ordered = rank(cands, cfg)
    recs = [to_dict(c, i + 1) for i, c in enumerate(ordered[: req.limit])]
    return {**base, "escalation": None, "escalation_text": None, "candidates_considered": len(cands),
            "recommendations": recs, "limits": _limits(cat, ftype), "facility_type": ftype}
