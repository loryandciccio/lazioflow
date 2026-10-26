from datetime import datetime, timedelta, timezone

import pytest

from backend.app.data_sources import cdc_hours as C
from backend.app.data_sources.cdc import opening_status
from bot.format import card


def test_service_hours_do_not_mean_whole_building_is_open(monkeypatch):
    page = '''<h2>Casa della Comunità San Nemesio Garbatella</h2> Via San Nemesio, 21
    <b>Orari Prelievi:</b> dal lunedì al sabato 7.45 - 10.30
    <b>Orario Ritiro Referti presso CUP:</b> dal lunedì al venerdì 11.00 - 18.45
    Referti sul Fascicolo Sanitario Elettronico Sede: Altro luogo'''
    records = C.parse(page,C.PRELIEVI)
    label = records['cdc:curalazio:35']
    assert '7.45 - 10.30' in label and 'intera sede' in label
    monkeypatch.setattr(C,'_records',{'cdc:curalazio:35':{'label':label,'source_url':C.PRELIEVI,
                                                       'retrieved_at':datetime.now(timezone.utc).isoformat()}})
    op = opening_status({'facility_id':'cdc:curalazio:35'},datetime.now(timezone.utc))
    assert not op['known'] and op['status'] != 'open'


def test_unknown_source_and_expired_data_are_not_accepted(monkeypatch):
    with pytest.raises(ValueError):
        C.parse('<p>Temporaneamente non disponibile</p>',C.PRELIEVI)
    monkeypatch.setattr(C,'_records',{'old':{'retrieved_at':(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()}})
    assert C.details('old') is None


def test_pharmacy_card_distinguishes_list_check_from_verified_hours():
    result = card({'rank':1,'name':'Farmacia','type':'pharmacy','distance_km':1,
                   'opening':{'label':'orario ordinario non disponibile','status':'unknown','known':False,
                              'retrieved_at':'2026-09-17T09:00:00+00:00','evidence_label':'Elenco turni/orari consultato'},
                   'score':{'travel_minutes':2}})
    assert 'Elenco turni/orari consultato' in result and 'fonte verificata' not in result
