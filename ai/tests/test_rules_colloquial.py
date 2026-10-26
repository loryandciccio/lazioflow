"""Frasi come le scrive la gente su Telegram: abbreviazioni, errori, niente accenti, romanesco leggero."""
import pytest

from ai.parser import normalize
from ai.rules_parser import classify, parse_rules

CASES = [
    # farmacia
    ("dove sta una farmacia aperta adesso", "FARMACIA"), ("farmacia notturna", "FARMACIA"), ("mi serve la tachipirina", "FARMACIA"),
    ("devo comprare una pomata", "FARMACIA"), ("farmacia x favore", "FARMACIA"), ("ho bisogno di medicine", "FARMACIA"),
    ("farmacia di turno stanotte", "FARMACIA"), ("mi serve uno sciroppo per la tosse", "FARMACIA"), ("serve un termometro", "FARMACIA"),
    # casa della comunità / territoriale
    ("devo fare le analisi del sangue", "ASSISTENZA_TERRITORIALE"), ("dove posso fare un vaccino", "ASSISTENZA_TERRITORIALE"),
    ("mi serve un infermiere per una medicazione", "ASSISTENZA_TERRITORIALE"), ("cerco la guardia medica", "ASSISTENZA_TERRITORIALE"),
    ("devo togliere i punti", "ASSISTENZA_TERRITORIALE"), ("mi serve una ricetta", "ASSISTENZA_TERRITORIALE"), ("cdc vicino", "ASSISTENZA_TERRITORIALE"),
    ("voglio parlare con un medico", "ASSISTENZA_TERRITORIALE"), ("dove misuro la pressione", "ASSISTENZA_TERRITORIALE"),
    # trauma
    ("so caduto dalle scale e me fa male er piede", "TRAUMA_MINORE"), ("ho preso una storta", "TRAUMA_MINORE"), ("caviglia gonfia", "TRAUMA_MINORE"),
    ("credo di essermi rotto il polso", "TRAUMA_MINORE"), ("sono scivolato e ho la spalla che fa male", "TRAUMA_MINORE"),
    ("botta al ginocchio giocando a calcio", "TRAUMA_MINORE"), ("nn riesco a camminare dopo una caduta", "TRAUMA_MINORE"),
    ("mi serve una radiografia", "TRAUMA_MINORE"), ("caduto in bici, gomito gonfio", "TRAUMA_MINORE"), ("colpo della strega", "TRAUMA_MINORE"),
    ("ho sbattuto il dito e si e gonfiato", "TRAUMA_MINORE"),
    # occhio
    ("occhio rosso e brucia", "OCCHIO"), ("mi e entrato qualcosa nell occhio", "OCCHIO"), ("vedo doppio", "OCCHIO"), ("orzaiolo", "OCCHIO"),
    ("ho perso una lente a contatto nell occhio", "OCCHIO"),
    # denti
    ("mal di denti", "DENTI"), ("mi si e rotto un dente", "DENTI"), ("ascesso alla gengiva", "DENTI"), ("mi fa male un molare", "DENTI"),
    # orl
    ("otite", "ORECCHIO_NASO_GOLA"), ("mi esce sangue dal naso", "ORECCHIO_NASO_GOLA"), ("non sento da un orecchio", "ORECCHIO_NASO_GOLA"),
    ("mal di gola con placche", "ORECCHIO_NASO_GOLA"), ("il bimbo ha qualcosa nel naso", "ORECCHIO_NASO_GOLA"),
    # gravidanza
    ("sono incinta di 20 settimane e ho un dubbio", "GRAVIDANZA"), ("mi serve un ginecologo", "GRAVIDANZA"), ("ho dolori mestruali forti", "GRAVIDANZA"),
    # pediatrico
    ("mio figlio ha la febbre", "PEDIATRICO"), ("la bimba ha vomitato", "PEDIATRICO"), ("bambino di 3 anni con la tosse", "PEDIATRICO"),
    ("mia figlia si e fatta male al braccio", "TRAUMA_MINORE"), ("il bimbo ha mal d orecchio", "ORECCHIO_NASO_GOLA"),
    # generico
    ("ho la febbre a 39", "PROBLEMA_GENERICO_NON_URGENTE"), ("sto male", "PROBLEMA_GENERICO_NON_URGENTE"), ("mal di pancia", "PROBLEMA_GENERICO_NON_URGENTE"),
    ("mi ha punto una vespa", "PROBLEMA_GENERICO_NON_URGENTE"), ("cistite", "PROBLEMA_GENERICO_NON_URGENTE"), ("ho la tosse da una settimana", "PROBLEMA_GENERICO_NON_URGENTE"),
    ("mi sono scottato con l acqua bollente", "PROBLEMA_GENERICO_NON_URGENTE"), ("mi sono tagliato con un coltello", "PROBLEMA_GENERICO_NON_URGENTE"),
    ("orticaria su tutto il corpo", "PROBLEMA_GENERICO_NON_URGENTE"), ("mi gira la testa", "PROBLEMA_GENERICO_NON_URGENTE"),
    # unknown / saluti
    ("ciao", "UNKNOWN"), ("grazie", "UNKNOWN"), ("che tempo fa", "UNKNOWN"), ("boh", "UNKNOWN"), ("non so", "UNKNOWN"),
    # emergenza (segnale: decide il verifier)
    ("mi manca l aria", "EMERGENZA"), ("credo sia un infarto", "EMERGENZA"), ("mio padre e svenuto", "EMERGENZA"),
]


@pytest.mark.parametrize("text,cat", CASES)
def test_colloquial(text, cat):
    got, conf, hits = classify(text)
    assert got == cat, (text, got, hits)
    p = normalize(parse_rules(text))
    assert p.category == cat


def test_ps_request_sets_intent_and_service():
    p = normalize(parse_rules("dove sta il pronto soccorso piu vicino"))
    assert p.intent == "emergency_room" and p.requested_service == "emergency_room" and p.category == "PROBLEMA_GENERICO_NON_URGENTE"
    p = normalize(parse_rules("ho preso una storta, qual e il ps meno affollato"))
    assert p.category == "TRAUMA_MINORE" and p.requested_service == "emergency_room"
    p = normalize(parse_rules("voglio andare in ospedale"))
    assert p.requested_service == "emergency_room"


def test_child_and_body_area():
    p = normalize(parse_rules("mio figlio di 8 anni è caduto e ha male al ginocchio"))
    assert p.category == "TRAUMA_MINORE" and p.age_group == "child" and p.body_area == "leg_knee"
    assert normalize(parse_rules("storta alla caviglia")).body_area == "ankle_foot"
