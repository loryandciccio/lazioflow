"""Parser deterministico a vocabolario (fallback senza LLM, e rete di sicurezza con LLM).

Come funziona: il testo viene normalizzato (minuscolo, senza accenti, abbreviazioni da chat: 'ke'->'che', 'nn'->'non',
'xche'->'perche'); ogni categoria ha un vocabolario di termini con un peso; i termini di 4+ lettere matchano anche
con desinenze diverse (caviglia/caviglie, gonfio/gonfia/gonfiore). Vince la categoria col punteggio più alto; a parità
vince quella più specifica (ordine di PRIORITY). Bambino e "voglio il pronto soccorso" sono segnali trasversali.
Non è un modello: è un elenco. Va allargato ogni volta che una frase reale finisce in UNKNOWN o in una categoria sbagliata.
"""
from __future__ import annotations

import re
import unicodedata

from .schemas import ParsedIntent

CHAT = {r"\bnn\b": "non", r"\bke\b": "che", r"\bxke\b|\bxche\b|\bperke\b": "perche", r"\bcmq\b": "comunque", r"\bqlc\b|\bqualcs\b": "qualcosa",
        r"\bsn\b": "sono", r"\bx\b": "per", r"\bkm\b": "km", r"\bps\b": "pronto soccorso", r"\bp\.s\.": "pronto soccorso", r"\bcdc\b": "casa della comunita",
        r"\bdott\b|\bdr\b": "dottore"}


def norm(text: str) -> str:
    # Prima di scartare i caratteri non ASCII: altrimenti l’occhio diventa locchio.
    text = (text or "").translate(str.maketrans({c: " " for c in "'’‘ʼ＇-‑–—"}))
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    for k, v in CHAT.items():
        t = re.sub(k, v, t)
    return re.sub(r"\s+", " ", t).strip()


