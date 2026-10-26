from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from backend.app.data_sources import pharmacy_regional as P
from backend.app.data_sources.source_utils import fetch

TZ = ZoneInfo('Europe/Rome')


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(P, '_snapshot', {})
    monkeypatch.setattr(P, '_errors', {})
    monkeypatch.setattr(P, '_index', {})
    monkeypatch.setattr(P, '_index_token', None)
    monkeypatch.setattr(P, 'CACHE', tmp_path/'regional.json')


def test_documents_are_official_and_deduplicated():
    text = '''<a href="/turni-2026.pdf">Turni settembre 2026</a>
    <a href="/turni-2026.pdf">Download</a><a href="https://evil.example/turni.pdf">Turni</a>'''
    docs = P.document_links(text, 'VT')
    assert len(docs) == 1 and docs[0]['label'] == 'Turni settembre 2026'
    assert not P.relevant({'url':'https://example.com/2026/Turni-2027.pdf','label':'Turni 2027'}, 'FR', datetime(2026,9,17))
    assert P.relevant({'url':'https://example.com/x.pdf','label':'Turni Luglio - Dicembre 2026'}, 'FR', datetime(2026,9,17))


def test_weekly_on_call_is_not_open_and_end_is_exclusive(monkeypatch):
    page = '''Da Lunedì 14/09/26 Dalle ore 08:00
    A Lunedì 21/09/26 Alle ore 08:00
    REPERIBILITA' A CHIAMATA
    ACQUAPENDENTE          Farm   CATOCCI              Sabato pomeriggio'''
    rows = P.parse_viterbo([page])
    now = datetime(2026,9,17,10,tzinfo=TZ)
    row = {**rows[0], 'source_url':'https://www.ordinefarmacistiviterbo.it/turni.pdf','retrieved_at':now.isoformat()}
    monkeypatch.setattr(P,'_snapshot',{'VT':{'retrieved_at':now.isoformat(),'rows':[row], 'documents':[]}})
    monkeypatch.setattr(P,'indexed',lambda:{'test':[row]})
    result = P.opening({'facility_id':'test','address':'Via Uno 1, 01021 Acquapendente (VT)'},now)
    assert result['on_duty'] and not result['known'] and result['status'] != 'open'
    assert 'chiamata' in result['label']
    assert not P.active(row, datetime(2026,9,21,8,tzinfo=TZ))
    assert P.active(row, datetime(2026,9,21,7,59,tzinfo=TZ))
    assert not P.parse_viterbo([page.replace('21/09/26','28/09/26')])


def test_stale_calendar_does_not_certify_turn(monkeypatch):
    now = datetime(2026,9,17,10,tzinfo=TZ)
    row = {'date':'2026-09-17','retrieved_at':(now-timedelta(days=2)).isoformat()}
    monkeypatch.setattr(P,'_snapshot',{'RI':{'retrieved_at':row['retrieved_at'],'rows':[row], 'documents':[]}})
    monkeypatch.setattr(P,'indexed',lambda:{'test':[row]})
    result = P.opening({'facility_id':'test','address':'Via Uno 1, 02100 Rieti (RI)'},now)
    assert not result['on_duty'] and not result['known']


def test_rieti_continuation_pages_stop_before_provincial_table():
    pages = ["TURNI CITTA' DI RIETI 2° SEMESTRE 2026\ngiovedì 17 settembre 2026 Manca SAS (Piazza Marconi, 24)",
             'venerdì 18 settembre 2026 Carbone SNC (Via Roma,13)',
             'TURNI DOMENICALI E FESTIVI\ndomenica 20 settembre 2026 Altro (Altro comune)']
    rows = P.parse_rieti(pages)
    assert len(rows)==2 and rows[1]['date']=='2026-09-18'
    assert all('starts_at' not in r for r in rows)


def test_monthly_calendar_rejects_partial_and_ignores_support_shifts():
    page = "TURNI FARMACIE CITTA' DI FROSINONE\nSETTEMBRE 2026\n"
    page += '\n'.join(f'{d} GIOVEDI’ FARMACIA TEST – VIA UNO, 1' for d in range(1,31))
    page += '\nAppoggio ALTRA – VIA DUE, 2'
    rows = P.parse_frosinone([page])
    assert len(rows)==30
    assert rows[0]['starts_at'].endswith('08:30:00+02:00')
    assert not P.parse_frosinone([page.replace('30 GIOVEDI’ FARMACIA TEST – VIA UNO, 1','')])


def test_match_requires_municipality_and_unambiguous_name():
    f = {'facility_id':'one','name':'Catocci Sas','address':'Via Uno 1, 01021 Acquapendente (VT)'}
    row = {'municipality':'ACQUAPENDENTE','name':'CATOCCI'}
    assert P.match_row(row,'VT',[f])=='one'
    assert P.match_row(row,'RI',[f]) is None
    assert P.match_row({**row,'municipality':'ALTRO'},'VT',[f]) is None
    assert P.match_row(row,'VT',[f,{**f,'facility_id':'two'}]) is None
    assert P.match_row({**row,'name':'CATOC'},'VT',[f]) is None


@pytest.mark.asyncio
async def test_failed_refresh_preserves_last_success(monkeypatch):
    stamp = '2026-01-01T00:00:00+00:00'
    previous = {'retrieved_at':stamp,'rows':[],'documents':[{'label':'Old','url':'https://www.ordinefarmacistifr.it/old.pdf'}]}
    monkeypatch.setattr(P,'_snapshot',{'FR':previous})
    monkeypatch.setattr(P,'LIVE_DISABLED',False)
    async def broken(*args,**kwargs):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(P,'fetch',broken)
    await P.refresh()
    assert P._snapshot['FR']==previous
    assert P._errors['FR']['error']=='ConnectError'


@pytest.mark.asyncio
async def test_download_rejects_redirect_to_other_host_and_large_body():
    def handler(request):
        if request.url.path=='/redirect':
            return httpx.Response(302,headers={'Location':'http://127.0.0.1/private'})
        return httpx.Response(200,content=b'x'*20)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError,match='host'):
            await fetch(client,'https://source.example/redirect',{'source.example'})
        with pytest.raises(ValueError,match='grande'):
            await fetch(client,'https://source.example/file',{'source.example'},max_bytes=10)


@pytest.mark.asyncio
async def test_failed_document_keeps_its_original_timestamp(monkeypatch):
    now=datetime.now(TZ)
    url='https://www.ordinefarmacistifr.it/turni.pdf'
    stamp=(now-timedelta(hours=7)).isoformat()
    row={'source_url':url,'retrieved_at':stamp,'date':now.date().isoformat(),'name':'Test','municipality':'FROSINONE'}
    monkeypatch.setattr(P,'_snapshot',{'FR':{'retrieved_at':stamp,'rows':[row], 'documents':[{'url':url,'label':'Turni','retrieved_at':stamp,'extraction':'structured'}]}})
    monkeypatch.setattr(P,'LIVE_DISABLED',False)
    async def get(client,target,hosts):
        if target==P.SOURCES['FR']['url']:
            return f'<a href="{url}">Turni</a>'.encode()
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(P,'fetch',get)
    await P.refresh()
    assert P._snapshot['FR']['rows']==[row]
    assert P._snapshot['FR']['documents'][0]['retrieved_at']==stamp
    assert P._snapshot['FR']['documents'][0]['error']=='ConnectError'
