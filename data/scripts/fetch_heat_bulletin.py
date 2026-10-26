"""Bollettino ondate di calore del Ministero della Salute (Roma), via il CSV mantenuto da onData
(https://github.com/ondata/ondate-calore, aggiornato ogni giorno dal portale ministeriale; stagione 25/05-20/09).
Livelli: 0 nessun rischio, 1 pre-allerta, 2 rischio elevato, 3 ondata di calore (>=3 giorni).
Uso: python3 data/scripts/fetch_heat_bulletin.py  -> data/raw/ondata/ondate_calore_roma.json
"""
import csv
import io
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "ondata"
URL = "https://raw.githubusercontent.com/ondata/ondate-calore/main/data/ondate-calore_latest.csv"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    raw = urllib.request.urlopen(URL, timeout=30).read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(raw)))
    roma = [r for r in rows if r["citta"].upper() == "ROMA"]
    json.dump(roma, open(OUT / "ondate_calore_roma.json", "w"), ensure_ascii=False, indent=1)
    (OUT / "ondate-calore_latest.csv").write_text(raw)
    for r in roma:
        print(r["data"], r["livello"], "(bollettino del", r["data_estrazione"] + ")")


if __name__ == "__main__":
    main()
