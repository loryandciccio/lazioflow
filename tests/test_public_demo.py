"""Public release protections: synthetic data must not become real-world advice or outbound fetches."""
import socket

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from bot import format as formatting, keyboards


def test_demo_requests_do_not_open_network_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The public synthetic demo must not open an outbound connection")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    with TestClient(app) as client:
        assert client.post('/understand', json={'text': 'cerco una farmacia'}).status_code == 200
        for category in ['FARMACIA', 'TRAUMA_MINORE']:
            response = client.post('/recommend', json={
                'category': category, 'location': {'lat': 41.9028, 'lng': 12.4964}})
            assert response.status_code == 200
            result = response.json()
            assert result['synthetic'] is True and 'DEMO' in result['disclaimer']
            assert result['recommendations']
            assert all(r['name'].startswith('DEMO ') and not r['maps_url'] for r in result['recommendations'])
            assert all(r['sources'][0]['source_name'] == 'Synthetic demo catalogue' for r in result['recommendations'])
            assert 'strutture fittizie' in formatting.results_message(result, result['recommendations'])
            buttons = keyboards.results(result['recommendations'], 'nearest', with_presets=False)
            assert not any(button.url for row in buttons.inline_keyboard for button in row)
        assert client.get('/sources').json()['synthetic'] is True


def test_demo_catalogue_disables_collectors_even_if_live_is_requested(monkeypatch):
    import importlib
    from backend.app import config
    monkeypatch.setenv('LAZIOFLOW_LIVE', '1')
    try:
        importlib.reload(config)
        assert config.SYNTHETIC_DATA and config.LIVE_DISABLED
    finally:
        monkeypatch.setenv('LAZIOFLOW_LIVE', '0')
        importlib.reload(config)


def test_poller_refuses_synthetic_catalogue_before_any_network_request(monkeypatch, capsys):
    from poller import poller
    monkeypatch.setattr('sys.argv', ['poller', '--once'])
    monkeypatch.setattr(poller, 'fetch_facilities', lambda: pytest.fail('network path must not be entered'))
    with pytest.raises(SystemExit) as error:
        poller.main()
    assert error.value.code == 2
    assert 'Synthetic demo catalogue' in capsys.readouterr().err
