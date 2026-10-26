"""Esporta il DB del poller in CSV dentro data/export/ (da committare per condividerlo col team)."""
import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from backend.app.config import DB_PATH as DB
OUT = ROOT / "data" / "export"

TABLES = ["facilities", "ps_snapshots", "weather", "poll_log"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    for t in TABLES:
        cur = conn.execute(f"SELECT * FROM {t}")
        with open(OUT / f"{t}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([d[0] for d in cur.description])
            n = w.writerows(cur)
        print(f"{t}.csv scritto")
    n = conn.execute("SELECT COUNT(DISTINCT ts) FROM ps_snapshots").fetchone()[0]
    print(f"snapshot distinti: {n}")
    conn.close()


if __name__ == "__main__":
    main()
