"""Test del ranking gerarchico (spec §16.3): compatibilità prima della distanza, stale con avviso, trend, preset."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.app import facilities as F
from backend.app.config import ranking_config
from backend.app.ranking import build_candidate, observed_wait, rank, to_dict
from backend.app.routing import compatibility
from backend.app.trend import trend_from_series

NOW = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)  # giovedì
ROME = (41.9028, 12.4964)
CFG = ranking_config()


def ps(name, lat, lng, caps=("emergency_room", "orthopedics_trauma"), scope="general", eid="PSX"):
    return {"facility_id": f"ps:{eid}", "name": name, "type": "emergency_room", "ps_scope": scope, "lat": lat, "lng": lng,
            "address": "-", "phone": None, "asl": "Roma 1", "ids": {"salutelazio_emergency_id": eid},
            "capabilities": list(caps), "capability_sources": {c: "minsal:posti_letto_2023" for c in caps},
            "classification": {"ps_type": "DEA I"}, "opening": {"mode": "h24"}, "source": {}, "updated_at": "2026-09-10"}


def live(total4, wait4_s, freshness="live", total3=0):
    return {"groups": {"3": {"total": total3, "avg_wait_s": 0, "max_wait_s": 0}, "4": {"total": total4, "avg_wait_s": wait4_s, "max_wait_s": wait4_s},
                       "5": {"total": 0, "avg_wait_s": 0, "max_wait_s": 0}},
            "freshness": freshness, "data_timestamp": NOW.isoformat(), "retrieved_at": NOW.isoformat(), "note": "dato NON aggiornato" if freshness == "stale" else None}


TRAUMA = F.category("TRAUMA_MINORE")


def cand(f, lv=None, tr=None, pref="balanced", age="unknown", cat=TRAUMA):
    return build_candidate(f, *ROME, cat, pref, NOW, lv, tr, age, CFG)


def test_hard_filter_scope_excludes_ophthalmic_ps_for_trauma():
    f = ps("Oftalmico", 41.91, 12.49, scope="ophthalmic", caps=("emergency_room", "ophthalmology", "orthopedics_trauma"))
    assert not compatibility(f, TRAUMA).compatible
    assert cand(f) is None


def test_near_but_unverified_department_ranks_after_verified_far():
    near_no_orto = ps("Vicino senza ortopedia", 41.905, 12.50, caps=("emergency_room",), eid="A")
    far_orto = ps("Lontano con ortopedia", 41.98, 12.60, eid="B")
    ordered = rank([cand(near_no_orto, live(2, 600)), cand(far_orto, live(2, 600))], CFG)
    assert [c.facility["name"] for c in ordered] == ["Lontano con ortopedia", "Vicino senza ortopedia"]
    assert ordered[1].compat.level == 2 and any("non verificato" in w for w in ordered[1].warnings)


def test_balanced_keeps_travel_and_observed_wait_separate():
    a = cand(ps("A vicino ma attesa lunga", 41.91, 12.50, eid="A"), live(5, 90 * 60))   # ~1 km, 90 min
    b = cand(ps("B lontano ma vuoto", 41.95, 12.55, eid="B"), live(0, 0))             # ~7 km, 0 min
    assert a.estimated_min == pytest.approx(a.travel_min)
    assert to_dict(a, 1)["score"]["estimated_minutes"] is None
    assert b.wait_min == 0
    assert [c.facility["name"] for c in rank([a, b], CFG)][0].startswith("A")


def test_preference_nearest_ignores_wait():
    a = cand(ps("A vicino attesa lunga", 41.91, 12.50, eid="A"), live(5, 90 * 60), pref="nearest")
    b = cand(ps("B lontano vuoto", 41.95, 12.55, eid="B"), live(0, 0), pref="nearest")
    assert a.estimated_min == pytest.approx(a.travel_min)
    assert rank([a, b], CFG)[0].facility["name"].startswith("A")


def test_preference_less_crowded_ignores_travel():
    a = cand(ps("A vicino attesa 30", 41.91, 12.50, eid="A"), live(3, 30 * 60), pref="less_crowded")
    b = cand(ps("B lontano attesa 10", 42.10, 12.80, eid="B"), live(1, 10 * 60), pref="less_crowded")
    assert rank([a, b], CFG)[0].facility["name"].startswith("B")


def test_no_live_data_ranks_after_known_and_is_flagged():
    a = cand(ps("A senza dato", 41.905, 12.50, eid="A"), None)
    b = cand(ps("B con dato", 41.95, 12.55, eid="B"), live(4, 20 * 60))
    ordered = rank([a, b], CFG)
    assert ordered[0].facility["name"].startswith("B")
    assert a.estimated_min is None and any("non disponibile" in w for w in a.warnings)
    d = to_dict(a, 2)
    assert d["live"]["freshness"] == "unavailable" and d["score"]["estimated_minutes"] is None


def test_stale_snapshot_is_used_but_warned():
    a = cand(ps("A stale", 41.91, 12.50, eid="A"), live(1, 5 * 60, freshness="stale"))
    assert a.wait_min == 5 and any("NON aggiornato" in w for w in a.warnings)
    assert to_dict(a, 1)["live"]["freshness"] == "stale"


def test_observed_wait_uses_code4_then_code3_then_zero():
    lv = live(0, 0, total3=2)
    lv["groups"]["3"]["max_wait_s"] = 900
    assert observed_wait(lv, CFG) == (15.0, 2, "3")
    assert observed_wait(live(0, 0), CFG) == (0.0, 0, None)
    assert observed_wait(None, CFG) == (None, None, None)


def test_child_requires_pediatrics_and_admits_pediatric_scope():
    adult_only = ps("Adulti", 41.91, 12.50, caps=("emergency_room", "orthopedics_trauma"), eid="A")
    with_ped = ps("Con pediatria", 41.95, 12.55, caps=("emergency_room", "orthopedics_trauma", "pediatrics"), eid="B")
    bambino_gesu = ps("Bambino Gesù", 41.90, 12.46, scope="pediatric", caps=("emergency_room", "orthopedics_trauma", "pediatrics", "pediatric_emergency_room"), eid="C")
    assert compatibility(adult_only, TRAUMA, "child").level == 2
    assert compatibility(with_ped, TRAUMA, "child").level == 1
    assert compatibility(bambino_gesu, TRAUMA, "child").level == 1
    assert not compatibility(bambino_gesu, TRAUMA, "adult").compatible


def test_trend_direction_and_deltas():
    t0 = NOW
    s = [(t0 - timedelta(minutes=m), v) for m, v in [(60, 18), (45, 21), (30, 25), (15, 26), (0, 27)]]
    tr = trend_from_series(s, NOW, CFG["trend"])
    assert (tr["current"], tr["delta_15m"], tr["delta_30m"], tr["delta_60m"]) == (27, 1, 2, 9)
    assert tr["direction"] == "increasing" and tr["samples"] == 5 and "+9" in tr["text"]
    down = [(t0 - timedelta(minutes=m), v) for m, v in [(60, 12), (30, 8), (0, 4)]]
    assert trend_from_series(down, NOW, CFG["trend"])["direction"] == "decreasing"
    small = [(t0 - timedelta(minutes=60), 1), (t0, 3)]   # +2 su 1: sotto la soglia assoluta
    assert trend_from_series(small, NOW, CFG["trend"])["direction"] == "stable"


def test_trend_insufficient_without_hour_old_sample_or_recent_sample():
    only_recent = [(NOW - timedelta(minutes=15), 5), (NOW, 7)]
    assert trend_from_series(only_recent, NOW, CFG["trend"])["direction"] == "insufficient_data"
    old = [(NOW - timedelta(minutes=90), 5), (NOW - timedelta(minutes=30), 7)]
    assert trend_from_series(old, NOW, CFG["trend"])["direction"] == "insufficient_data"
    assert trend_from_series([], NOW, CFG["trend"])["direction"] == "insufficient_data"


def test_far_facility_excluded_by_max_distance():
    assert cand(ps("Lontanissimo", 43.5, 13.0)) is None


def test_trend_is_a_label_not_in_formula():
    a = cand(ps("A", 41.91, 12.50, eid="A"), live(3, 20 * 60), {"direction": "increasing", "delta_60m": 9, "current": 27})
    b = cand(ps("B", 41.91, 12.50, eid="B"), live(3, 20 * 60), {"direction": "decreasing", "delta_60m": -9, "current": 5})
    assert a.estimated_min == b.estimated_min
    assert any("in aumento" in r for r in a.reasons) and any("in diminuzione" in r for r in b.reasons)


def test_pediatric_category_puts_pediatric_ps_first():
    ped_cat = F.category("PEDIATRICO")
    general = ps("Generale con pediatria", 41.905, 12.50, caps=("emergency_room", "pediatrics"), eid="A")
    dedicated = ps("PS pediatrico", 41.95, 12.55, scope="pediatric", caps=("emergency_room", "pediatrics", "pediatric_emergency_room"), eid="B")
    ordered = rank([cand(general, live(0, 0), cat=ped_cat, age="child"), cand(dedicated, live(0, 0), cat=ped_cat, age="child")], CFG)
    assert ordered[0].facility["name"] == "PS pediatrico"


def test_pharmacy_known_open_wins_only_off_hours_and_nearby():
    from backend.app.data_sources.pharmacies import opening_status
    from datetime import datetime as dt
    farm = {"opening": {"h24_all_year": True}}
    day = dt(2026, 9, 10, 11, 0, tzinfo=timezone.utc)      # giovedì mattina
    night = dt(2026, 9, 10, 23, 0, tzinfo=timezone.utc)
    assert opening_status(farm, day)["off_hours"] is False
    assert opening_status(farm, night)["off_hours"] is True
    assert "2026" not in opening_status({"opening": {"on_duty": {"value": True, "date": "2026-09-10"}}}, day)["label"]


@pytest.mark.parametrize("pref", ["balanced", "less_crowded"])
def test_stale_low_wait_cannot_beat_recent_observation(pref):
    old = cand(ps("Old", 41.903, 12.497, eid="old"), live(0, 0, freshness="stale"), pref=pref)
    fresh = cand(ps("Fresh", 41.95, 12.55, eid="fresh"), live(10, 7200), pref=pref)
    assert rank([old, fresh], CFG)[0] is fresh
    assert not to_dict(old, 2)["score"]["wait_used_for_ranking"]
    assert to_dict(old, 2)["live"]["observed_wait_minutes"] == 0
    assert not any("inferiore alle alternative" in reason for reason in old.reasons)


@pytest.mark.parametrize("pref", ["balanced", "less_crowded", "nearest"])
def test_stale_wait_changes_never_change_order(pref):
    near = ps("Near", 41.903, 12.497, eid="near")
    far = ps("Far", 41.95, 12.55, eid="far")
    for small, large in [(0, 7200), (7200, 0)]:
        a = cand(near, live(1, small, freshness="stale"), pref=pref)
        b = cand(far, live(1, large, freshness="stale"), pref=pref)
        assert rank([b, a], CFG)[0] is a
