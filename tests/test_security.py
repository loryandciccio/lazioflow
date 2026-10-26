from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.security import AccessGuard


def client(**settings):
    app = FastAPI()
    app.add_middleware(AccessGuard, **settings)
    @app.get('/health')
    @app.post('/parse')
    def endpoint():
        return {'ok': True}
    return TestClient(app)


def test_production_fails_closed_without_key():
    assert client(api_key='', production=True).get('/health').status_code == 503


def test_authentication_and_no_store():
    c = client(api_key='secret')
    assert c.get('/health').status_code == 401
    assert c.get('/health', headers={'X-API-Key': 'wrong'}).status_code == 401
    good = c.get('/health', headers={'X-API-Key': 'secret'})
    assert good.status_code == 200 and good.headers['cache-control'] == 'no-store'


def test_global_budget_and_recovery(monkeypatch):
    from backend.app import security
    now = [100.0]
    monkeypatch.setattr(security.time, 'monotonic', lambda: now[0])
    c = client(api_key='', limit=2)
    assert c.get('/health').status_code == 200
    assert c.get('/health').status_code == 200
    limited = c.get('/health')
    assert limited.status_code == 429 and limited.headers['retry-after'] == '60'
    now[0] += 61
    assert c.get('/health').status_code == 200


def test_ai_budget_does_not_block_non_ai_routes(monkeypatch):
    monkeypatch.setenv('AI_REQUESTS_PER_MINUTE', '1')
    c = client(api_key='', limit=10)
    assert c.post('/parse').status_code == 200
    assert c.post('/parse').status_code == 429
    assert c.get('/health').status_code == 200
