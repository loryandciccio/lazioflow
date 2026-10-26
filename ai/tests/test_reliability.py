"""Regressioni realistiche: anatomia, farmaci già presi e guasti dei provider."""
import asyncio
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from ai import groq_client
from ai.parser import normalize, parse, parse_groq, parse_llm
from ai.rules_parser import classify, parse_rules

parser_module = importlib.import_module('ai.parser')
explain_module = importlib.import_module('ai.explain')


@pytest.mark.parametrize('text,area', [
    ('mi fa male il malleolo', 'ankle_foot'),
    ('ho dolore al tendine d’Achille', 'ankle_foot'),
    ('ho male ai talloni', 'ankle_foot'),
    ('mi fa male il calcagno', 'ankle_foot'),
    ('ho dolore al metatarso', 'ankle_foot'),
    ('ho male agli alluci', 'ankle_foot'),
    ('mi fanno male le caviglie', 'ankle_foot'),
    ('dolore ai piedi', 'ankle_foot'),
    ('mi fa male la rotula', 'leg_knee'),
    ('dolore alle ginocchia', 'leg_knee'),
    ('dolore al menisco', 'leg_knee'),
    ('ho male al polpaccio', 'leg_knee'),
    ('dolore all’avambraccio', 'arm_hand'),
    ('dolore ai polsi', 'arm_hand'),
    ('mi fa male il bicipite', 'arm_hand'),
])
def test_localized_anatomical_pain_is_not_generic(text, area):
    parsed = normalize(parse_rules(text))
    assert parsed.category == 'TRAUMA_MINORE'
    assert parsed.problem_domain == 'musculoskeletal'
    assert parsed.body_area == area
    assert parsed.requested_service is None


@pytest.mark.parametrize('text,category,age', [
    ('la bambina ha la febbre e non le scende con la tachipirina', 'PEDIATRICO', 'child'),
    ('ho mal di testa, ho preso la tachipirina ma non passa', 'PROBLEMA_GENERICO_NON_URGENTE', 'unknown'),
    ('mio figlio di 20 anni ha la febbre', 'PROBLEMA_GENERICO_NON_URGENTE', 'adult'),
    ('ho 35 anni e mi serve uno sciroppo per la tosse', 'FARMACIA', 'adult'),
    ('mia madre ha male al malleolo', 'TRAUMA_MINORE', 'adult'),
    ('mio nipote piccolo ha male al malleolo', 'TRAUMA_MINORE', 'child'),
    ('ho la tosse da 3 mesi', 'PROBLEMA_GENERICO_NON_URGENTE', 'unknown'),
    ('ho la tosse da 8 anni', 'PROBLEMA_GENERICO_NON_URGENTE', 'unknown'),
    ('mio figlio ha mal di gola da 3 anni', 'ORECCHIO_NASO_GOLA', 'child'),
    ('ho finito la tachipirina e voglio comprarla', 'FARMACIA', 'unknown'),
])
def test_drug_context_and_patient_age(text, category, age):
    parsed = normalize(parse_rules(text))
    assert parsed.category == category
    assert parsed.age_group == age


def test_normalization_preserves_words_and_anatomical_boundaries():
    assert parse_rules('mi è entrato qualcosa nell’occhio').category == 'OCCHIO'
    assert parse_rules('sono stanca').body_area == 'whole_body'
    assert classify('devo prenotare un ristorante')[0] == 'UNKNOWN'
    parsed = normalize(parse_rules('devo prenotare una visita cardiologica'))
    assert parsed.intent == 'scheduled_care' and parsed.requested_service == 'scheduled_visit'


@pytest.fixture
def groq_enabled(monkeypatch):
    monkeypatch.setenv('LAZIOFLOW_AI', '1')
    monkeypatch.setenv('LLM_PROVIDER', 'groq')
    monkeypatch.setenv('GROQ_API_KEY', 'synthetic-test-key')


async def test_parser_deadline_falls_back_with_anatomy(groq_enabled, monkeypatch):
    cancelled = asyncio.Event()

    async def hangs(text):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(parser_module, 'parse_groq', hangs)
    monkeypatch.setattr(parser_module, 'LLM_TIMEOUT_S', 0.01)
    result = await parse('mi fa male il malleolo')
    assert result.parser == 'rules' and result.note == 'fallback: timeout'
    assert result.parsed.body_area == 'ankle_foot'
    assert cancelled.is_set()


