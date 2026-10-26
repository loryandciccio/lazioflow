from fastapi.testclient import TestClient

from backend.app.main import app

c = TestClient(app)


def test_parse_endpoint_offline(monkeypatch):
    monkeypatch.setenv("LAZIOFLOW_AI", "0")
    r = c.post("/parse", json={"text": "Sono caduto e mi fa molto male il piede"}).json()
    assert r["parsed"]["category"] == "TRAUMA_MINORE" and r["parsed"]["needs_location"] and r["parser"] == "rules"
    assert set(r["parsed"]) == {"intent", "category", "problem_domain", "body_area", "requested_service", "age_group",
                                "needs_location", "emergency_detected_by_llm", "confidence"}


def test_safety_endpoint_contract():
    r = c.post("/safety/check", json={"text": "ho un dolore al petto"}).json()
    assert r["status"] == "HARD_RED_FLAG" and r["allowed_actions"] == ["SHOW_112"] and r["matched_rules"][0]["source"]["url"]
    r = c.post("/safety/check", json={"text": "cerco una farmacia"}).json()
    assert r["status"] == "NO_FLAG_DETECTED" and r["matched_rules"] == []


def test_understand_safety_wins_over_parser(monkeypatch):
    monkeypatch.setenv("LAZIOFLOW_AI", "0")
    r = c.post("/understand", json={"text": "ho una storta ma anche un dolore al petto"}).json()
    assert r["safety"]["status"] == "HARD_RED_FLAG" and r["next_step"] == "SHOW_112"
    r = c.post("/understand", json={"text": "mia nonna è caduta ed è confusa"}).json()
    assert r["next_step"] == "SHOW_116117_AND_ASK"
    r = c.post("/understand", json={"text": "non so dove andare"}).json()
    assert r["next_step"] == "ASK_SERVICE_TYPE"
    r = c.post("/understand", json={"text": "ho preso una storta"}).json()
    assert r["next_step"] == "ROUTE" and r["parse"]["parsed"]["category"] == "TRAUMA_MINORE"


def test_explain_offline_uses_only_given_data(monkeypatch):
    monkeypatch.setenv("LAZIOFLOW_AI", "0")
    recs = [{"rank": 1, "name": "PS X", "type": "emergency_room", "distance_km": 2.1, "reasons": ["distanza 2,1 km", "0 persone in attesa"], "warnings": []}]
    r = c.post("/explain", json={"text": "storta", "recommendations": recs}).json()
    assert r["generator"] == "rules" and "PS X" in r["text"] and "distanza 2,1 km" in r["text"]


def test_text_too_long_rejected():
    assert c.post("/parse", json={"text": "a" * 4097}).status_code == 422


def test_telegram_message_length_accepted(monkeypatch):
    monkeypatch.setenv("LAZIOFLOW_AI", "0")
    assert c.post("/understand", json={"text": "a" * 4096}).status_code == 200


def test_emergency_does_not_wait_for_model(monkeypatch):
    async def broken_model(text):
        raise AssertionError("Un hard red flag non deve chiamare l'LLM")

    monkeypatch.setattr("backend.app.ai_routes.parse", broken_model)
    result = c.post("/understand", json={"text": "ho dolore al petto"})
    assert result.status_code == 200
    assert result.json()["next_step"] == "SHOW_112"
    assert result.json()["parse"]["parser"] == "rules"


def test_understand_does_not_log_health_text(monkeypatch, caplog):
    monkeypatch.setenv("LAZIOFLOW_AI", "0")
    with caplog.at_level("INFO", logger="lazioflow.ai"):
        c.post("/understand", json={"text": "ho preso una storta"})
    assert "ho preso una storta" not in caplog.text
    assert "understand safety=" in caplog.text


def test_invalid_explanation_returns_validation_error():
    for rec in ({}, {"rank": 1, "name": "PS", "type": "emergency_room", "distance_km": 1, "score": []}):
        assert c.post("/explain", json={"recommendations": [rec]}).status_code == 422


def test_explanation_accepts_recommendation_response(monkeypatch):
    monkeypatch.setenv("LAZIOFLOW_AI", "0")
    ranking = c.post("/recommend", json={"category": "FARMACIA", "location": {"lat": 41.9028, "lng": 12.4964}}).json()
    response = c.post("/explain", json={"recommendations": ranking["recommendations"]})
    assert response.status_code == 200
    assert ranking["recommendations"][0]["name"] in response.json()["text"]
