"""Spec §16.1: hard red flag, ambiguo, nessuna flag, conflitto LLM vs safety, testo vuoto, linguaggio colloquiale."""
import pytest

from safety.verifier import check, load_rules, merge_with_llm, normalize

HARD = [
    "Ho un dolore al petto fortissimo e mi manca l'aria",
    "mio padre non risponde e non si sveglia",
    "non riesco a parlare bene e ho la bocca storta",
    "mi sono tagliato e il sangue non si ferma",
    "ha battuto la testa e ora vomita",
    "mio figlio ha convulsioni",
    "ho la gola gonfia dopo aver mangiato le noci, faccio fatica a respirare",
    "Ha bevuto la candeggina",
    "voglio farla finita",
    "sto soffocando",
    "nn riesco a respirare aiuto",                       # colloquiale, senza accenti
    "È SVENUTA E NON REAGISCE",                           # maiuscole/accenti
    "credo sia un infarto",
    "mal di testa improvviso mai avuto così",           # regola stroke_sudden_severe_headache (Lorenzo)
]
UNCERTAIN = [
    "ho un dolore lancinante alla pancia",
    "sono incinta e ho delle perdite di sangue",
    "il mio bambino di 3 mesi ha la febbre",
    "mia nonna è caduta e adesso è confusa",
    "non so cosa ho ma peggiora rapidamente",
    "ho sangue nelle feci",
]
NO_FLAG = [
    "Sono sceso dalle scale, ho preso una storta al piede e mi fa molto male.",
    "Cerco una farmacia aperta",
    "Vorrei trovare un PS vicino",
    "Mi serve una Casa della Comunità",
    "Ho mal di gola da due giorni",
    "mi è entrato qualcosa nell'occhio",
    "ho un dente che mi fa male",
    "che ore sono?",
    "Non so dove andare",
]


@pytest.mark.parametrize("text", HARD)
def test_hard_red_flags(text):
    r = check(text)
    assert r.status == "HARD_RED_FLAG", (text, r.matched_rules)
    assert r.allowed_actions == ["SHOW_112"] and "112" in r.message
    assert all(m.source.get("name") for m in r.matched_rules)


@pytest.mark.parametrize("text", UNCERTAIN)
def test_uncertain(text):
    r = check(text)
    assert r.status == "UNCERTAIN", (text, r.matched_rules)
    assert "SHOW_116117" in r.allowed_actions and "USER_EXPLICIT_CHOICE" in r.allowed_actions
    assert "ROUTE" not in r.allowed_actions


@pytest.mark.parametrize("text", NO_FLAG)
def test_no_flag(text):
    r = check(text)
    assert r.status == "NO_FLAG_DETECTED", (text, r.matched_rules)
    assert r.message is None and "ROUTE" in r.allowed_actions
    assert "non che il caso sia lieve" in r.note


def test_empty_text():
    for t in ("", "   ", None):
        r = check(t)
        assert r.status == "NO_FLAG_DETECTED" and r.matched_rules == []


def test_llm_flag_raises_to_uncertain_never_lowers():
    r = check("mi sento strano", emergency_detected_by_llm=True)
    assert r.status == "UNCERTAIN" and r.matched_rules[0].rule_id == "llm_emergency_flag"
    hard = check("dolore al petto", emergency_detected_by_llm=False)
    assert hard.status == "HARD_RED_FLAG"                 # l'LLM non può abbassare
    assert merge_with_llm(hard, False).status == "HARD_RED_FLAG"
    assert merge_with_llm(check("storta al piede"), True).status == "UNCERTAIN"
    assert merge_with_llm(check("storta al piede"), False).status == "NO_FLAG_DETECTED"


def test_negation_is_deliberately_not_handled():
    assert check("non ho dolore al petto").status == "HARD_RED_FLAG"


