import pytest
"""Endpoint tests against the synthetic public demo catalogue, without network calls."""
from fastapi.testclient import TestClient

from backend.app.main import app

c = TestClient(app)
ROME = {"lat": 41.9028, "lng": 12.4964}


def test_health_and_categories():
    h = c.get("/health").json()
    assert h["status"] == "degraded" and h["dataset"]["emergency_room"] == 6
    assert h["synthetic"] is True
    ids = {x["id"] for x in c.get("/categories").json()["categories"]}
    assert {"EMERGENZA", "TRAUMA_MINORE", "FARMACIA", "ASSISTENZA_TERRITORIALE"} <= ids


def test_emergency_category_returns_escalation_not_facilities():
    r = c.post("/recommend", json={"category": "EMERGENZA", "location": ROME}).json()
    assert r["escalation"] == "112" and r["recommendations"] == []


def test_trauma_top3_are_compatible_ps_with_sources_and_timestamps():
    r = c.post("/recommend", json={"category": "TRAUMA_MINORE", "location": ROME})
    assert r.status_code == 200, r.text
    d = r.json()
    assert 1 <= len(d["recommendations"]) <= 3 and d["candidates_considered"] > 3
    for x in d["recommendations"]:
        assert x["type"] == "emergency_room" and x["ps_scope"] in ("general", "orthopedic")
        assert x["compatible"] and x["maps_url"] == ""
        assert x["distance_km"] >= 0 and x["score"]["formula"]
        assert x["live"]["freshness"] in ("live", "recent", "stale", "unavailable")
        if x["live"]["freshness"] != "unavailable":
            assert x["live"]["data_timestamp"]
        assert x["sources"] and all(s["freshness"] for s in x["sources"])
        assert x["trend"]["direction"] in ("increasing", "stable", "decreasing", "insufficient_data")


def test_unknown_category_and_wrong_type_are_400():
    assert c.post("/recommend", json={"category": "DIAGNOSI", "location": ROME}).status_code == 400
    assert c.post("/recommend", json={"category": "FARMACIA", "location": ROME, "facility_type": "emergency_room"}).status_code == 400


def test_extra_fields_rejected():
    assert c.post("/recommend", json={"category": "FARMACIA", "location": ROME, "severity": "mild"}).status_code == 422


def test_pharmacies_distinguish_open_from_near():
    d = c.post("/recommend", json={"category": "FARMACIA", "location": ROME}).json()
    for x in d["recommendations"]:
        assert x["type"] == "pharmacy" and x["opening"]["status"] in ("unknown", "unknown_hours")
        assert x["opening"]["known"] is False
        assert x["live"] is None and x["score"]["wait_minutes"] is None


def test_cdc_always_says_call_first():
    d = c.post("/recommend", json={"category": "ASSISTENZA_TERRITORIALE", "location": ROME}).json()
    assert d["recommendations"]
    for x in d["recommendations"]:
        assert x["type"] in ("community_house", "community_hospital")
        assert "chiama prima" in " ".join(x["reasons"] + x["warnings"]).lower() or x["opening"]["status"] == "closed"


def test_generic_category_can_pick_ps_explicitly():
    d = c.post("/recommend", json={"category": "PROBLEMA_GENERICO_NON_URGENTE", "location": ROME, "facility_type": "emergency_room"}).json()
    assert d["facility_type"] == "emergency_room" and all(x["type"] == "emergency_room" for x in d["recommendations"])


def test_facility_detail_and_sources():
    fid = c.post("/recommend", json={"category": "TRAUMA_MINORE", "location": ROME}).json()["recommendations"][0]["facility_id"]
    f = c.get(f"/facilities/{fid}").json()
    assert f["capability_sources"] and "orthopedics_trauma" in f["capabilities"]
    assert c.get("/facilities/nope").status_code == 404
    assert c.get("/sources").json()["ranking_parameters"]["presets"]["balanced"]["wait"] is True


def test_health_survives_uninitialized_or_invalid_database(tmp_path, monkeypatch):
    db = tmp_path / "poller.db"
    monkeypatch.setattr("backend.app.main.DB_PATH", db)
    for content in (b"", b"not a SQLite database"):
        db.write_bytes(content)
        response = c.get("/health")
        assert response.status_code == 200
        assert response.json()["poller"]["status"] == "unavailable"


def test_relative_database_path_uses_project_root(monkeypatch, tmp_path):
    from backend.app.config import ROOT, database_path
    monkeypatch.chdir(tmp_path)
    assert database_path("data/lazioflow.db") == ROOT / "data/lazioflow.db"
    assert database_path(str(tmp_path / "custom.db")) == tmp_path / "custom.db"


@pytest.mark.parametrize('age_seconds,failed,expected', [(60, 0, 'ok'), (3600, 0, 'degraded'), (60, 1, 'degraded'), (-60, 0, 'degraded')])
def test_health_reflects_poller_freshness_and_failures(tmp_path, monkeypatch, age_seconds, failed, expected):
    import sqlite3
    from datetime import datetime, timedelta, timezone
    from backend.app import main
    path = tmp_path / 'health.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE poll_log (ts TEXT, ps_ok INTEGER, ps_fail INTEGER)')
        db.execute('CREATE TABLE ps_snapshots (ts TEXT)')
        ts = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
        db.execute('INSERT INTO poll_log VALUES (?, 54, ?)', (ts, failed))
        db.execute('INSERT INTO ps_snapshots VALUES (?)', (ts,))
    monkeypatch.setattr(main, 'DB_PATH', path)
    result = c.get('/health').json()
    assert result['status'] == expected
    assert result['poller_age_seconds'] == pytest.approx(age_seconds, abs=2)
