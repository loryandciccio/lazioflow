"""LazioFlow poller: salva ogni N minuti lo stato live dei Pronto Soccorso del Lazio + meteo Roma.

Uso:  python3 poller/poller.py            (loop infinito, default ogni 5 min)
      python3 poller/poller.py --once     (un solo giro, utile per test)
"""
import argparse
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from backend.app.config import DB_PATH, LIVE_CONCURRENCY, LIVE_TIMEOUT_S, SYNTHETIC_DATA
from backend.app.data_sources.salutelazio import _groups_from_api

API = "https://server.salutelazio.it/server/external-services/facilities/structures"
HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://salutelazio.it", "Accept": "application/json"}
LAZIO_BBOX = "westLng=11.4&southLat=40.7&eastLng=14.1&northLat=42.9&zoom=8&lang=it"
ROME = (41.9028, 12.4964)

SCHEMA = """
CREATE TABLE IF NOT EXISTS facilities (
  emergency_id TEXT PRIMARY KEY, name TEXT, address TEXT, phone TEXT, lat REAL, lng REAL, url TEXT, first_seen TEXT
);
CREATE TABLE IF NOT EXISTS ps_snapshots (
  ts TEXT, emergency_id TEXT, group_code TEXT, total INTEGER, avg_wait_s INTEGER, max_wait_s INTEGER,
  PRIMARY KEY (ts, emergency_id, group_code)
);
CREATE TABLE IF NOT EXISTS weather (
  ts TEXT PRIMARY KEY, temp_c REAL, apparent_c REAL, humidity REAL, weather_code INTEGER
);
CREATE TABLE IF NOT EXISTS poll_log (ts TEXT PRIMARY KEY, ps_ok INTEGER, ps_fail INTEGER, weather_ok INTEGER, seconds REAL);
CREATE INDEX IF NOT EXISTS idx_snapshots_facility_ts ON ps_snapshots (emergency_id, ts);
"""


def get_json(url, timeout=LIVE_TIMEOUT_S):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_facilities():
    data = get_json(f"{API}/list?{LAZIO_BBOX}&page=1&limit=200&facilityTypeIds=006")
    items = [f for f in data["items"] if f.get("emergencyOrganizationId")]
    if not items:
        raise ValueError("anagrafica PS vuota")
    return items


def fetch_status(emergency_id):
    q = urllib.parse.urlencode({"facilityId": emergency_id})
    return get_json(f"{API}/emergency-status?{q}")


def fetch_weather():
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={ROME[0]}&longitude={ROME[1]}"
        "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code&timezone=Europe%2FRome"
    )
    c = get_json(url)["current"]
    return c["temperature_2m"], c["apparent_temperature"], c["relative_humidity_2m"], c["weather_code"]


def poll(conn):
    t0 = time.time()
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        facilities = fetch_facilities()
    except Exception as exc:
        # La fonte dell'anagrafica può fallire mentre emergency-status funziona.
        from backend.app.facilities import by_type, emergency_id
        facilities = [{"emergencyOrganizationId": emergency_id(f), "name": f["name"],
                       "plainAddress": f.get("address"), "contactPhone": f.get("phone"),
                       "geometry": {"latitude": f.get("lat"), "longitude": f.get("lng")}}
                      for f in by_type("emergency_room") if emergency_id(f)]
        if not facilities:
            raise
        print(f"  [warn] anagrafica live non disponibile ({type(exc).__name__}): uso dataset locale", file=sys.stderr)
    for f in facilities:
        g = f.get("geometry") or {}
        conn.execute(
            "INSERT INTO facilities VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(emergency_id) DO UPDATE SET "
            "name=excluded.name, address=excluded.address, phone=excluded.phone, "
            "lat=excluded.lat, lng=excluded.lng, url=COALESCE(excluded.url, facilities.url)",
            (f["emergencyOrganizationId"], f["name"], f.get("plainAddress"), f.get("contactPhone"),
             g.get("latitude"), g.get("longitude"), f.get("url"), ts),
        )
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=max(1, LIVE_CONCURRENCY)) as executor:
        requests = {executor.submit(fetch_status, f["emergencyOrganizationId"]): f for f in facilities}
        for future in as_completed(requests):
            f = requests[future]
            eid = f["emergencyOrganizationId"]
            try:
                groups = _groups_from_api(future.result())
                rows = [(ts, eid, code, grp["total"], grp["avg_wait_s"], grp["max_wait_s"])
                        for code, grp in groups.items()]
                conn.executemany("INSERT OR REPLACE INTO ps_snapshots VALUES (?,?,?,?,?,?)", rows)
                ok += 1
            except Exception as exc:
                fail += 1
                print(f"  [warn] {f['name']}: {type(exc).__name__}", file=sys.stderr)
    weather_ok = 0
    try:
        conn.execute("INSERT OR REPLACE INTO weather VALUES (?,?,?,?,?)", (ts, *fetch_weather()))
        weather_ok = 1
    except Exception as e:
        print(f"  [warn] meteo: {e}", file=sys.stderr)
    secs = round(time.time() - t0, 1)
    conn.execute("INSERT OR REPLACE INTO poll_log VALUES (?,?,?,?,?)", (ts, ok, fail, weather_ok, secs))
    conn.commit()
    waiting = conn.execute("SELECT SUM(total) FROM ps_snapshots WHERE ts=?", (ts,)).fetchone()[0]
    print(f"{ts}  PS ok={ok} fail={fail}  meteo={'ok' if weather_ok else 'KO'}  in attesa Lazio={waiting}  ({secs}s)", flush=True)
    return ok > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=300, help="secondi tra un giro e l'altro")
    args = ap.parse_args()
    if SYNTHETIC_DATA:
        ap.error("Synthetic demo catalogue: real-source polling is disabled. Configure an authorized real dataset first.")
    if args.interval <= 0:
        ap.error("--interval deve essere maggiore di zero")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        while True:
            success = False
            try:
                success = poll(conn)
            except Exception as e:
                conn.rollback()
                print(f"[error] giro fallito: {e}", file=sys.stderr, flush=True)
            if args.once:
                return 0 if success else 1
            time.sleep(args.interval)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
