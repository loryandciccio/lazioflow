"""Farmacie di turno / aperte a Roma (solo Comune di Roma) dall'Ordine dei Farmacisti di Roma.

- pagina giornaliera https://www.ordinefarmacistiroma.it/cittadino/turni-delle-farmacie.html?d=YYYY-MM-DD
  (tabella: denominazione, indirizzo, telefono; nessuna coordinata, nessun orario esplicito)
- PDF farmacie aperte H24 tutto l'anno e H12 (8-20) tutto l'anno: /files/turni/farmacie_aperte_h24.pdf, _h12.pdf
Uso: python3 data/scripts/fetch_turni_farmacie_roma.py [YYYY-MM-DD]  -> data/raw/ordine_farmacisti_roma/
"""
import csv
import html
import io
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "ordine_farmacisti_roma"
SITE = "https://www.ordinefarmacistiroma.it"
UA = {"User-Agent": "Mozilla/5.0"}


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()


def parse_daily(day):
    page = fetch(f"{SITE}/cittadino/turni-delle-farmacie.html?d={day}").decode("utf-8", "ignore")
    out = []
    for row in re.findall(r"<tr class=\" row\d\">(.*?)</tr>", page, re.S):
        cells = re.findall(r'<td class="shift_(\w+)"[^>]*>(.*?)</td>', row, re.S)
        d = {k: html.unescape(re.sub(r"<[^>]+>", "", v)).strip() for k, v in cells}
        if d.get("name"):
            out.append({"nome": d["name"], "indirizzo": d.get("address", ""), "telefono": d.get("phone", "")})
    return out


def parse_pdf(name):
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(fetch(f"{SITE}/files/turni/{name}")))
    out = []
    for line in "\n".join(p.extract_text() or "" for p in r.pages).splitlines():
        m = re.match(r"^(.*?)\s+(\d{5})\s+(RM/\d.*?)\s+MUNICIPIO:\s*(\d+)", line.strip())
        if m:
            out.append({"ragione_sociale_e_indirizzo": m.group(1).strip(), "cap": m.group(2), "asl": m.group(3).strip(), "municipio": m.group(4)})
    return out


def write(path, rows):
    if not rows:
        raise ValueError(f"nessun dato valido per {path.name}: mantengo il file precedente")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    daily = parse_daily(day)
    write(OUT / f"turni_{day}.csv", daily)
    print(f"{day}: {len(daily)} farmacie di turno")
    source_dates = {"daily": datetime.now(timezone.utc).isoformat()}
    for pdf, out in (("farmacie_aperte_h24.pdf", "aperte_h24.csv"), ("farmacie_aperte_h12.pdf", "aperte_h12_8-20.csv")):
        try:
            rows = parse_pdf(pdf)
            write(OUT / out, rows)
            source_dates[out] = datetime.now(timezone.utc).isoformat()
            print(f"{pdf}: {len(rows)} farmacie")
        except ImportError:
            print("pypdf mancante: salto i PDF")
    (OUT / "metadata.json").write_text(json.dumps({"retrieved_at": source_dates,
        "daily_date": day, "source_url": f"{SITE}/cittadino/turni-delle-farmacie.html"}, indent=2))


if __name__ == "__main__":
    main()