# (termine, peso). Termini >= 4 lettere: match sul prefisso (desinenze libere). Frasi multi-parola: match esatto sul prefisso.
LEX: dict[str, list[tuple[str, int]]] = {
    "FARMACIA": [("farmacia", 5), ("farmacie", 5), ("parafarmacia", 5), ("di turno", 4), ("farmacia aperta", 5), ("farmacia notturna", 5),
                 ("medicina", 2), ("medicine", 2), ("medicinal", 3), ("farmaco", 3), ("farmaci", 3), ("sciroppo", 5), ("antidolorific", 4),
                 ("tachipirina", 5), ("aspirina", 5), ("brufen", 5), ("oki", 2), ("cerott", 3), ("pastigli", 2), ("compress", 2), ("pillol", 2),
                 ("antibiotic", 2), ("pomata", 5), ("collirio", 5), ("test covid", 3), ("tampone", 2), ("test di gravidanza", 4), ("bende", 2),
                 ("siringa", 2), ("termometro", 3), ("disinfettante", 3)],
    "ASSISTENZA_TERRITORIALE": [("casa della comunita", 6), ("casa di comunita", 6), ("case della comunita", 6), ("prelievo", 5), ("prelievi", 5),
                                ("analisi del sangue", 5), ("esami del sangue", 5), ("infermier", 5), ("vaccin", 5), ("pua", 4), ("medico di base", 5),
                                ("medico di famiglia", 5), ("medico curante", 5), ("guardia medica", 5), ("continuita assistenziale", 5), ("ricetta", 4),
                                ("impegnativa", 4), ("medicazion", 4), ("togliere i punti", 5), ("punti di sutura", 3), ("iniezione", 4), ("misurare la pressione", 5), ("misur", 4),
                                ("certificato", 3), ("consultorio", 4), ("assistente sociale", 3), ("anziano da seguire", 3), ("cure domiciliari", 4),
                                ("ambulatorio", 3), ("visita di controllo", 4), ("controllo", 1), ("terapia", 2), ("fisioterap", 3), ("psicolog", 3),
                                ("dottore", 2), ("un medico", 3), ("dal medico", 3), ("un dottore", 3)],
    "TRAUMA_MINORE": [("storta", 6), ("distorsion", 6), ("cadut", 4), ("cascat", 4), ("scivolat", 4), ("inciampat", 4), ("contusion", 5), ("botta", 4),
                      ("slogat", 5), ("lussazion", 5), ("frattur", 5), ("rott", 3), ("spaccat", 3), ("incrinat", 4), ("cavigli", 4), ("pols", 4),
                      ("ginocchi", 4), ("pied", 4), ("gamb", 3), ("bracci", 3), ("spall", 4), ("mano", 2), ("mani", 2), ("dito", 3), ("dita", 3), ("gomit", 4), ("anca", 3),
                      ("malleol", 6), ("tallon", 6), ("calcagn", 6), ("alluc", 6), ("metatars", 6), ("achille", 6),
                      ("rotul", 6), ("menisc", 6), ("polpacc", 6), ("avambracc", 6), ("bicipit", 6), ("tricipit", 6),
                      ("costol", 3), ("clavicola", 4), ("tibia", 4), ("femore", 4), ("gonfi", 2), ("livido", 3), ("ematoma", 3), ("non riesco a camminare", 5),
                      ("non riesco ad appoggiare", 5), ("non riesco a muovere", 3), ("zoppic", 4), ("incidente in bici", 4), ("caduto in moto", 4),
                      ("caduto dalla bici", 5), ("giocando a calcio", 3), ("partita", 1), ("ortopedic", 5), ("radiografia", 4), ("lastra", 4), ("gesso", 4),
                      ("trauma", 4), ("preso un colpo", 3), ("mi sono fatto male", 3), ("mi sono fatta male", 3), ("sbattuto", 3), ("stirament", 4), ("strappo", 4),
                      ("muscol", 2), ("tendin", 3), ("schiena bloccata", 4), ("colpo della strega", 5), ("cervical", 3)],
    "OCCHIO": [("occhio", 6), ("occhi", 5), ("vista", 3), ("vedo male", 4), ("vedo doppio", 5), ("vedo annebbiato", 5), ("congiuntivit", 6), ("orzaiolo", 6),
               ("corpo estraneo", 2), ("palpebra", 5), ("oculist", 6), ("lenti a contatto", 4), ("lampi di luce", 4), ("mosche volanti", 4), ("occhio rosso", 6)],
    "DENTI": [("dente", 6), ("denti", 6), ("molare", 6), ("gengiv", 5), ("dentist", 6), ("mascella", 4), ("otturazion", 5), ("carie", 5), ("ascesso", 5),
              ("bocca gonfia", 4), ("devitalizz", 5), ("apparecchio", 3)],
    "ORECCHIO_NASO_GOLA": [("orecchi", 6), ("otite", 6), ("naso", 4), ("gola", 4), ("epistassi", 6), ("sangue dal naso", 6), ("tonsill", 6), ("non sento", 4),
                           ("tappo", 3), ("sinusit", 5), ("laringit", 5), ("raucedine", 5), ("senza voce", 5), ("otorino", 6), ("orl", 4), ("corpo estraneo nel naso", 6),
                           ("qualcosa nel naso", 5), ("qualcosa nell orecchio", 6), ("vertigin", 2), ("mal di gola", 5), ("placche", 5)],
    "GRAVIDANZA": [("incinta", 6), ("gravid", 6), ("ginecolog", 6), ("mestrua", 5), ("ciclo", 3), ("perdite", 3), ("ovai", 5), ("utero", 5),
                   ("contrazion", 5), ("ostetric", 6), ("allattament", 5), ("settimana di gravidanza", 6), ("test positivo", 3), ("aborto", 5), ("consultorio", 3)],
    "PEDIATRICO": [("bambin", 5), ("bimb", 5), ("figlio", 5), ("figlia", 5), ("neonat", 6), ("lattante", 6), ("pediatr", 6), ("nipotin", 5), ("ragazzin", 4)],
    "PROBLEMA_GENERICO_NON_URGENTE": [("febbre", 4), ("influenz", 4), ("raffreddor", 4), ("tosse", 4), ("mal di testa", 4), ("mal di pancia", 4),
                                      ("mal di stomaco", 4), ("mal di schiena", 4), ("nausea", 4), ("vomit", 4), ("diarrea", 4), ("malessere", 4), ("sto male", 4),
                                      ("mi sento male", 4), ("non mi sento bene", 4), ("stanc", 2), ("debol", 3), ("vertigin", 3), ("giramenti", 4), ("gira la testa", 4), ("capogir", 4), ("eruzion", 4),
                                      ("prurito", 4), ("puntura", 3), ("punto da", 3), ("morso", 3), ("dolor", 2), ("male", 1), ("cistite", 5), ("brucia", 3),
                                      ("allergi", 3), ("orticaria", 4), ("ferita", 3), ("taglio", 3), ("tagliat", 3), ("ustion", 4), ("scottat", 4), ("bruciat", 4),
                                      ("gonfiore", 2), ("infezion", 4), ("pressione alta", 4), ("pressione bassa", 4), ("palpitazion", 4), ("ansia", 3),
                                      ("attacco di panico", 4), ("insonnia", 3), ("colpo di calore", 4), ("disidratat", 4), ("svenimento", 2), ("emorroid", 4),
                                      ("stitichezz", 4), ("reflusso", 4), ("gastrite", 4), ("herpes", 4), ("zecca", 4), ("medusa", 4), ("ape", 2), ("vespa", 3),
                                      ("ho preso", 1), ("sintomi", 3), ("covid", 3), ("mal di", 2), ("dolore", 2), ("fa male", 2)],
}
PRIORITY = ["FARMACIA", "ASSISTENZA_TERRITORIALE", "TRAUMA_MINORE", "OCCHIO", "DENTI", "ORECCHIO_NASO_GOLA", "GRAVIDANZA", "PEDIATRICO", "PROBLEMA_GENERICO_NON_URGENTE"]
META = {
    "FARMACIA": ("pharmacy", "unknown", "unknown", "pharmacy"),
    "ASSISTENZA_TERRITORIALE": ("community_care", "unknown", "unknown", "community_house"),
    "TRAUMA_MINORE": ("seek_care", "musculoskeletal", "unknown", None),
    "OCCHIO": ("seek_care", "eye", "eye", None),
    "DENTI": ("seek_care", "dental", "mouth_teeth", None),
    "ORECCHIO_NASO_GOLA": ("seek_care", "ent", "ear_nose_throat", None),
    "GRAVIDANZA": ("seek_care", "pregnancy_gynecology", "abdomen", None),
    "PEDIATRICO": ("seek_care", "unknown", "unknown", None),
    "PROBLEMA_GENERICO_NON_URGENTE": ("seek_care", "general_malaise", "whole_body", None),
}
BODY = [("ankle_foot", r"cavigli|pied|tallon|alluc|malleol|calcagn|metatars|achille"), ("leg_knee", r"ginocchi|gamb|tibia|femore|anca|cosci|polpacc|rotul|menisc"),
        ("arm_hand", r"pols|bracci|avambracci|mano|mani|dito|dita|gomit|spall|clavicola|bicipit|tricipit"), ("back", r"schiena|lombar|cervical|collo"),
        ("head", r"testa|fronte|cranio"), ("chest", r"petto|torace|costol"), ("abdomen", r"pancia|stomaco|addome|ventre"), ("skin", r"pelle|cute|eruzion|orticaria")]
