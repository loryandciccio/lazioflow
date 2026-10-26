"""Safety layer deterministico (spec §3). Analizza il TESTO ORIGINALE dell'utente con le regole di safety/rules.json.

Stati:  HARD_RED_FLAG  -> 112, nessun ranking
        UNCERTAIN      -> 116117 + scelta esplicita dell'utente; mai 'non grave'
        NO_FLAG_DETECTED -> nessuna condizione codificata rilevata (NON significa 'lieve')
Il verifier può solo aumentare la cautela: l'esito dell'LLM (emergency_detected_by_llm) può alzare lo stato a
UNCERTAIN, mai abbassarlo. In caso di conflitto vince il safety layer.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent / "rules.json"

ALLOWED_ACTIONS = {
    "HARD_RED_FLAG": ["SHOW_112"],
    "UNCERTAIN": ["SHOW_116117", "SHOW_112", "ASK_SERVICE_TYPE", "USER_EXPLICIT_CHOICE"],
    "NO_FLAG_DETECTED": ["ASK_SERVICE_TYPE", "SHOW_116117", "ROUTE"],
}
MESSAGES = {
    "HARD_RED_FLAG": "⚠️ Quello che descrivi può essere un'emergenza: chiama il 112.",
    "UNCERTAIN": "Non riesco a classificarlo in sicurezza e non voglio sbagliare.",
    "NO_FLAG_DETECTED": None,
}


@dataclass
class Match:
    rule_id: str
    label: str
    action: str
    matched_text: str
    source: dict


@dataclass
class SafetyResult:
    status: str
    matched_rules: list[Match] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    message: str | None = None
    llm_flag_considered: bool = False
    note: str = "NO_FLAG_DETECTED significa solo che nessuna condizione codificata è stata rilevata, non che il caso sia lieve."

    def to_dict(self) -> dict:
        return asdict(self)


def normalize(text: str) -> str:
    text = (text or "").translate(str.maketrans({c: " " for c in "'’‘ʼ＇-‑–—"}))
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\bnn\b", "non", t)          # abbreviazione colloquiale
    t = re.sub(r"\bxke\b|\bxche\b", "perche", t)
    return re.sub(r"\s+", " ", t).strip()


@lru_cache(maxsize=1)
def load_rules() -> list[dict]:
    with open(RULES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    rules = []
    for r in data["rules"]:
        rules.append({**r, "_compiled": [re.compile(p) for p in r["patterns"]]})
    return rules


def check(text: str, emergency_detected_by_llm: bool | None = None) -> SafetyResult:
    norm = normalize(text)
    matches: list[Match] = []
    if norm:
        for r in load_rules():
            for rx in r["_compiled"]:
                m = rx.search(norm)
                if m:
                    matches.append(Match(r["rule_id"], r["label"], r["action"], m.group(0), r["source"]))
                    break
    if any(m.action == "EMERGENCY" for m in matches):
        status = "HARD_RED_FLAG"
    elif matches:
        status = "UNCERTAIN"
    elif emergency_detected_by_llm:
        status = "UNCERTAIN"
    else:
        status = "NO_FLAG_DETECTED"
    res = SafetyResult(status, matches, list(ALLOWED_ACTIONS[status]), MESSAGES[status], bool(emergency_detected_by_llm))
    if status == "UNCERTAIN" and not matches and emergency_detected_by_llm:
        res.matched_rules = [Match("llm_emergency_flag", "il parser ha segnalato una possibile emergenza", "UNCERTAIN", "", {"name": "LLM parser (segnale, non regola)", "url": None, "verified_at": None})]
    return res


def merge_with_llm(safety: SafetyResult, emergency_detected_by_llm: bool) -> SafetyResult:
    """Conflitto LLM vs safety: il safety layer non scende mai; l'LLM può solo alzare a UNCERTAIN."""
    if safety.status == "NO_FLAG_DETECTED" and emergency_detected_by_llm:
        return check("", True) if not safety.matched_rules else safety
    return safety


if __name__ == "__main__":
    import sys
    print(json.dumps(check(" ".join(sys.argv[1:])).to_dict(), ensure_ascii=False, indent=1))
