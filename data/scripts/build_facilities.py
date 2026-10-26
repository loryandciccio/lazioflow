"""Costruisce data/normalized/facilities.json (schema unico) + ps_capabilities.csv unendo le fonti in data/raw/.

Join PS -> reparti/reti:
  SaluteLazio emergency-status.facilityId  (es. "120045-01", "12021602-01", "12090600-39PED")
    -> codice HSP struttura (6 cifre) + subcodice (2 cifre, se presenti 8 cifre prima del '-')
    -> Ministero posti letto 2023 (Codice struttura, Subcodice)       => reparti (capabilities)
    -> Ministero rete emergenza 2025 (Codice struttura, Subcodice)     => PS/DEA1/DEA2, flag PS pediatrico
    -> Regione Lazio DGR 869/2023 tab. 6.6 (codice 8 cifre)            => trauma CTS/CTZ/PST, UTN, emodinamica, perinatale
Uso: python3 data/scripts/build_facilities.py
"""
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "normalized"
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

# Ministero ha rinumerato alcune strutture: SaluteLazio/rete emergenza 2025 usano il codice nuovo, posti letto 2023 e DGR 869 quello vecchio
HSP_ALIAS = {"120307": "120180", "120308": "120294"}  # Aurelia Hospital, Policlinico Casilino
# PS senza stato live (GIPSE error 422): codice HSP preso dalla rete emergenza 2025
HSP_MANUAL = {"Pronto Soccorso Policlinico Gemelli": ("120905", "01"), "Pronto Soccorso Campus Bio-Medico": ("120915", "")}
DISCIPLINE_CAP = {
    "36": "orthopedics_trauma", "39": "pediatrics", "08": "cardiology", "50": "coronary_unit", "32": "neurology",
    "30": "neurosurgery", "37": "obstetrics_gynecology", "34": "ophthalmology", "38": "ent", "09": "general_surgery",
    "49": "intensive_care", "14": "vascular_surgery", "43": "urology", "40": "psychiatry", "62": "neonatology",
    "73": "neonatal_intensive_care", "10": "maxillofacial_surgery", "11": "pediatric_surgery", "13": "thoracic_surgery",
    "07": "cardiac_surgery", "24": "infectious_diseases", "52": "dermatology", "58": "gastroenterology",
    "68": "pneumology", "29": "nephrology", "47": "burns_unit", "28": "spinal_unit", "26": "internal_medicine",
    "21": "geriatrics", "18": "hematology", "64": "oncology", "33": "child_neuropsychiatry",
}
SCOPE_BY_NAME = [
    ("pediatric", r"pediatric|bambino ges"), ("ophthalmic", r"oculistic|oftalmic"), ("dental", r"odontoiatric"),
    ("obstetric", r"ostetric"), ("hematologic", r"ematologic"), ("orthopedic", r"\bcto\b|icot"),
]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9 ]+", " ", s).split()


def address_key(address):
    """Confronto dell'indirizzo completo, inclusi tutti i civici: 8 non coincide con 842."""
    address = re.split(r"\b\d{5}\b", address or "")[0]
    tokens = norm(address)
    ignored = {"VIA", "VIALE", "PIAZZA", "PIAZZALE", "LARGO", "CORSO", "VICOLO",
               "DI", "DEL", "DELLA", "DELLE", "DEGLI", "DEI", "D", "LE", "V"}
    # Unifica 58/b, 58 B e 58B mantenendo il suffisso del civico.
    key = " ".join(t for t in tokens if t not in ignored)
    return re.sub(r"(\d)\s+([A-Z])\b", r"\1\2", key)


def pdf_address(row):
    line = row["ragione_sociale_e_indirizzo"]
    match = re.search(r"\b(?:VIALE|VIA|PIAZZALE|PIAZZA|LARGO|CORSO|VICOLO)\b", line, re.I)
    return address_key(line[match.start():]) if match else ""


def valid_lazio_coords(lat, lng):
    return lat is not None and lng is not None and 40.7 <= lat <= 42.9 and 11.4 <= lng <= 14.1


def parse_hsp(fid):
    m = re.match(r"^(\d{6})(\d{2})?", (fid or "").replace(" ", ""))
    return (m.group(1), m.group(2) or "") if m else (None, None)


def read_csv(path, **kw):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, **kw))