PS_WANT = re.compile(r"pronto soccorso|ospedale|meno affollat|piu vicin|dove sta il|dove si trova|dove e il|qual e il|quale|il migliore|dea\b|andare al")
CHILD = re.compile(r"\b(?:bambin\w*|bimb\w*|figli[oa]|neonat\w*|lattante|pediatr\w*|nipotin\w*|ragazzin\w*|nipote piccolo|la piccola|il piccolo)\b")
AGE = re.compile(r"\b(\d{1,3}) (ann[oi]|mes[ei])\b")
ADULT = re.compile(r"\b(?:mamma|papa|madre|padre|marito|moglie|nonna|nonno|anzian\w*)\b")
MEDICATION_TAKEN = re.compile(r"\b(?:pres[oa]|prend[oe]|assunt[oa]|assum[oe]|somministrat\w*|dat[oa]|nonostante)\b|\bnon (?:mi |gli |le )?(?:passa|scende|funziona)")
PHARMACY_BUY = re.compile(r"\bfarmaci[ae]\b|\b(?:compr\w*|acquist\w*|ho finito|finite le medicine)\b")
SCHEDULED = re.compile(r"\b(?:prenot\w* [^.]{0,35}(?:visita|esame|ecografi\w*|risonanz\w*)|visita specialistica|visita cardiologic\w*|ecografi\w*|risonanza\w*)\b")
ADVICE = re.compile(r"non so|non saprei|consigli|cosa (devo|dovrei|posso) fare|aiut|chi (devo )?chiam|dove (devo |posso |dovrei )?anda|dove vado|che faccio|cosa faccio|cosa mi consigli")
GREETING = re.compile(r"^(ciao|salve|buongiorno|buonasera|hey|ehi|grazie|ok|okay|va bene|si|no)\b[\s!.]*$")
EMERGENCY_HINT = re.compile(r"dolore al petto|non riesc\w* a respir|manca l aria|svenut|perso i sensi|non risponde|convuls|sangue (che )?non si ferma|emorragi|"
                            r"bocca storta|non riesc\w* a parlare|infarto|ictus|soffoc|candeggina|avvelen|farla finita|suicid|incoscien|overdose|arma da fuoco|accoltellat")


def _term_rx(term: str) -> re.Pattern:
    if " " in term:
        return re.compile(r"\b" + re.escape(term) + r"\w*")
    return re.compile(r"\b" + re.escape(term) + (r"\w*" if len(term) >= 4 else r"\b"))


