import sqlite3

import pytest

from poller import poller


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(poller.SCHEMA)
    yield conn
    conn.close()


def setup_sources(monkeypatch, payload):
    monkeypatch.setattr(poller, "fetch_facilities", lambda: [{"emergencyOrganizationId": "PSX", "name": "PS Test"}])
    monkeypatch.setattr(poller, "fetch_status", lambda eid: payload)
    monkeypatch.setattr(poller, "fetch_weather", lambda: (20, 21, 50, 0))


def valid_groups():
    return {"groups": [{"group": {"code": code}, "total": 0, "avgWaitSeconds": 0, "maxWaitSeconds": 0}
                       for code in ("3", "4", "5")]}


def test_poller_rejects_partial_snapshot_without_saving_rows(db, monkeypatch):
    payload = valid_groups()
    del payload["groups"][-1]["total"]
    setup_sources(monkeypatch, payload)
    assert poller.poll(db) is False
    assert db.execute("SELECT COUNT(*) FROM ps_snapshots").fetchone()[0] == 0
    assert db.execute("SELECT ps_ok, ps_fail FROM poll_log").fetchone() == (0, 1)


def test_poller_preserves_missing_wait_as_unknown(db, monkeypatch):
    payload = valid_groups()
    payload["groups"][1].update(total=2, maxWaitSeconds=None)
    setup_sources(monkeypatch, payload)
    assert poller.poll(db) is True
    assert db.execute("SELECT total, max_wait_s FROM ps_snapshots WHERE group_code='4'").fetchone() == (2, None)


def test_poller_uses_local_facilities_when_listing_is_down(db, monkeypatch):
    setup_sources(monkeypatch, valid_groups())
    def unavailable():
        raise OSError("offline")
    monkeypatch.setattr(poller, "fetch_facilities", unavailable)
    monkeypatch.setattr("backend.app.facilities.by_type", lambda *types: [
        {"name": "PS locale", "ids": {"salutelazio_emergency_id": "PSY"}, "lat": 41.9, "lng": 12.5}])
    assert poller.poll(db) is True
    assert db.execute("SELECT emergency_id FROM facilities").fetchone() == ("PSY",)


def test_poller_once_returns_error_when_no_data(tmp_path, monkeypatch):
    monkeypatch.setattr(poller, "SYNTHETIC_DATA", False)
    monkeypatch.setattr(poller, "DB_PATH", tmp_path / "poller.db")
    monkeypatch.setattr(poller, "poll", lambda conn: False)
    monkeypatch.setattr("sys.argv", ["poller", "--once"])
    assert poller.main() == 1