def load_sources():
    pl = defaultdict(dict)
    for r in read_csv(RAW / "minsal" / "posti_letto_2023_lazio.csv"):
        k = (r["Codice struttura"], r["Subcodice"])
        pl[k].setdefault("_name", r["Denominazione Struttura/Stabilimento"])
        pl[k][r["Codice disciplina"]] = {"name": r["Descrizione disciplina"].title(), "beds": int(r["Totale posti letto"] or 0)}
    em = {(r["Codice struttura"], r["Subcodice"]): r for r in read_csv(RAW / "minsal" / "strutture_emergenza_2025_lazio.csv")}
    dgr = {r["codice_hsp"]: r for r in read_csv(RAW / "regione_lazio" / "dgr869_2023_reti_tempo_dipendenti.csv")}
    return pl, em, dgr


def lookup(table, s, sub, extra=()):
    for k in [(s, sub), (s, ""), (s, "01"), *extra]:
        if k in table:
            return k
    c = [k for k in table if k[0] == s]
    return c[0] if len(c) == 1 else None


def build_ps(pl, em, dgr):
    src = json.load(open(RAW / "salutelazio" / "ps_detail_status.json"))
    out, rows = [], []
    # ospedali che hanno un PS pediatrico censito come voce separata su SaluteLazio (es. Umberto I): il flag ministeriale
    # "PS pediatrico" (a livello di ospedale) va messo solo su quella voce, non sul PS generale o sugli altri PS specialistici
    ped_hosp = {parse_hsp(it["status"].get("facilityId"))[0] for it in src["items"] if re.search(r"pediatric", it["list"]["name"], re.I)}
    for it in src["items"]:
        f, d, st = it["list"], it["detail"], it["status"]
        s, sub = parse_hsp(st.get("facilityId"))
        if not s and f["name"] in HSP_MANUAL:
            s, sub = HSP_MANUAL[f["name"]]
        s_old = HSP_ALIAS.get(s, s)
        k_pl = lookup(pl, s_old, sub) if s else None
        k_em = lookup(em, s, sub) if s else None
        k_dgr = next((k for k in (s_old + (sub or "00"), s_old + "00", s_old + "01") if k in dgr), None) if s else None
        caps, cap_src = ["emergency_room"], {"emergency_room": "salutelazio:list 006"}
        beds = {}
        if k_pl:
            for code, v in pl[k_pl].items():
                if code.startswith("_"):
                    continue
                beds[code] = v
                if code in DISCIPLINE_CAP:
                    caps.append(DISCIPLINE_CAP[code])
                    cap_src[DISCIPLINE_CAP[code]] = "minsal:posti_letto_2023"
        cls = {"ps_type": None, "dea_level": None, "pediatric_ps": False, "trauma_level": None, "trauma_ped_level": None,
               "stroke_unit": None, "cardio_network": None, "perinatal_level": None, "pediatric_emergency_role": None}
        if k_em:
            lv = em[k_em]["Livello Emergenza"]
            cls["ps_type"] = {"PS": "PS", "DEA1": "DEA I", "DEA2": "DEA II"}.get(lv, lv)
            cls["dea_level"] = {"PS": 0, "DEA1": 1, "DEA2": 2}.get(lv)
            is_ped_name = bool(re.search(r"pediatric|bambino ges", f["name"], re.I))
            cls["pediatric_ps"] = em[k_em]["Pronto Soccorso Pediatrico"].strip() == "X" and (is_ped_name or s not in ped_hosp) and not re.search(r"oculist|odontoiatr|ostetric|ematolog", f["name"], re.I)
        if k_dgr:
            g = dgr[k_dgr]
            cls.update(trauma_level=g["trauma_adulti"] or None, trauma_ped_level=g["trauma_pediatrico"] or None,
                       stroke_unit=g["ictus"] or None, cardio_network=g["cardio"] or None,
                       perinatal_level=g["perinatale"] or None, pediatric_emergency_role=g["emergenza_pediatrica"] or None)
            if not cls["ps_type"]:
                cls["ps_type"] = g["emergenza"] or None
            if g["emergenza"] in ("PS specialistico", "PS disagiato"):
                cls["ps_type"] = g["emergenza"]
        for cap, cond, why in [
            ("trauma_network", cls["trauma_level"], "regione_lazio:dgr869_2023 (trauma adulti)"),
            ("pediatric_trauma_network", cls["trauma_ped_level"], "regione_lazio:dgr869_2023 (trauma pediatrico)"),
            ("stroke_unit", cls["stroke_unit"], "regione_lazio:dgr869_2023 (rete ictus)"),
            ("cath_lab", cls["cardio_network"] in ("CE", "CEC"), "regione_lazio:dgr869_2023 (emodinamica)"),
            ("pediatric_emergency_room", cls["pediatric_ps"], "minsal:strutture_emergenza_2025"),
        ]:
            if cond:
                caps.append(cap)
                cap_src[cap] = why
        scope = next((sc for sc, rx in SCOPE_BY_NAME if re.search(rx, f["name"], re.I)), "general")
        if scope == "pediatric" and "pediatric_emergency_room" not in caps:
            caps.append("pediatric_emergency_room")
            cap_src["pediatric_emergency_room"] = "salutelazio:nome struttura"
        # DM 70/2015 (all. 1, §9.1.1): un PS deve disporre h24 di radiologia (TC ed ecografia) e laboratorio: non è un dato per struttura
        caps.append("imaging_h24_by_regulation")
        cap_src["imaging_h24_by_regulation"] = "DM 70/2015 (requisito normativo, non verificato per struttura)"
        g = f.get("geometry") or {}
        rec = {
            "facility_id": f"ps:{f['emergencyOrganizationId']}", "name": f["name"], "type": "emergency_room", "ps_scope": scope,
            "lat": g.get("latitude"), "lng": g.get("longitude"), "address": f.get("plainAddress"), "phone": f.get("contactPhone"),
            "asl": (dgr[k_dgr]["asl"] if k_dgr else None),
            "ids": {"salutelazio_emergency_id": f["emergencyOrganizationId"], "salutelazio_url": f["url"],
                    "salutelazio_status_facility_id": st.get("facilityId"), "hsp_struttura": s, "hsp_sub": sub or None,
                    "minsal_posti_letto_key": list(k_pl) if k_pl else None, "minsal_emergenza_key": list(k_em) if k_em else None, "dgr869_code": k_dgr},
            "capabilities": sorted(set(caps)), "capability_sources": cap_src, "classification": cls, "beds_by_discipline": beds,
            "live": {"supported": "groups" in st, "endpoint": "salutelazio:emergency-status", "note": None if "groups" in st else "GIPSE 422 al 10/09/2026: nessun dato live"},
            "live_status": None, "opening": {"mode": "h24"},
            "source": {"anagrafica": "salutelazio:list/detail 006", "reparti": "dati.salute.gov.it posti letto 2023" if k_pl else None,
                       "livello_emergenza": "salute.gov.it Strutture_Emergenza_2025.xlsx" if k_em else None,
                       "reti_tempo_dipendenti": "Regione Lazio DGR 869/2023 all. 1 tab. 6.6" if k_dgr else None, "fetched_at": src["fetched_at"]},
            "updated_at": NOW,
        }
        out.append(rec)
        rows.append({"facility_id": rec["facility_id"], "name": f["name"], "scope": scope, "hsp": f"{s}-{sub}" if s else "", "ps_type": cls["ps_type"],
                     "pediatric_ps": int(cls["pediatric_ps"]), "trauma": cls["trauma_level"] or "", "trauma_ped": cls["trauma_ped_level"] or "",
                     "stroke": cls["stroke_unit"] or "", "cardio": cls["cardio_network"] or "", "live": int(rec["live"]["supported"]),
                     **{c: int(c in caps) for c in ["orthopedics_trauma", "pediatrics", "cardiology", "coronary_unit", "neurology", "neurosurgery",
                                                     "obstetrics_gynecology", "ophthalmology", "ent", "general_surgery", "intensive_care", "vascular_surgery"]},
                     "join_reparti": int(bool(k_pl)), "join_emergenza": int(bool(k_em)), "join_dgr": int(bool(k_dgr))})
    return out, rows


