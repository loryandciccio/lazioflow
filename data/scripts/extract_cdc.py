"""Case della Comunità del Lazio da due fonti regionali (nessun open data ufficiale strutturato esiste, verificato 10/09/2026).

1. Mappa Curalazio (comunicazione.regione.lazio.it/curalazio/case-della-comunita): marker embedded nel JS della pagina
   -> nome, ASL, indirizzo, lat/lng, tipo icona (CdC / Ospedale di Comunità).
2. Schede SaluteLazio (salutelazio.it/it/servizi/case-della-comunita): card per CdC con ASL, indirizzo, telefono,
   flag "Aperta sab. dom. festivi", data scheda, link a un PDF (immagine scansionata: NON estraibile senza OCR).
Uso: python3 data/scripts/extract_cdc.py -> data/raw/cdc/cdc_curalazio.json, cdc_salutelazio.json
"""
import html
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "cdc"
UA = {"User-Agent": "Mozilla/5.0"}


def fetch(url):
    """Il sito Curalazio (WordPress dietro WAF) risponde 503 ad alcuni client Python: fallback su curl."""
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "ignore")
    except Exception:
        import subprocess
        return subprocess.run(["curl", "-sL", "-A", "Mozilla/5.0 (Macintosh) Chrome/120", url], capture_output=True, timeout=120, check=True).stdout.decode("utf-8", "ignore")


def curalazio():
    page = fetch("https://comunicazione.regione.lazio.it/curalazio/case-della-comunita")
    i = page.find('"markers":[')
    if i < 0:  # il sito va spesso in 503: uso l'ultima copia salvata della pagina
        cache = sorted(OUT.glob("curalazio_page_cache_*.html"))
        if not cache:
            raise SystemExit("Curalazio non raggiungibile e nessuna cache in data/raw/cdc/")
        print(f"[warn] Curalazio non disponibile, uso {cache[-1].name}")
        page = cache[-1].read_text(encoding="utf-8", errors="ignore")
        i = page.find('"markers":[')
    markers, _ = json.JSONDecoder().raw_decode(page, i + len('"markers":'))
    out = []
    for mk in markers:
        desc = html.unescape(re.sub(r"<[^>]+>", " ", mk.get("description") or ""))
        asl = re.search(r"(ASL[^\n]*?)\s{2,}", desc + "  ")
        title = re.sub(r"^\s*CASA (DELLA|DI) COMUNIT[AÀ]'?\s*", "", mk["title"].replace("\\'", "'"), flags=re.I).strip()
        title = re.sub(r"^\s*OSPEDALE DI COMUNIT[AÀ]'?\s*", "", title, flags=re.I).strip() or mk["title"]
        out.append({
            "nome": title if title.isupper() is False else title.title(), "asl": (asl.group(1).strip() if asl else None), "indirizzo": mk.get("address"),
            "lat": float(mk["coord_x"]), "lng": float(mk["coord_y"]),
            "tipo": (mk.get("icon_data") or {}).get("title"), "descrizione": desc.strip(),
        })
    return out


def salutelazio():
    page = fetch("https://salutelazio.it/it/servizi/case-della-comunita")
    out = []
    for card in re.findall(r'<div class="card-file shadow.*?</button>\s*</div>\s*</div>', page, re.S):
        title = re.search(r'<h3 class="card-file-title[^>]*>(.*?)</h3>', card)
        desc = re.search(r'<div>(.*?)</div>\s*</div>\s*</div>\s*</section>', card, re.S)
        dt = re.search(r'<p class="description text-slate-28">(\d{2}/\d{2}/\d{4})</p>', card)
        raw = html.unescape(re.sub(r"<[^>]+>", "", desc.group(1))).strip() if desc else ""
        raw = raw[raw.find("ASL"):] if "ASL" in raw else raw  # la card ripete titolo e "pdf | 629KB" prima dell'ASL
        parts = [p.strip() for p in raw.split(" - ")]
        wk = re.search(r"festivi:\s*(SI|NO)", raw, re.I)
        tel = re.search(r"Tel:\s*([\d ]+)", raw)
        out.append({
            "nome": html.unescape(title.group(1)).strip() if title else None,
            "asl": parts[0] if parts else None,
            "indirizzo": " - ".join(p for p in parts[1:] if not p.lower().startswith(("tel", "aperta"))),
            "telefono": tel.group(1).strip() if tel else None,
            "aperta_weekend_festivi": (wk.group(1).upper() == "SI") if wk else None,
            "data_scheda": dt.group(1) if dt else None, "raw": raw,
        })
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    c = curalazio()
    s = salutelazio()
    json.dump({"fetched_at": ts, "source": "https://comunicazione.regione.lazio.it/curalazio/case-della-comunita", "items": c}, open(OUT / "cdc_curalazio.json", "w"), ensure_ascii=False, indent=1)
    json.dump({"fetched_at": ts, "source": "https://salutelazio.it/it/servizi/case-della-comunita", "items": s}, open(OUT / "cdc_salutelazio.json", "w"), ensure_ascii=False, indent=1)
    print(f"curalazio: {len(c)} marker ({sum(1 for x in c if x['tipo']=='pin-mappa-cdc')} CdC); salutelazio: {len(s)} schede, weekend SI={sum(1 for x in s if x['aperta_weekend_festivi'])}")


if __name__ == "__main__":
    main()
