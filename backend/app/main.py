"""LazioFlow backend (FastAPI). Unico componente che parla con SaluteLazio e col DB del poller.

Endpoint:
  GET  /health                 stato backend, poller, dataset
  GET  /categories             categorie chiuse (per bot e parser)
  GET  /facilities/{id}        scheda struttura (capabilities + fonti)
  GET  /ps/live                tutti i PS con stato live/snapshot + trend (per /rete e dashboard)
  POST /recommend              Top N gerarchico (spec §12)
  GET  /sources                fonti, timestamp e limiti del dataset
  /parse e /safety/check sono registrati dal workstream AI+Safety (backend/app/ai_routes.py) se presente.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import sqlite3
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from . import facilities as F
from .config import DB_PATH, ranking_config
from .data_sources.salutelazio import live_status
from .models import RecommendRequest, RecommendResponse
from .ranking import observed_wait
from .recommend import RecommendError, recommend
from .trend import trends

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lazioflow")
from .data_sources import pharmacy_live, pharmacy_regional, pharmacy_contacts, cdc_hours, cdc_regional, cdc_rome, updates


@asynccontextmanager
async def lifespan(app):
    updates.load_caches()
    task = asyncio.create_task(updates.run())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(lifespan=lifespan, title="LazioFlow API", version="0.1.0",
              description="Orientamento sanitario territoriale nel Lazio. Nessuna diagnosi, nessun triage.")


@app.get("/health")
def health():
    poller = None
    if DB_PATH.exists():
        conn = None
        try:
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=1)
            row = conn.execute("SELECT ts, ps_ok, ps_fail FROM poll_log ORDER BY ts DESC LIMIT 1").fetchone()
            n = conn.execute("SELECT COUNT(DISTINCT ts) FROM ps_snapshots").fetchone()[0]
            poller = {"last_poll": row[0] if row else None, "ps_ok": row[1] if row else None,
                      "ps_fail": row[2] if row else None, "snapshots": n}
        except sqlite3.Error as exc:
            log.warning("storico poller non leggibile: %s", type(exc).__name__)
            poller = {"status": "unavailable", "note": "Storico non leggibile: il backend usa i dati live quando disponibili."}
        finally:
            if conn is not None:
                conn.close()
    poll_age = None
    if poller and poller.get("last_poll"):
        try:
            observed = datetime.fromisoformat(poller["last_poll"])
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            poll_age = (datetime.now(timezone.utc) - observed).total_seconds()
        except (ValueError, TypeError):
            pass
    healthy = (poll_age is not None
               and 0 <= poll_age <= ranking_config()["freshness"]["recent_max_age_s"]
               and poller.get("ps_ok", 0) > 0 and poller.get("ps_fail", 0) == 0)
    return {"synthetic": bool(F.meta().get("synthetic")), "status": "ok" if healthy else "degraded", "poller_age_seconds": poll_age, "time": datetime.now(timezone.utc).isoformat(), "dataset": F.meta()["counts"],
            "dataset_built_at": F.meta()["built_at"], "poller": poller, "pharmacy_updates": pharmacy_live.status(), "cdc_updates": cdc_hours.status(), "cdc_regional": cdc_regional.status(),
            "provincial_pharmacy_updates": pharmacy_regional.status(), "update_workers": updates.status(),
            "rome_contacts": pharmacy_contacts.status(), "rome_service_hours": cdc_rome.status()}


@app.get("/categories")
def categories():
    return {"categories": list(F.categories().values())}


@app.get("/coverage")
def coverage():
    from .coverage import coverage as report
    return report()


@app.get("/facilities/{facility_id}")
def facility(facility_id: str):
    f = F.get(facility_id)
    if not f:
        raise HTTPException(404, "struttura non trovata")
    return f


@app.get("/ps/live")
async def ps_live():
    cfg = ranking_config()
    ps = F.by_type("emergency_room")
    eids = [F.emergency_id(f) for f in ps if F.emergency_id(f)]
    live = await live_status(eids)
    tr = trends(eids)
    out = []
    for f in ps:
        eid = F.emergency_id(f)
        st = live.get(eid) or {}
        wait_min, waiting, code = observed_wait(st, cfg)
        out.append({"facility_id": f["facility_id"], "emergency_id": eid, "name": f["name"], "lat": f["lat"], "lng": f["lng"],
                    "ps_scope": f.get("ps_scope"), "freshness": st.get("freshness", "unavailable"),
                    "data_timestamp": st.get("data_timestamp"), "groups": st.get("groups"), "total_waiting": waiting,
                    "observed_wait_minutes": None if wait_min is None else round(wait_min), "observed_wait_code": code,
                    "trend": tr.get(eid), "note": st.get("note")})
    return {"synthetic": bool(F.meta().get("synthetic")), "generated_at": datetime.now(timezone.utc).isoformat(), "source": "Synthetic demo catalogue" if F.meta().get("synthetic") else "SaluteLazio emergency-status + poller",
            "items": out}


@app.post("/recommend", response_model=RecommendResponse)
async def post_recommend(req: RecommendRequest):
    try:
        res = await recommend(req)
    except RecommendError as e:
        raise HTTPException(400, str(e))
    log.info("recommend category=%s type=%s pref=%s considered=%s top=%s", res["category"], res["facility_type"],
             res["preference"], res["candidates_considered"], [r["facility_id"] for r in res["recommendations"]])
    return res


@app.get("/sources")
def sources():
    m = F.meta()
    if m.get("synthetic"):
        return {"synthetic": True, "dataset_built_at": m["built_at"], "counts": m["counts"],
                "ps_join": {}, "ranking_parameters": ranking_config(),
                "sources": [{"name": "Synthetic demo catalogue", "url": None,
                             "what": "Fictional records, generated for demonstration", "freshness": "static"}],
                "limits": ["DEMO: strutture fittizie, non utilizzare per cercare assistenza sanitaria.",
                           "Nessun dato reale o stato live incluso. I connettori esterni sono disabilitati con questo catalogo."]}
    return {"dataset_built_at": m["built_at"], "counts": m["counts"], "ps_join": m.get("ps_join"),
            "ranking_parameters": ranking_config(),
            "pharmacy_updates": pharmacy_live.status(), "cdc_updates": cdc_hours.status(), "cdc_regional": cdc_regional.status(), "provincial_pharmacy_updates": pharmacy_regional.status(),
            "rome_contacts": pharmacy_contacts.status(), "rome_service_hours": cdc_rome.status(),
            "sources": [
                {"name": "SaluteLazio API emergency-status", "url": "https://salutelazio.it", "what": "stato live PS (54/56)", "freshness": "live"},
                {"name": "Poller LazioFlow", "url": None, "what": "storico: intervallo predefinito 5 minuti; stato effettivo in /health", "freshness": "recent"},
                {"name": "Ministero della Salute — posti letto per disciplina 2023", "url": "https://www.dati.salute.gov.it/it/dataset/posti-letto-stabilimento-ospedaliero-e-disciplina-2023/", "what": "reparti dei PS", "freshness": "static"},
                {"name": "Ministero della Salute — rete emergenza ospedaliera 2025", "url": "https://www.salute.gov.it/new/it/banche-dati/elenco-strutture-della-rete-dellemergenza-ospedaliera/", "what": "PS/DEA I/DEA II, PS pediatrico", "freshness": "static"},
                {"name": "Regione Lazio DGR 869/2023 All. 1 tab. 6.6", "url": "https://www.regione.lazio.it/sites/default/files/documentazione/2024/SAN-DGR-869-07-12-2023-Allegato-1.pdf", "what": "reti trauma/ictus/emodinamica (trascrizione manuale)", "freshness": "static"},
                {"name": "Curalazio + SaluteLazio — Case della Comunità", "url": "https://salutelazio.it/it/servizi/case-della-comunita", "what": "catalogo territoriale; schede regionali aggiornate ogni giorno, documenti dei servizi quando associati", "freshness": "vedi cdc_regional"},
                {"name": "Ministero della Salute — farmacie", "url": "https://www.dati.salute.gov.it/it/dataset/farmacie/", "what": "anagrafica 1804 farmacie", "freshness": "static"},
                {"name": "Ordine dei Farmacisti di Roma", "url": "https://www.ordinefarmacistiroma.it", "what": "h24/h12 aggiornati giornalmente, turni ogni ora (solo Roma, abbinamenti parziali)", "freshness": "vedi pharmacy_updates"},
                *[{"name": spec['name'], "url": spec['url'], "what": "calendari provinciali: consultazione ogni 6 ore; turni estratti solo per formati riconosciuti, altrimenti documento ufficiale", "freshness": "vedi provincial_pharmacy_updates"} for code, spec in pharmacy_regional.SOURCES.items() if code != 'RM'],
            ],
            "limits": ["Nessuna diagnosi, nessun codice triage, nessuna previsione.",
                       "Gemelli e Campus Bio-Medico non espongono lo stato live (errore GIPSE 422): dichiarati 'non disponibile'.",
                       "Orari CdC: schede ASL integrate per alcune sedi; orari ordinari farmacie non coperti dagli elenchi turni/h24."]}


from .security import AccessGuard
app.add_middleware(AccessGuard)

from .ai_routes import router as ai_router  # noqa: E402
app.include_router(ai_router)