def build_cdc():
    cura = json.load(open(RAW / "cdc" / "cdc_curalazio.json"))
    sl = json.load(open(RAW / "cdc" / "cdc_salutelazio.json"))
    by_name = {" ".join(norm(x["nome"])): x for x in sl["items"]}
    out, matched = [], 0
    for i, c in enumerate(cura["items"]):
        key = " ".join(norm(c["nome"]))
        card = by_name.get(key) or next((v for k, v in by_name.items() if k and (k in key or key in k)), None)
        matched += bool(card)
        is_odc = c["tipo"] == "pin-mappa-odc"
        out.append({
            "facility_id": f"cdc:curalazio:{i}", "name": ("Ospedale di Comunità " if is_odc else "Casa della Comunità ") + c["nome"],
            "type": "community_hospital" if is_odc else "community_house", "lat": c["lat"], "lng": c["lng"], "address": c["indirizzo"],
            "phone": card["telefono"] if card else None, "asl": (c["asl"] or "").upper().replace("ASL ", "") or None,
            "ids": {"curalazio_index": i, "salutelazio_card": card["nome"] if card else None},
            "capabilities": ["community_house_dm77"], "capability_sources": {"community_house_dm77": "DM 77/2022: standard nazionale, servizi per singola CdC NON verificati"},
            "classification": {}, "beds_by_discipline": {}, "live": {"supported": False}, "live_status": None,
            "opening": {"mode": "unknown", "weekend_holidays_open": card["aperta_weekend_festivi"] if card else None,
                        "hours": None, "note": "orari non disponibili in formato dati; PDF scheda SaluteLazio è immagine"},
            "source": {"anagrafica": cura["source"], "scheda": sl["source"] if card else None, "fetched_at": cura["fetched_at"]}, "updated_at": NOW,
        })
    return out, matched


