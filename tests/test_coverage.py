from fastapi.testclient import TestClient

from backend.app.main import app
from bot.format import coverage_message


def test_coverage_contains_every_province_without_claiming_live_openings():
    result=TestClient(app).get('/coverage')
    assert result.status_code==200
    data=result.json()
    assert {p['code'] for p in data['provinces']}=={'RM','VT','RI','LT','FR'}
    assert sum(p['catalog']['pharmacies'] for p in data['provinces'])==8
    assert data['synthetic'] is True
    text=coverage_message(data)
    assert len(text)<4096
    assert 'non tutte le strutture effettivamente aperte' in text
    assert all(not p['pharmacies']['known_open'] for p in data['provinces'])