def test_every_rule_has_source_and_compiles():
    rules = load_rules()
    assert len(rules) >= 15
    for r in rules:
        assert r["action"] in ("EMERGENCY", "UNCERTAIN") and r["patterns"] and r["source"]["name"]
        if r["source"]["verified_at"]:
            assert r["source"]["url"].startswith("http")


def test_normalize():
    assert normalize("  Perché   NON   respira?! ") == "perche non respira?!"


# Regressione safety v2: frasi realistiche e colloquiali, una per famiglia di regole.
EXPANDED_HARD = [
    "all improvviso vedo tutto offuscato",
    "ho perso l'equilibrio all'improvviso e sbandavo",
    "mal di testa all'improvviso fortissimo mai avuto",
    "ho battuto la testa e continuo a vomitare",
    "dopo la botta in testa vedo doppio",
    "dopo il trauma alla testa sono confuso e sonnolento",
    "dopo la caduta e la botta in testa esce sangue dall'orecchio",
    "sta soffocando con un boccone in gola",
    "stava annegando e ora non risponde",
    "dopo una puntura ho difficoltà a ingoiare e orticaria",
    "dopo l'allergia ho le labbra blu",
    "con questo caldo è svenuto ed è confuso",
    "ho bevuto del detersivo credo di essermi avvelenato",
    "sono stato investito e mi sono fatto molto male",
    "ho un'ustione estesa sul viso",
]


@pytest.mark.parametrize("text", EXPANDED_HARD)
def test_expanded_hard_red_flags(text):
    r = check(text)
    assert r.status == "HARD_RED_FLAG", (text, [(m.rule_id, m.matched_text) for m in r.matched_rules])
    assert r.allowed_actions == ["SHOW_112"]

EXPANDED_UNCERTAIN = [
    "ho fatto un tamponamento e mi fa male il collo",
    "sono caduto dalla bici e ho dolore alla spalla",
    "ho un dolore alla pancia fortissimo arrivato all'improvviso",
    "dopo la puntura di vespa ho orticaria e mi gira la testa",
    "sono stato tutto il giorno al caldo, ho nausea e crampi",
    "continuo a vomitare e non riesco a tenere giù l'acqua",
    "da poco non sento bene una gamba e ho uno strano formicolio",
]


@pytest.mark.parametrize("text", EXPANDED_UNCERTAIN)
def test_expanded_uncertain_flags(text):
    r = check(text)
    assert r.status == "UNCERTAIN", (text, [(m.rule_id, m.matched_text) for m in r.matched_rules])
    assert "SHOW_116117" in r.allowed_actions and "ROUTE" not in r.allowed_actions


@pytest.mark.parametrize("text", [
    "ho preso una storta al piede",
    "mi sono scottato un dito con acqua calda",
    "ho mal di testa da ieri ma non è improvviso",
    "ho un po' di orticaria ma respiro normalmente",
    "cerco una farmacia di turno",
])
def test_expansion_does_not_block_common_low_risk_requests(text):
    assert check(text).status == "NO_FLAG_DETECTED", text


@pytest.mark.parametrize('text,rule_id,status', [
    ('mi manca l’aria', 'breathing_difficulty', 'HARD_RED_FLAG'),
    ("mi manca l'aria", 'breathing_difficulty', 'HARD_RED_FLAG'),
    ('mi manca l aria', 'breathing_difficulty', 'HARD_RED_FLAG'),
    ('mancanza d’aria', 'breathing_difficulty', 'HARD_RED_FLAG'),
    ('mancanza di aria', 'breathing_difficulty', 'HARD_RED_FLAG'),
    ('non respiro', 'breathing_difficulty', 'HARD_RED_FLAG'),
    ('all’improvviso non vedo bene', 'stroke_sudden_vision', 'HARD_RED_FLAG'),
    ('ho sangue nell’urina', 'unc_blood_in_vomit_stool', 'UNCERTAIN'),
])
def test_typographic_apostrophes_and_normalized_rules(text, rule_id, status):
    result = check(text)
    assert result.status == status
    assert rule_id in [match.rule_id for match in result.matched_rules]
