from datetime import datetime, timezone, timedelta

import pytest

from backend.app.data_sources import cdc_rome as C, pharmacy_contacts as P


def test_directory_does_not_mix_name_with_address():
    d=C.Directory(C.ROOTS['Roma 1'])
    d.feed('<a href="/casedellasalute-territoriali/casa-della-comunita-eroi">Casa della Comunità Eroi Via Fra Albenzio, 10</a>')
    assert list(d.links.values())==['Casa della Comunità Eroi']


def test_rome_service_hours_keep_their_scope(monkeypatch):
    page='''<div class="details-ticket"><a class="details-header">Orario Apertura Presidio</a>
    <div class="details-content"><p>Apertura dal lunedì al venerdì 8.00-18.00.</p><p>Sabato solo su appuntamento 8.00-12.00.</p></div></div>'''
    services=C.parse_roma1(page)
    assert 'solo su appuntamento' in services[0]['text']
    monkeypatch.setattr(C,'_records',{'one':{'retrieved_at':datetime.now(timezone.utc).isoformat(),'services':services,'source_url':'https://www.aslroma1.it/test'}})
    result=C.details('one')
    assert not result['known'] and result['status']!='open'
    assert 'solo su appuntamento' in result['label']
    C._records['one']['retrieved_at']=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
    assert C.details('one') is None


def test_prelievi_are_bound_to_the_correct_site():
    catalog=[{'facility_id':'a','type':'community_house','name':'Casa della Comunità Uno','asl':'ROMA 2'},
             {'facility_id':'b','type':'community_house','name':'Casa della Comunità Due','asl':'ROMA 2'}]
    page='Sede: Casa della Comunità Uno Via Roma 1 Telefono: 06123 Orari Prelievi: lunedì 8.00-10.00 Orario Ritiro Referti presso CUP: 11.00-12.00 Referti sul FSE Sede: Casa della Comunità Due Via Roma 2 Telefono: 06456 Orari Prelievi: martedì 9.00-11.00 Orario Ritiro Referti presso CUP: 12.00-13.00 Referti sul FSE'
    result=C.parse_prelievi(page,catalog)
    assert result['a'][0]['text']=='lunedì 8.00-10.00'
    assert result['b'][0]['text']=='martedì 9.00-11.00'


def test_pharmacy_phone_matching_requires_town_and_unique_number(monkeypatch):
    page='''Pagina 1 di 2<table><tr><td class="pharmacy_address">VIA ROMA 1 - 00100 ROMA (RM)</td><td class="pharmacy_phone">06.123456</td></tr></table>'''
    rows,number,total=P.parse(page)
    assert (number,total)==(1,2)
    monkeypatch.setattr(P,'_snapshot',{'retrieved_at':datetime.now(timezone.utc).isoformat(),'rows':rows})
    f={'type':'pharmacy','address':'Via Roma, 1, 00100 Roma (RM)','phone':None}
    assert P.overlay(f)['phone']=='06123456'
    assert P.overlay({**f,'address':'Via Roma, 1, 00044 Frascati (RM)'})['phone'] is None
    P._snapshot['rows'].append({**rows[0],'phone':'06999999'})
    assert P.overlay(f)['phone'] is None
    with pytest.raises(ValueError):
        P.parse('<html>Temporaneamente non disponibile</html>')