async def test_rate_limit_is_reported_and_does_not_log_private_response(groq_enabled, monkeypatch, caplog):
    mock = AsyncMock(side_effect=groq_client.GroqError(429))
    monkeypatch.setattr(parser_module, 'parse_groq', mock)
    result = await parse('la bambina ha la febbre e non scende con la tachipirina')
    assert result.note == 'fallback: rate_limit'
    assert result.parsed.category == 'PEDIATRICO'
    assert mock.await_count == 1
    assert 'bambina' not in caplog.text


@pytest.mark.parametrize('confidence', [None, True, -1, 101, 0.9, '90'])
async def test_invalid_groq_confidence_uses_rules(groq_enabled, monkeypatch, confidence):
    data = parse_rules('mi fa male il malleolo').model_dump()
    data['confidence'] = confidence
    monkeypatch.setattr(groq_client, 'chat', AsyncMock(return_value=(json.dumps(data), {})))
    result = await parse('mi fa male il malleolo')
    assert result.parser == 'rules' and result.parsed.body_area == 'ankle_foot'


async def test_groq_percentage_is_validated_and_converted(monkeypatch):
    data = parse_rules('mi fa male il malleolo').model_dump()
    data['confidence'] = 92
    monkeypatch.setattr(groq_client, 'chat', AsyncMock(return_value=(json.dumps(data), {})))
    result = await parse_groq('mi fa male il malleolo')
    assert result.parsed.confidence == .92 and result.parser == 'llm'


@pytest.fixture
def mock_http(monkeypatch):
    """Esegue la costruzione HTTP vera contro un transport in memoria."""
    real_client = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(groq_client.httpx, 'AsyncClient',
                            lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))

    return install


@pytest.mark.parametrize('payload', [
    {'choices': []},
    {'choices': [{'message': {'content': None}, 'finish_reason': 'stop'}]},
    {'choices': [{'message': {'content': '{"ok": true}'}, 'finish_reason': 'length'}]},
    {'choices': [{'message': {'content': 'testo', 'refusal': 'refused'}, 'finish_reason': 'stop'}]},
])
async def test_transport_rejects_incomplete_responses(groq_enabled, mock_http, payload):
    mock_http(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await groq_client.chat('system', 'user', max_tokens=100, timeout_s=1)


async def test_transport_rate_limit_contains_no_remote_body(groq_enabled, mock_http):
    mock_http(lambda request: httpx.Response(429, json={'error': {'message': 'PRIVATE_ACCOUNT_AND_SYMPTOMS'}}))
    with pytest.raises(groq_client.GroqError) as caught:
        await groq_client.chat('system', 'user', max_tokens=100, timeout_s=1)
    assert caught.value.status_code == 429
    assert 'PRIVATE' not in str(caught.value)


async def test_other_groq_models_use_json_object_mode(groq_enabled, monkeypatch, mock_http):
    monkeypatch.setattr(groq_client, 'GROQ_MODEL', 'llama-3.3-70b-versatile')

    def handle(request):
        body = json.loads(request.content)
        assert body['response_format'] == {'type': 'json_object'}
        assert 'confidence' in body['messages'][0]['content']
        return httpx.Response(200, json={'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}]})

    mock_http(handle)
    await groq_client.chat('system', 'user', max_tokens=100, timeout_s=1, schema=parser_module._groq_schema())


async def test_anthropic_client_closes_on_failure(monkeypatch):
    import anthropic
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.messages.parse.side_effect = RuntimeError('synthetic failure')
    monkeypatch.setattr(anthropic, 'AsyncAnthropic', lambda **kwargs: client)
    with pytest.raises(RuntimeError):
        await parse_llm('synthetic')
    client.__aexit__.assert_awaited_once()


async def test_explanation_deadline_uses_verified_template(groq_enabled, monkeypatch):
    async def hangs(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(groq_client, 'chat', hangs)
    monkeypatch.setattr(explain_module, 'LLM_TIMEOUT_S', .01)
    recs = [{'rank': 1, 'name': 'Struttura sintetica', 'type': 'emergency_room', 'distance_km': 2,
             'reasons': ['distanza 2 km'], 'warnings': ['attesa non disponibile']}]
    result = await explain_module.explain('sintetico', recs)
    assert result['generator'] == 'rules'
    assert 'distanza 2 km' in result['text'] and 'attesa non disponibile' in result['text']
