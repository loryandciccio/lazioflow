"""Scarica dall'API pubblica SaluteLazio (non documentata) anagrafica + dettaglio + stato live.

Uso:  python3 data/scripts/fetch_salutelazio.py            -> scrive data/raw/salutelazio/*.json
Endpoint (base https://server.salutelazio.it/server/external-services):
  GET /facility/structures/healthcare-facility-type?lang=it     tipologie (001 ASL, 002 Consultori, 003 Farmacie,
                                                                 006 Pronto soccorso, 007 Strutture per ricovero,
                                                                 008 Visite ed esami, 009 Studio medico)
  GET /facilities/structures/list?westLng&southLat&eastLng&northLat&zoom&lang&page&limit(max 200)&facilityTypeIds&text
  GET /facilities/structures/<url-slug>?lang=it                  dettaglio (serviceLabels, disciplineLabels, openingHours...)
  GET /facilities/structures/emergency-status?facilityId=<emergencyOrganizationId>   stato live PS
  GET /facilities/structures/suggestions/what?text=  |  /suggestions/where?text=
Nessuna autenticazione. Header Origin non necessario (verificato 10/09/2026).
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "salutelazio"
BASE = "https://server.salutelazio.it/server/external-services"
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Origin": "https://salutelazio.it"}
BBOX = {"westLng": 11.4, "southLat": 40.7, "eastLng": 14.1, "northLat": 42.9, "zoom": 8, "lang": "it"}
TYPES = {"001": "asl", "002": "consultori", "003": "farmacie", "006": "pronto_soccorso", "007": "ospedali", "008": "visite_esami"}


def get(path, params=None, retries=2):
    url = f"{BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:300]
            if e.code in (400, 422) or i == retries:
                return {"_error": e.code, "_body": body}
            time.sleep(1)
        except Exception as e:  # rete
            if i == retries:
                return {"_error": str(e)}
            time.sleep(1)


def list_type(code):
    items, page = [], 1
    while True:
        d = get("facilities/structures/list", {**BBOX, "page": page, "limit": 200, "facilityTypeIds": code})
        items += d.get("items", [])
        if len(items) >= (d.get("total") or 0) or not d.get("items"):
            return d.get("total"), items
        page += 1


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    json.dump(get("facility/structures/healthcare-facility-type", {"lang": "it"}), open(OUT / "facility_types.json", "w"), ensure_ascii=False, indent=1)
    lists = {}
    for code, name in TYPES.items():
        total, items = list_type(code)
        lists[code] = items
        json.dump({"fetched_at": ts, "facilityTypeId": code, "total": total, "items": items}, open(OUT / f"list_{code}_{name}.json", "w"), ensure_ascii=False, indent=1)
        print(f"{code} {name}: total={total} items={len(items)}", file=sys.stderr)
    # dettaglio PS + ospedali, stato live PS
    with ThreadPoolExecutor(8) as ex:
        ps = lists["006"]
        det = list(ex.map(lambda f: get(f"facilities/structures/{f['url']}", {"lang": "it"}), ps))
        st = list(ex.map(lambda f: get("facilities/structures/emergency-status", {"facilityId": f["emergencyOrganizationId"]}) if f.get("emergencyOrganizationId") else {"_error": "no emergencyOrganizationId"}, ps))
        osp = list(ex.map(lambda f: get(f"facilities/structures/{f['url']}", {"lang": "it"}), lists["007"]))
    json.dump({"fetched_at": ts, "items": [{"list": f, "detail": d, "status": s} for f, d, s in zip(ps, det, st)]}, open(OUT / "ps_detail_status.json", "w"), ensure_ascii=False, indent=1)
    json.dump({"fetched_at": ts, "items": osp}, open(OUT / "ospedali_detail.json", "w"), ensure_ascii=False, indent=1)
    ok = sum(1 for s in st if "groups" in s)
    print(f"PS stato live ok={ok}/{len(ps)}; errori: {[f['name'] for f, s in zip(ps, st) if 'groups' not in s]}", file=sys.stderr)


if __name__ == "__main__":
    main()
