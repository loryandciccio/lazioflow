"""Scarica gli open data del Ministero della Salute utili a LazioFlow e ne salva il sottoinsieme Lazio.

1. Posti letto per stabilimento ospedaliero e disciplina 2023  (chiave: codice struttura HSP 6 cifre + subcodice)
   https://www.dati.salute.gov.it/it/dataset/posti-letto-stabilimento-ospedaliero-e-disciplina-2023/
2. Elenco strutture della rete dell'emergenza ospedaliera 2025 (PS / DEA1 / DEA2 + flag PS pediatrico)
   https://www.salute.gov.it/new/it/banche-dati/elenco-strutture-della-rete-dellemergenza-ospedaliera/
3. Farmacie (anagrafica nazionale con coordinate)  https://www.dati.salute.gov.it/it/dataset/farmacie/
Uso: python3 data/scripts/fetch_minsal.py   (richiede openpyxl per il file 2)
"""
import csv
import io
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "minsal"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) Chrome/120"}
URL_PL = "https://www.dati.salute.gov.it/sites/default/files/2025-07/Posti%20letto%20per%20stabilimento%20ospedaliero%20e%20disciplina_2023_0.csv"
URL_EM = "https://www.salute.gov.it/new/sites/default/files/2026-02/Strutture_Emergenza_2025.xlsx"
URL_FARM_PAGE = "https://www.dati.salute.gov.it/it/dataset/farmacie/"


def fetch(url):
    """urllib fallisce l'handshake TLS con salute.gov.it su alcune build di Python: fallback su curl."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
            return r.read()
    except Exception:
        import subprocess
        return subprocess.run(["curl", "-sL", "-A", UA["User-Agent"], url], capture_output=True, timeout=300, check=True).stdout


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # 1. posti letto
    rows = list(csv.DictReader(io.StringIO(fetch(URL_PL).decode("latin-1")), delimiter=";"))
    laz = [r for r in rows if r["Codice Regione"] == "120"]
    with open(OUT / "posti_letto_2023_lazio.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows({k: v.strip() for k, v in r.items()} for r in laz)
    print(f"posti letto Lazio: {len(laz)} righe, {len({(r['Codice struttura'], r['Subcodice']) for r in laz})} stabilimenti", file=sys.stderr)
    # 2. rete emergenza
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(fetch(URL_EM)), read_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        head = [str(c) for c in next(it)]
        with open(OUT / "strutture_emergenza_2025_lazio.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(head)
            n = 0
            for r in it:
                if str(r[1]) == "120":
                    w.writerow(["" if c is None else str(c).strip() for c in r])
                    n += 1
        print(f"rete emergenza Lazio: {n} strutture", file=sys.stderr)
    except ImportError:
        print("openpyxl mancante: salto Strutture_Emergenza_2025.xlsx", file=sys.stderr)
    # 3. farmacie: il nome file cambia ogni giorno (FRM_FARMA_5_YYYYMMDD.csv): lo ricavo dalla pagina
    page = fetch(URL_FARM_PAGE).decode("utf-8", "ignore")
    m = re.search(r'href="(/sites/default/files/opendata/FRM_FARMA_5_\d+\.csv)"', page)
    if not m:
        sys.exit("link CSV farmacie non trovato")
    rows = list(csv.DictReader(io.StringIO(fetch("https://www.dati.salute.gov.it" + m.group(1)).decode("latin-1")), delimiter=";"))
    laz = [r for r in rows if r["cod_regione"] == "120" and r["data_fine_validita"].strip() in ("", "-")]
    with open(OUT / "farmacie_lazio_attive.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(laz)
    print(f"farmacie Lazio attive: {len(laz)} (file {m.group(1).split('/')[-1]}, {date.today()})", file=sys.stderr)


if __name__ == "__main__":
    main()
