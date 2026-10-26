"""Spec §16.2: almeno 30 frasi. Girano offline sul parser a regole; con ANTHROPIC_API_KEY si esegue anche l'LLM
(test marcato) e si verifica che rispetti lo schema chiuso."""
import json
import os

import pytest
from pydantic import ValidationError

from ai.parser import normalize, parse, parse_rules, reject_forbidden
from ai.schemas import ParsedIntent

CASES = [  # (testo, categoria attesa, age_group atteso o None)
    ("Cerco una farmacia aperta", "FARMACIA", None),
    ("farmacia di turno vicino a me", "FARMACIA", None),
    ("mi serve uno sciroppo per la tosse", "FARMACIA", None),
    ("Vorrei trovare un PS vicino", "PROBLEMA_GENERICO_NON_URGENTE", None),
    ("qual è il pronto soccorso meno affollato?", "PROBLEMA_GENERICO_NON_URGENTE", None),
    ("Mi serve una Casa della Comunità", "ASSISTENZA_TERRITORIALE", None),
    ("devo fare un prelievo del sangue", "ASSISTENZA_TERRITORIALE", None),
    ("dove faccio il vaccino antinfluenzale", "ASSISTENZA_TERRITORIALE", None),
    ("mi serve la guardia medica", "ASSISTENZA_TERRITORIALE", None),
    ("Sono caduto e mi fa male la caviglia", "TRAUMA_MINORE", None),
    ("Sono sceso dalle scale, ho preso una storta al piede e mi fa molto male.", "TRAUMA_MINORE", None),
    ("ho il polso gonfio dopo una caduta in bici", "TRAUMA_MINORE", None),
    ("penso di essermi rotto un dito", "TRAUMA_MINORE", None),
    ("mio figlio di 8 anni è caduto e ha male al ginocchio", "TRAUMA_MINORE", "child"),
    ("la bimba ha la febbre da ieri", "PEDIATRICO", "child"),
    ("il mio bambino ha l'otite", "ORECCHIO_NASO_GOLA", "child"),
    ("mi è entrato qualcosa nell'occhio", "OCCHIO", None),
    ("ho l'occhio rosso e mi brucia", "OCCHIO", None),
    ("mi sanguina il naso ma poco", "ORECCHIO_NASO_GOLA", None),
    ("ho mal di gola da tre giorni", "ORECCHIO_NASO_GOLA", None),
    ("sono incinta e ho un dubbio sulle analisi", "GRAVIDANZA", None),
    ("ho un dente rotto", "DENTI", None),
    ("mal di denti fortissimo", "DENTI", None),
    ("ho la febbre a 38 e mi sento male", "PROBLEMA_GENERICO_NON_URGENTE", None),
    ("ho mal di pancia da stamattina", "PROBLEMA_GENERICO_NON_URGENTE", None),
    ("Non so dove andare", "UNKNOWN", None),
    ("che ore sono?", "UNKNOWN", None),
    ("ciao", "UNKNOWN", None),
    ("mi consigli un ristorante?", "UNKNOWN", None),
    ("ho un dolore al petto e mi manca l'aria", "EMERGENZA", None),
    ("mia madre è svenuta", "EMERGENZA", None),
    ("non riesco a respirare", "EMERGENZA", None),
    ("ho una puntura di insetto che prude", "PROBLEMA_GENERICO_NON_URGENTE", None),
    ("", "UNKNOWN", None),
]


@pytest.mark.parametrize("text,cat,age", CASES)
def test_rules_parser_closed_categories(text, cat, age):
    p = normalize(parse_rules(text))
    assert p.category == cat, (text, p)
    if age:
        assert p.age_group == age
    if cat == "EMERGENZA":
        assert p.intent == "emergency" and p.emergency_detected_by_llm and not p.needs_location
    elif cat != "UNKNOWN":
        assert p.needs_location


def test_schema_rejects_forbidden_and_extra_fields():
    base = dict(intent="seek_care", category="TRAUMA_MINORE", problem_domain="musculoskeletal", body_area="ankle_foot",
                requested_service=None, age_group="unknown", needs_location=True, emergency_detected_by_llm=False, confidence=0.9)
    ParsedIntent(**base)
    with pytest.raises(ValidationError):
        ParsedIntent(**base, severity="mild")
    with pytest.raises(ValidationError):
        ParsedIntent(**base, diagnosis="distorsione")
    with pytest.raises(ValidationError):
        ParsedIntent(**{**base, "category": "DISTORSIONE"})
    with pytest.raises(ValidationError):
        ParsedIntent(**{**base, "confidence": 1.7})
    with pytest.raises(ValueError):
        reject_forbidden({**base, "triage_code": "verde"})


def test_llm_flag_true_when_emergency_intent():
    p = normalize(ParsedIntent(intent="emergency", category="UNKNOWN", problem_domain="unknown", body_area="unknown",
                               requested_service=None, age_group="unknown", needs_location=True,
                               emergency_detected_by_llm=False, confidence=0.4))
    assert p.category == "EMERGENZA" and p.emergency_detected_by_llm and not p.needs_location


async def test_parse_never_raises_and_reports_engine(monkeypatch):
    monkeypatch.setenv("LAZIOFLOW_AI", "0")
    r = await parse("cerco una farmacia")
    assert r.parser == "rules" and r.parsed.category == "FARMACIA"
    assert json.loads(r.model_dump_json())["parsed"]["intent"] == "pharmacy"


@pytest.mark.skipif(os.getenv("RUN_LIVE_AI_TESTS") != "1" or not os.getenv("ANTHROPIC_API_KEY"),
                    reason="test live opt-in: RUN_LIVE_AI_TESTS=1 e ANTHROPIC_API_KEY")
async def test_llm_parser_respects_schema():
    from ai.parser import parse_llm
    for text, cat, _ in CASES[:12]:
        r = await parse_llm(text)
        assert r.parser == "llm" and r.parsed.category in ParsedIntent.model_fields["category"].annotation.__args__