def build_pharmacies():
    rows = read_csv(RAW / "minsal" / "farmacie_lazio_attive.csv")
    sl_data = json.load(open(RAW / "salutelazio" / "list_003_farmacie.json"))
    sl = sl_data["items"]
    sl_idx = defaultdict(list)
    for x in sl:
        cap = re.search(r"\b(\d{5})\b", x.get("plainAddress") or "")
        sl_idx[(cap.group(1) if cap else "", address_key(x.get("plainAddress")))].append(x)
    turni = {p.name: read_csv(p) for p in (RAW / "ordine_farmacisti_roma").glob("*.csv")}
    daily_name = max((k for k in turni if re.fullmatch(r"turni_\d{4}-\d{2}-\d{2}\.csv", k)
                      and k[6:16] <= NOW[:10]), default=None)
    daily = turni.get(daily_name, [])
    daily_date = daily_name[6:16] if daily_name else None
    source_meta_path = RAW / "ordine_farmacisti_roma" / "metadata.json"
    opening_meta = json.load(open(source_meta_path)) if source_meta_path.exists() else {}

    def fl(x):
        try:
            return float(x.replace(",", "."))
        except Exception:
            return None

    duty = {address_key(r["indirizzo"].split(" - ")[0]): r for r in daily}
    h24 = {pdf_address(r) for r in turni.get("aperte_h24.csv", [])} - {""}
    h12 = {pdf_address(r) for r in turni.get("aperte_h12_8-20.csv", [])} - {""}
    coordinates_addresses = defaultdict(set)
    for r in rows:
        point = (fl(r["latitudine"]), fl(r["longitudine"]))
        coordinates_addresses[point].add((r["comune"].strip(), address_key(r["indirizzo"])))
    # Il file ministeriale contiene punti generici condivisi da centinaia di sedi diverse.
    suspicious = {point for point, addresses in coordinates_addresses.items() if len(addresses) > 1}
    out, n_coord, n_sl, n_duty, n_rejected = [], 0, 0, 0, 0
    for r in rows:
        lat, lng = fl(r["latitudine"]), fl(r["longitudine"])
        src_coord = "minsal"
        ak = address_key(r["indirizzo"])
        matches = sl_idx.get((r["cap"], ak), []) if ak else []
        sl_match = matches[0] if len(matches) == 1 else None
        coordinate_note = None
        if not valid_lazio_coords(lat, lng) or (lat, lng) in suspicious:
            lat = lng = None
            coordinate_note = "coordinate ministeriali mancanti o non affidabili (punto fuori regione o condiviso da indirizzi diversi)"
            n_rejected += 1
        if sl_match:
            point = sl_match.get("geometry") or {}
            if valid_lazio_coords(point.get("latitude"), point.get("longitude")):
                lat, lng, src_coord = point["latitude"], point["longitude"], "salutelazio"
                coordinate_note = "coordinate SaluteLazio abbinate a CAP, indirizzo e civico univoci"
                n_sl += 1
        n_coord += lat is not None
        is_roma = r["comune"].strip() == "ROMA"
        duty_row = duty.get(ak) if is_roma else None
        on_duty = duty_row is not None
        is_h24, is_h12 = is_roma and ak in h24, is_roma and ak in h12
        n_duty += on_duty
        out.append({
            "facility_id": f"farm:minsal:{r['cod_farmacia']}", "name": r["descrizione_farmacia"].strip().title(), "type": "pharmacy",
            "lat": lat, "lng": lng, "address": f"{r['indirizzo'].strip()}, {r['cap']} {r['comune'].strip().title()} ({r['sigla_provincia']})",
            "phone": (duty_row or {}).get("telefono") or (sl_match or {}).get("contactPhone"), "asl": None,
            "ids": {"minsal_cod_farmacia": r["cod_farmacia"], "p_iva": r["p_iva"], "coords_source": src_coord if lat is not None else None},
            "location_quality": {"status": "source_coordinates" if lat is not None else "unverified", "note": coordinate_note,
                                 "source_url": "https://salutelazio.it" if src_coord == "salutelazio" else "https://www.dati.salute.gov.it/it/dataset/farmacie/"},
            "capabilities": ["pharmacy"] + (["pharmacy_h24"] if is_h24 else []),
            "capability_sources": {"pharmacy": "dati.salute.gov.it farmacie", "pharmacy_h24": "Ordine Farmacisti Roma PDF h24"},
            "classification": {"tipologia": r["descrizione_tipologia"]}, "beds_by_discipline": {}, "live": {"supported": False}, "live_status": None,
            "opening": {"mode": "unknown", "hours": None,
                        "h24_all_year": is_h24,
                        "h12_8_20_all_year": is_h12,
                        "on_duty": {"date": daily_date, "value": on_duty} if is_roma else None,
                        "source_url": ("https://www.ordinefarmacistiroma.it/files/turni/farmacie_aperte_h24.pdf" if is_h24 else
                                       "https://www.ordinefarmacistiroma.it/files/turni/farmacie_aperte_h12.pdf" if is_h12 else
                                       f"https://www.ordinefarmacistiroma.it/cittadino/turni-delle-farmacie.html?d={daily_date}" if is_roma and daily_date else None),
                        "retrieved_at": (opening_meta.get("retrieved_at") or {}).get("aperte_h24.csv" if is_h24 else "aperte_h12_8-20.csv" if is_h12 else "daily"),
                        "note": "orari ordinari non disponibili da fonte ufficiale; turni solo Comune di Roma (Ordine Farmacisti)"},
            "source": {"anagrafica": "https://www.dati.salute.gov.it/it/dataset/farmacie/", "coordinate": "https://salutelazio.it" if src_coord == "salutelazio" else "https://www.dati.salute.gov.it/it/dataset/farmacie/",
                       "turni": "https://www.ordinefarmacistiroma.it/cittadino/turni-delle-farmacie.html" if is_roma else None}, "updated_at": NOW,
        })
    return out, {"totale": len(out), "con_coordinate": n_coord, "coord_da_salutelazio": n_sl, "roma": sum(1 for r in rows if r["comune"].strip() == "ROMA"),
                 "coordinate_minsal_scartate": n_rejected, "di_turno_oggi_abbinate": n_duty, "di_turno_oggi_fonte": len(daily),
                 "turni_data": daily_date, "h24_abbinate": sum(1 for o in out if o["opening"]["h24_all_year"]), "h24_fonte": len(h24)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pl, em, dgr = load_sources()
    ps, rows = build_ps(pl, em, dgr)
    cdc, cdc_matched = build_cdc()
    farm, fstats = build_pharmacies()
    with open(OUT / "ps_capabilities.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    meta = {
        "built_at": NOW, "schema_version": 1,
        "counts": {"emergency_room": len(ps), "community_house": sum(1 for c in cdc if c["type"] == "community_house"),
                   "community_hospital": sum(1 for c in cdc if c["type"] == "community_hospital"), "pharmacy": len(farm)},
        "ps_join": {"reparti": sum(r["join_reparti"] for r in rows), "livello_emergenza": sum(r["join_emergenza"] for r in rows),
                    "dgr869": sum(r["join_dgr"] for r in rows), "live": sum(r["live"] for r in rows), "totale": len(rows)},
        "cdc_join_salutelazio": {"abbinate": cdc_matched, "totale": len(cdc)}, "farmacie": fstats,
    }
    json.dump({"meta": meta, "facilities": ps + cdc + farm}, open(OUT / "facilities.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    print("PS senza join reparti:", [r["name"] for r in rows if not r["join_reparti"]])
    print("PS senza join emergenza 2025:", [r["name"] for r in rows if not r["join_emergenza"]])
    print("PS senza join DGR:", [r["name"] for r in rows if not r["join_dgr"]])
    print("CdC non abbinate a scheda:", [c["name"] for c in cdc if not c["ids"]["salutelazio_card"]][:40])


if __name__ == "__main__":
    main()