_COMPILED = {cat: [(_term_rx(t), w, t) for t, w in terms] for cat, terms in LEX.items()}


def age_group(t: str) -> str:
    """L'età esplicita prevale su 'figlio'; la durata dei sintomi non è un'età."""
    for m in AGE.finditer(t):
        before = t[:m.start()]
        if re.search(r"\b(?:da|per|durante|negli ultimi|da circa)\s*$", before):
            continue
        years = int(m.group(1)) / (12 if m.group(2).startswith("mes") else 1)
        return "child" if years < 14 else "adult"
    if CHILD.search(t):
        return "child"
    if ADULT.search(t):
        return "adult"
    return "unknown"


def scores(t: str) -> dict[str, tuple[int, list[str]]]:
    out = {}
    for cat, terms in _COMPILED.items():
        s, hits = 0, []
        for rx, w, term in terms:
            if rx.search(t):
                s += w
                hits.append(term)
        out[cat] = (s, hits)
    return out


def classify(text: str) -> tuple[str, float, list[str]]:
    """-> (categoria, confidence 0-1, termini trovati)."""
    t = norm(text)
    if not t or GREETING.match(t):
        return "UNKNOWN", 0.2, []
    if EMERGENCY_HINT.search(t):
        return "EMERGENZA", 0.8, ["segnale di emergenza (il verifier decide)"]
    sc = scores(t)
    # Il bisogno resta il sintomo quando il farmaco è già stato assunto.
    if MEDICATION_TAKEN.search(t) and not PHARMACY_BUY.search(t):
        sc["FARMACIA"] = (0, [])
    if SCHEDULED.search(t):
        return "ASSISTENZA_TERRITORIALE", 0.8, ["visita o esame programmato"]
    child = age_group(t) == "child"
    if age_group(t) == "adult":
        sc["PEDIATRICO"] = (0, [])
    best = max(PRIORITY, key=lambda c: (sc[c][0], -PRIORITY.index(c)))
    s, hits = sc[best]
    if s == 0:
        return "UNKNOWN", 0.25, []
    if best == "PEDIATRICO":
        others = [c for c in PRIORITY if c != "PEDIATRICO" and sc[c][0] >= 3 and c != "PROBLEMA_GENERICO_NON_URGENTE"]
        if others:
            best = max(others, key=lambda c: sc[c][0])
            s, hits = sc[best]
    elif child and best == "PROBLEMA_GENERICO_NON_URGENTE":
        best = "PEDIATRICO"
    second = sorted((v[0] for k, v in sc.items() if k != best), reverse=True)[0]
    conf = min(0.9, 0.45 + 0.05 * s) - (0.15 if second and second >= s else 0.0)
    return best, round(max(conf, 0.3), 2), hits


def parse_rules(text: str) -> ParsedIntent:
    t = norm(text)
    cat, conf, _ = classify(text)
    age = age_group(t)
    child = age == "child"
    wants_ps = bool(PS_WANT.search(t)) and "pronto soccorso" in t or "ospedale" in t or bool(re.search(r"meno affollat|pronto soccorso", t))
    if cat == "EMERGENZA":
        return ParsedIntent(intent="emergency", category="EMERGENZA", problem_domain="unknown", body_area="unknown", requested_service=None,
                            age_group=age, needs_location=False, emergency_detected_by_llm=True, confidence=conf)
    if cat == "UNKNOWN":
        if wants_ps:
            return ParsedIntent(intent="emergency_room", category="PROBLEMA_GENERICO_NON_URGENTE", problem_domain="unknown", body_area="unknown",
                                requested_service="emergency_room", age_group=age, needs_location=True,
                                emergency_detected_by_llm=False, confidence=0.5)
        return ParsedIntent(intent="unknown", category="UNKNOWN", problem_domain="unknown", body_area="unknown",
                            requested_service="advice" if ADVICE.search(t) else None, age_group=age,
                            needs_location=False, emergency_detected_by_llm=False, confidence=conf)
    intent, dom, area, svc = META[cat]
    for a, rx in BODY:
        if re.search(r"\b(?:" + rx + r")\w*\b", t):
            area = a
            break
    if wants_ps and cat not in ("FARMACIA", "ASSISTENZA_TERRITORIALE"):
        intent, svc = "emergency_room", "emergency_room"
    if cat == "ASSISTENZA_TERRITORIALE" and SCHEDULED.search(t):
        intent, svc = "scheduled_care", "scheduled_visit"
    return ParsedIntent(intent=intent, category=cat, problem_domain=dom, body_area=area, requested_service=svc,
                        age_group="child" if (child or cat == "PEDIATRICO") else age, needs_location=True,
                        emergency_detected_by_llm=False, confidence=conf)
