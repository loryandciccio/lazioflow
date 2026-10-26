from datetime import datetime, timedelta, timezone
import pytest
from backend.app.data_sources import cdc_regional as C


def test_regional_cards_preserve_unknown_hours_and_expire(monkeypatch):
    monkeypatch.setattr(C, '_snapshot', {'retrieved_at': datetime.now(timezone.utc).isoformat(),
        'records': {'Rieti': {'phone':'0746 123','weekend':True,'published_date':'16/09/2026','asl':'Rieti'}}})
    facility = {'ids':{'salutelazio_card':'Rieti'},'phone':None}
    assert C.overlay(facility)['phone'] == '0746 123'
    assert C.details(facility)['known'] is False
    assert C.details({'ids':{'salutelazio_card':'Rieti altro'}}) is None
    C._snapshot['retrieved_at'] = (datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    assert C.details(facility) is None
    assert C.overlay(facility) == facility


def test_broken_source_is_rejected():
    with pytest.raises(ValueError):
        C.parse('<html>Servizio non disponibile</html>')


def test_multiple_asls_are_parsed():
    def card(name, asl, weekend):
        return f'<div class="card-file shadow"><h3 class="card-file-title">{name}</h3><div>ASL {asl} - Via Uno - Tel: 0746 123 - Aperta sab. dom. festivi: {weekend}</div><button>Download</button></div></div>'
    records = C.parse(card('Rieti','Rieti','SI') + card('Latina','Latina','NO'))
    assert records['Rieti']['weekend'] is True
    assert records['Latina']['weekend'] is False


def test_name_cleanup_and_asl_matching_are_unambiguous(monkeypatch):
    record={'asl':'Roma 1','phone':None,'weekend':True,'published_date':None}
    monkeypatch.setattr(C,'_snapshot',{'retrieved_at':datetime.now(timezone.utc).isoformat(),'records':{'Coppedè':record}})
    assert C.record({'ids':{'salutelazio_card':'<a href="/">Coppedè</a>'}})==record
    assert C.record({'name':"Casa della Comunità Coppede'",'asl':'ROMA 1'})==record
    assert C.record({'name':"Casa della Comunità Coppede'",'asl':'ROMA 2'}) is None


def test_document_metadata_uses_only_allowed_host():
    import json
    def script(url):
        value={'name':'Eroi','file':{'full':url}}
        return '<script>self.__next_f.push('+json.dumps([1,'17:'+json.dumps(value)])+')</script>'
    url='https://minio-vra-prod.servicelazio.it/bucket/eroi.pdf'
    assert C.documents(script(url))['Eroi']['document_url']==url
    assert not C.documents(script('https://malicious.example/eroi.pdf'))


def test_old_static_weekend_flag_is_not_a_current_closure(monkeypatch):
    from backend.app.data_sources import cdc,cdc_rome,cdc_hours
    monkeypatch.setattr(C,'_snapshot',{})
    monkeypatch.setattr(cdc_rome,'_records',{})
    monkeypatch.setattr(cdc_hours,'_records',{})
    result=cdc.opening_status({'opening':{'weekend_holidays_open':False}},datetime(2026,9,20,tzinfo=timezone.utc))
    assert result['status']!='closed' and result['known'] is False
