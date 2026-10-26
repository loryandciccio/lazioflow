from datetime import datetime, timezone, timedelta

import httpx
import pytest

from backend.app.data_sources import pharmacy_live as L


def page(day='17/09/2026'):
    return f'''<h1>Farmacie di turno a Roma il {day}</h1><table><tr class="row0">
    <td class="shift_name">Farmacia A</td><td class="shift_address">VIA ROMA 8 - 00100 ROMA (RM)</td>
    <td class="shift_phone">06123</td></tr></table>'''


def test_parser_rejects_wrong_day_and_empty_page():
    assert L.parse_daily(page(), '2026-09-17')[0]['address'] == 'ROMA 8'
    with pytest.raises(ValueError):
        L.parse_daily(page('16/09/2026'), '2026-09-17')
    with pytest.raises(ValueError):
        L.parse_daily('<h1>Farmacie di turno a Roma il 17/09/2026</h1>', '2026-09-17')


def test_overlay_exact_address_no_other_city_no_ambiguous_match(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    source = {'daily': {'date':'2026-09-17', 'retrieved_at':now, 'source_url':'https://example.test',
                        'rows':[{'address':'ROMA 8','phone':'06123'}]}}
    monkeypatch.setattr(L, '_snapshot', source)
    f = {'type':'pharmacy','address':'Via Roma 8, 00100 Roma (RM)','opening':{}}
    assert L.overlay(f)['opening']['on_duty']['value']
    assert L.overlay(f)['phone'] == '06123'
    assert not L.overlay({**f,'address':'Via Roma 842, 00100 Roma (RM)'})['opening']['on_duty']['value']
    elsewhere = {**f,'address':'Via Roma 8, 00054 Fiumicino (RM)'}
    assert L.overlay(elsewhere) == elsewhere
    source['daily']['rows'] *= 2
    assert not L.overlay(f)['opening']['on_duty']['value']


def test_old_pdf_no_longer_certifies_open(monkeypatch):
    old = (datetime.now(timezone.utc)-timedelta(days=3)).isoformat()
    monkeypatch.setattr(L, '_snapshot', {'h24': {'date':'2026-09-10','retrieved_at':old,'source_url':'url', 'rows':[{'address':'ROMA 8'}]}})
    f = {'type':'pharmacy','address':'Via Roma 8, 00100 Roma (RM)','opening':{'h24_all_year':True}}
    assert L.overlay(f)['opening']['h24_all_year'] is False


async def test_failed_refresh_keeps_last_good_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(L, 'LIVE_DISABLED', False)
    monkeypatch.setattr(L, 'CACHE', tmp_path/'cache.json')
    old = {'daily': {'date':'2020-01-01','retrieved_at':'2020-01-01T00:00:00+00:00','rows':[], 'source_url':'url'}}
    monkeypatch.setattr(L, '_snapshot', old)
    monkeypatch.setattr(L, '_errors', {})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw: client(transport=httpx.MockTransport(lambda req:httpx.Response(503)), **kw))
    await L.refresh()
    assert L._snapshot == old and not L.CACHE.exists()
    assert set(L._errors) == {'daily','h24','h12'}


async def test_success_is_persisted_and_not_downloaded_again_within_ttl(monkeypatch, tmp_path):
    from zoneinfo import ZoneInfo
    day = datetime.now(ZoneInfo('Europe/Rome')).strftime('%d/%m/%Y')
    calls = []
    def reply(request):
        calls.append(str(request.url))
        return httpx.Response(200, text=page(day))
    client = httpx.AsyncClient
    monkeypatch.setattr(L, 'LIVE_DISABLED', False)
    monkeypatch.setattr(L, 'CACHE', tmp_path/'cache.json')
    monkeypatch.setattr(L, '_snapshot', {})
    monkeypatch.setattr(L, '_errors', {})
    monkeypatch.setattr(L, 'parse_pdf', lambda content:[{'address':'ROMA 8'}])
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw:client(transport=httpx.MockTransport(reply), **kw))
    await L.refresh()
    assert len(calls) == 3 and L.CACHE.exists()
    await L.refresh()
    assert len(calls) == 3
    monkeypatch.setattr(L, '_snapshot', {})
    L.load_cache()
    assert set(L._snapshot) == {'daily','h24','h12'}


def test_daily_refresh_does_not_rejuvenate_expired_h24(monkeypatch):
    from backend.app.data_sources.pharmacies import opening_status
    now = datetime.now(timezone.utc)
    old = (now-timedelta(days=10)).isoformat()
    monkeypatch.setattr(L, '_snapshot', {'daily': {'date':now.date().isoformat(), 'retrieved_at':now.isoformat(),
                                                'source_url':'daily', 'rows':[{'address':'ROMA 8'}]}})
    f = {'type':'pharmacy','address':'Via Roma 8, 00100 Roma (RM)',
         'opening':{'h24_all_year':True,'retrieved_at':old}}
    result = opening_status(L.overlay(f), now)
    assert result['status'] != 'open'


def test_missing_timestamp_cannot_certify_h24_or_duty():
    from datetime import datetime, timezone
    from backend.app.data_sources.pharmacies import opening_status
    now=datetime.now(timezone.utc)
    result=opening_status({'opening':{'h24_all_year':True}},now)
    assert not result['known'] and result['status']!='open'
    result=opening_status({'opening':{'on_duty':{'value':True,'date':now.date().isoformat()}}},now)
    assert not result.get('on_duty')
