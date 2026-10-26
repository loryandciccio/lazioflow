"""Bot: logica di decisione pura, formattazione, e flusso handler con Telegram e backend finti."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from bot import format as F
from bot import keyboards as K
from bot.state import category_for_explicit_type, decide, location, set_location, set_request

c = TestClient(app)
CATS = {x["id"]: x for x in c.get("/categories").json()["categories"]}
ROME = (41.9028, 12.4964)


def und(text):
    return c.post("/understand", json={"text": text}).json()


def test_decide_safety_wins():
    d = decide(und("ho una storta e un dolore al petto"), CATS)
    assert d.action == "SHOW_112" and "112" in d.safety_message


def test_decide_uncertain_asks_explicit_choice():
    d = decide(und("sono incinta e ho perdite di sangue"), CATS)
    assert d.action == "SHOW_116117_AND_ASK" and d.category == "GRAVIDANZA"


def test_decide_routes_single_type_and_multi_type(monkeypatch):
    monkeypatch.setenv("LAZIOFLOW_AI", "0")
    d = decide(und("ho preso una storta"), CATS, have_location=False)
    assert d.action == "ASK_LOCATION" and d.category == "TRAUMA_MINORE" and d.facility_type == "emergency_room"
    assert decide(und("ho preso una storta"), CATS, have_location=True).action == "RECOMMEND"
    d = decide(und("ho la febbre"), CATS)
    assert d.action == "ASK_TYPE_FOR_CATEGORY" and set(d.allowed_types) == {"community_house", "emergency_room"}
    d = decide(und("ho la febbre"), CATS, preselected_type="emergency_room")
    assert d.action == "ASK_LOCATION" and d.facility_type == "emergency_room"
    assert decide(und("non so dove andare"), CATS).action == "ASK_SERVICE_TYPE"
    d = decide(und("mio figlio di 6 anni è caduto e gli fa male il polso"), CATS)
    assert d.category == "TRAUMA_MINORE" and d.age_group == "child"


def test_explicit_type_keeps_category_only_if_allowed():
    ud = {}
    set_request(ud, "TRAUMA_MINORE", None)
    assert category_for_explicit_type(ud, "emergency_room", CATS) == "TRAUMA_MINORE"
    assert category_for_explicit_type(ud, "pharmacy", CATS) == "FARMACIA"
    set_request(ud, "UNKNOWN", None)
    assert category_for_explicit_type(ud, "emergency_room", CATS) == "PROBLEMA_GENERICO_NON_URGENTE"


def test_location_ttl(monkeypatch):
    ud = {}
    set_location(ud, *ROME)
    assert location(ud) == ROME
    ud["location"]["ts"] -= 10**6
    assert location(ud) is None


def test_results_message_shows_timestamp_source_and_never_quality():
    res = c.post("/recommend", json={"category": "TRAUMA_MINORE", "location": {"lat": ROME[0], "lng": ROME[1]}}).json()
    recs = res["recommendations"]
    txt = F.results_message(res, recs)
    assert "1. " in txt and ("SaluteLazio" in txt or "non disponibile" in txt)
    assert "112" in txt and "116117" in txt
    assert "qualit" not in txt.lower() and "migliore ospedale" not in txt.lower()
    kb = K.results(recs, "balanced")
    urls = [b.url for row in kb.inline_keyboard for b in row if b.url]
    assert res["synthetic"] is True and urls == []
    assert "strutture fittizie" in txt
    assert F.why_message(res, recs, {"text": "spiegazione", "generator": "rules"})


def test_card_marks_stale_and_unavailable():
    base = {"rank": 1, "name": "PS X", "type": "emergency_room", "distance_km": 2.0, "address": "via", "phone": None,
            "compatibility_confidence": "verified", "compatibility_sources": {"orthopedics_trauma": "minsal"},
            "classification": {}, "score": {"travel_minutes": 5, "estimated_minutes": None, "mode_label": "Equilibrato"},
            "trend": {"direction": "insufficient_data"}, "warnings": [], "reasons": []}
    assert "non disponibile" in F.card({**base, "live": {"available": False, "freshness": "unavailable"}})
    stale = {**base, "live": {"available": True, "freshness": "stale", "total_waiting": 3, "observed_wait_minutes": 10,
                              "observed_wait_code": "4", "data_timestamp": "2026-09-10T08:00:00+00:00"}}
    assert "vecchio" in F.card(stale)


# ---- flusso handler con Telegram finto e backend reale (TestClient)
class FakeApi:
    async def understand(self, text): return und(text)
    async def _get(self, path): return c.get(path).json()
    async def recommend(self, category, lat, lng, preference="balanced", age_group="unknown", facility_type=None, limit=3):
        body = {"category": category, "location": {"lat": lat, "lng": lng}, "preference": preference, "age_group": age_group, "limit": limit}
        if facility_type: body["facility_type"] = facility_type
        return c.post("/recommend", json=body).json()
    async def explain(self, text, recs): return c.post("/explain", json={"text": text, "recommendations": recs}).json()
    async def sources(self): return c.get("/sources").json()
    async def ps_live(self): return c.get("/ps/live").json()


def fake_update(text=None, loc=None, data=None):
    msg = SimpleNamespace(text=text, location=SimpleNamespace(latitude=loc[0], longitude=loc[1]) if loc else None,
                          reply_text=AsyncMock(), reply_contact=AsyncMock(), edit_text=AsyncMock())
    cq = SimpleNamespace(data=data, message=msg, answer=AsyncMock()) if data else None
    return SimpleNamespace(message=msg, callback_query=cq, effective_message=msg)


def ctx(ud=None):
    return SimpleNamespace(user_data=ud if ud is not None else {}, bot_data={"api": FakeApi()})


def texts(u):
    return " ".join(str(call.args[0]) for call in u.message.reply_text.await_args_list)


async def test_flow_text_then_location(monkeypatch):
    monkeypatch.setenv("LAZIOFLOW_AI", "0")
    from bot.handlers.location import on_location
    from bot.handlers.text import on_text
    context = ctx()
    u = fake_update(text="ho preso una storta al piede")
    await on_text(u, context)
    assert "Disturbo" in texts(u) and context.user_data["pending_confirmation"]
    from bot.handlers.callbacks import on_callback
    confirm = fake_update(data="confirmcat")
    confirm.message.message_id = context.user_data["confirmation_message_id"]
    await on_callback(confirm, context)
    assert "posizione" in texts(confirm).lower()
    assert context.user_data["category"] == "TRAUMA_MINORE"
    u2 = fake_update(loc=ROME)
    await on_location(u2, context)
    out = texts(u2)
    assert "1. " in out and "112" in out
    assert context.user_data["last_recs"]


async def test_flow_red_flag_blocks_everything(monkeypatch):
    from bot.handlers.text import on_text
    context = ctx({"category": "FARMACIA", "facility_type": "pharmacy"})
    u = fake_update(text="non riesco a respirare")
    await on_text(u, context)
    assert "112" in texts(u) and "1. " not in texts(u)
    assert "category" not in context.user_data


async def test_flow_buttons_and_callbacks(monkeypatch):
    from bot.handlers.callbacks import on_callback
    from bot.handlers.text import on_text
    context = ctx()
    set_location(context.user_data, *ROME)
    u = fake_update(text=K.BTN_FARMACIA)
    await on_text(u, context)
    assert "1. " in texts(u) and context.user_data["category"] == "FARMACIA"
    u = fake_update(text=K.BTN_EMERGENZA)
    await on_text(u, context)
    assert "112" in texts(u) and "1. " not in texts(u)
    u = fake_update(text=K.BTN_NONSO)
    await on_text(u, context)
    assert "116117" in texts(u)
    cb = fake_update(data="type:emergency_room")
    await on_callback(cb, context)
    assert context.user_data["category"] == "PROBLEMA_GENERICO_NON_URGENTE" and "1. " in texts(cb)
    cb = fake_update(data="pref:nearest")
    await on_callback(cb, context)
    assert context.user_data["preference"] == "nearest"
    cb = fake_update(data="why")
    await on_callback(cb, context)
    assert "Perché questo ordine" in texts(cb)
    cb = fake_update(data="alt")
    await on_callback(cb, context)
    assert "dal 4°" in texts(cb)


async def test_backend_down_is_honest():
    from bot.api_client import Api
    from bot.handlers.text import on_text
    context = SimpleNamespace(user_data={}, bot_data={"api": Api(base_url="http://127.0.0.1:1", timeout=0.5)})
    u = fake_update(text="cerco una farmacia")
    await on_text(u, context)
    assert "non risponde" in texts(u) and "112" in texts(u)


@pytest.mark.parametrize("text", ["non riesco a respirare", "sono incinta e ho perdite di sangue", "non so dove andare"])
async def test_safety_and_clarification_do_not_depend_on_categories(text):
    from bot.handlers.text import on_text
    context = ctx()
    context.bot_data["api"]._get = AsyncMock(side_effect=AssertionError("il catalogo non serve per le uscite di sicurezza"))
    u = fake_update(text=text)
    await on_text(u, context)
    assert "112" in texts(u) or "116117" in texts(u)
    context.bot_data["api"]._get.assert_not_awaited()


@pytest.mark.parametrize("text", ["ho la febbre", "sono incinta e ho perdite di sangue", "non so dove andare"])
async def test_location_never_bypasses_pending_service_choice(text):
    from bot.handlers.location import on_location
    from bot.handlers.text import on_text
    context = ctx()
    context.bot_data["api"].recommend = AsyncMock(side_effect=AssertionError("scelta esplicita ancora mancante"))
    await on_text(fake_update(text=text), context)
    u = fake_update(loc=ROME)
    await on_location(u, context)
    assert "Scegli prima" in texts(u)
    assert location(context.user_data) == ROME
    context.bot_data["api"].recommend.assert_not_awaited()
    markup = u.message.reply_text.await_args.kwargs["reply_markup"]
    types = [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data.startswith("type:")]
    if text == "ho la febbre":
        assert types == ["type:emergency_room", "type:community_house"]


def test_new_request_discards_previous_results_but_keeps_location_and_preference():
    ud = {"last_result": {"category": "FARMACIA"}, "last_recs": [{}], "allowed_types": ["pharmacy"],
          "result_message_id": 42, "offset": 3, "preference": "nearest"}
    set_location(ud, *ROME)
    set_request(ud, "TRAUMA_MINORE", "emergency_room")
    assert not ({"last_result", "last_recs", "allowed_types", "offset", "result_message_id"} & ud.keys())
    assert location(ud) == ROME and ud["preference"] == "nearest"


async def test_failed_new_text_cannot_reuse_previous_request():
    from bot.api_client import BackendError
    from bot.handlers.location import on_location
    from bot.handlers.text import on_text
    context = ctx()
    set_request(context.user_data, "FARMACIA", "pharmacy")
    context.user_data["last_recs"] = [{"name": "vecchio risultato"}]
    context.bot_data["api"].understand = AsyncMock(side_effect=BackendError("offline"))
    context.bot_data["api"].recommend = AsyncMock()
    await on_text(fake_update(text="mi fa male il petto"), context)
    await on_location(fake_update(loc=ROME), context)
    assert "category" not in context.user_data and "last_recs" not in context.user_data
    context.bot_data["api"].recommend.assert_not_awaited()


@pytest.mark.parametrize("data", ["type:invalid", "pref:invalid", "refresh", "why", "alt"])
async def test_invalid_or_expired_callbacks_do_not_call_backend(data):
    from bot.handlers.callbacks import on_callback
    context = ctx()
    context.bot_data["api"]._get = AsyncMock()
    context.bot_data["api"].recommend = AsyncMock()
    context.bot_data["api"].explain = AsyncMock()
    u = fake_update(data=data)
    await on_callback(u, context)
    assert texts(u)
    context.bot_data["api"]._get.assert_not_awaited()
    context.bot_data["api"].recommend.assert_not_awaited()
    context.bot_data["api"].explain.assert_not_awaited()


async def test_old_result_cannot_explain_or_replace_new_result():
    from bot.handlers.callbacks import on_callback
    context = ctx({"category": "FARMACIA", "facility_type": "pharmacy", "last_result": {"category": "FARMACIA"},
                   "last_recs": [{"name": "nuovo risultato"}], "result_message_id": 20})
    context.bot_data["api"].explain = AsyncMock()
    u = fake_update(data="why")
    u.message.message_id = 10
    await on_callback(u, context)
    assert "ultimo risultato" in texts(u)
    context.bot_data["api"].explain.assert_not_awaited()


async def test_identical_refresh_does_not_duplicate_results():
    from telegram.error import BadRequest
    from bot.handlers.location import run_recommend
    context = ctx()
    set_request(context.user_data, "FARMACIA", "pharmacy")
    u = fake_update()
    u.message.edit_text.side_effect = BadRequest("Message is not modified")
    await run_recommend(u.message, context, *ROME, edit=True)
    u.message.reply_text.assert_not_awaited()


@pytest.mark.parametrize("number", ["112", "116117"])
async def test_phone_buttons_show_unmodified_short_number_without_backend(number):
    from bot.handlers.callbacks import on_callback
    context = ctx()
    context.bot_data["api"] = None
    u = fake_update(data=f"call:{number}")
    await on_callback(u, context)
    assert f"<code>{number}</code>" in texts(u)
    assert "non avvia una chiamata" in texts(u)
    u.message.reply_contact.assert_not_awaited()
    u.callback_query.answer.assert_awaited_once()


@pytest.mark.parametrize("text,number", [(K.BTN_EMERGENZA, "112"), (K.BTN_NON_URGENTE, "116117"),
                                        ("non riesco a respirare", "112"), ("sono incinta e ho perdite di sangue", "116117")])
async def test_safety_messages_include_short_number_instructions(text, number):
    from bot.handlers.text import on_text
    u = fake_update(text=text)
    await on_text(u, ctx())
    assert f"<code>{number}</code>" in texts(u)
    u.message.reply_contact.assert_not_awaited()


def test_phone_actions_are_available_on_results_and_service_choice():
    for keyboard in (K.results([], "balanced"), K.service_type(), K.confirm_category()):
        assert all(keyboard.inline_keyboard)
        data = {button.callback_data for row in keyboard.inline_keyboard for button in row}
        assert {"call:112", "call:116117"} <= data
        assert not any((button.url or "").startswith("tel:") for row in keyboard.inline_keyboard for button in row)


def test_no_results_and_missing_waits_are_not_misleading():
    assert "Non ci sono altre" in F.results_message({"facility_type": "pharmacy"}, [], offset=3)
    assert "60 km" not in F.results_message({"facility_type": "pharmacy"}, [])
    empty = F.rete_message({"items": []})
    assert "non disponibili" in empty and "0 in attesa" not in empty
    partial = F.rete_message({"items": [{"name": "PS X", "total_waiting": 4, "observed_wait_minutes": None, "freshness": "stale"}]})
    assert "tempo non disponibile" in partial and "~0 min" not in partial and "dato vecchio" in partial


@pytest.mark.parametrize("status,body", [(200, "<html>not json</html>"), (200, "[]"), (503, "private backend error"), (302, "redirect")])
async def test_api_malformed_or_failed_responses_are_recoverable(monkeypatch, status, body):
    import httpx
    from bot.api_client import Api, BackendError
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text=body))
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(transport=transport, **kwargs))
    api = Api(base_url="https://example.test/")
    for request in (api.health, lambda: api.understand("test")):
        with pytest.raises(BackendError) as error:
            await request()
        assert "private backend error" not in str(error.value)


@pytest.mark.parametrize("have_location", [False, True])
async def test_confirmation_blocks_location_and_old_buttons(have_location):
    from bot.handlers.text import on_text
    from bot.handlers.location import on_location
    from bot.handlers.callbacks import on_callback
    context = ctx()
    if have_location:
        set_location(context.user_data, *ROME)
    context.bot_data["api"].recommend = AsyncMock(wraps=context.bot_data["api"].recommend)
    await on_text(fake_update(text="ho preso una storta"), context)
    context.user_data["confirmation_message_id"] = 123
    await on_location(fake_update(loc=ROME), context)
    await on_callback(fake_update(data="type:pharmacy"), context)
    wrong = fake_update(data="confirmcat")
    wrong.message.message_id = 122
    await on_callback(wrong, context)
    context.bot_data["api"].recommend.assert_not_awaited()
    correct = fake_update(data="confirmcat")
    correct.message.message_id = 123
    await on_callback(correct, context)
    context.bot_data["api"].recommend.assert_awaited_once()
    await on_callback(correct, context)
    context.bot_data["api"].recommend.assert_awaited_once()


def test_session_expiry_erases_sensitive_state_and_text_is_not_retained():
    from bot.state import expire_session
    ud = {}
    set_request(ud, "TRAUMA_MINORE", text="testo personale")
    set_location(ud, *ROME)
    assert "last_text" not in ud
    deadline = ud["session_expires_at"]
    assert not expire_session(ud, deadline - 1)
    assert expire_session(ud, deadline)
    assert ud == {}


async def test_backend_client_sends_configured_key(monkeypatch):
    import httpx
    from bot.api_client import Api
    seen = []
    def reply(request):
        seen.append(request.headers.get("x-api-key"))
        return httpx.Response(200, json={})
    transport = httpx.MockTransport(reply)
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=transport, **kw))
    monkeypatch.setenv("LAZIOFLOW_API_KEY", "test-key")
    api = Api("https://example.test")
    await api.health()
    await api.understand("test")
    assert seen == ["test-key", "test-key"]
