"""Parser di intent: testo libero -> ParsedIntent (JSON validato con schema rigido).

Due motori:
  - "llm": Claude via Anthropic SDK con output strutturato (messages.parse + Pydantic). Prompt: ai/prompts/intent.md.
  - "rules": parser deterministico a parole chiave (fallback se manca la chiave API, se l'LLM fallisce o se
    LAZIOFLOW_AI=0). Meno capace ma sempre disponibile: il bot non deve mai restare muto.
In entrambi i casi l'output passa per ParsedIntent (extra=forbid) e per `normalize()`, che rende coerenti intent e
categoria. La gravità NON si decide qui: safety/verifier.py gira sempre sul testo originale.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import httpx

from .groq_client import groq_enabled
from .schemas import FORBIDDEN_KEYS, ParsedIntent, ParseResult

log = logging.getLogger("lazioflow.ai")
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "intent.md"
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "20"))


def _anthropic_key() -> bool:
    try:
        import anthropic
        with anthropic.Anthropic() as c:
            return bool(c.api_key or getattr(c, "auth_token", None))
    except Exception:
        return False


def provider() -> str:
    """Motore LLM attivo: "anthropic" | "groq" | "none".

    LAZIOFLOW_AI=0 spegne tutto (sviluppo a costo zero: il bot resta funzionante sulle regole).
    LLM_PROVIDER=anthropic|groq forza un provider; con "auto" (default) vince Anthropic se la chiave
    c'è, altrimenti Groq. "none" = nessuna chiave utilizzabile.
    """
    if os.getenv("LAZIOFLOW_AI", "0") == "0":
        return "none"
    want = os.getenv("LLM_PROVIDER", "auto").strip().lower()
    if want == "anthropic":
        return "anthropic" if _anthropic_key() else "none"
    if want == "groq":
        return "groq" if groq_enabled() else "none"
    if _anthropic_key():
        return "anthropic"
    return "groq" if groq_enabled() else "none"


def ai_enabled() -> bool:
    return provider() != "none"


@lru_cache(maxsize=1)
def system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------- parser deterministico (fallback): ai/rules_parser.py
from .rules_parser import parse_rules  # noqa: E402


# ---------------------------------------------------------------- coerenza post-validazione
def normalize(p: ParsedIntent) -> ParsedIntent:
    d = p.model_dump()
    if d["intent"] == "emergency" or d["category"] == "EMERGENZA":
        d.update(intent="emergency", category="EMERGENZA", emergency_detected_by_llm=True, needs_location=False)
    elif d["intent"] == "pharmacy" and d["category"] in ("UNKNOWN", "PROBLEMA_GENERICO_NON_URGENTE"):
        d["category"] = "FARMACIA"
    elif d["intent"] == "community_care" and d["category"] == "UNKNOWN":
        d["category"] = "ASSISTENZA_TERRITORIALE"
    if d["category"] == "FARMACIA":
        d["intent"] = "pharmacy"
    if d["category"] == "PEDIATRICO":
        d["age_group"] = "child"
    if d["category"] not in ("EMERGENZA", "UNKNOWN"):
        d["needs_location"] = True
    return ParsedIntent(**d)


def reject_forbidden(raw: dict) -> None:
    if not isinstance(raw, dict):
        raise ValueError("il parser deve restituire un oggetto JSON")
    bad = FORBIDDEN_KEYS & {k.lower() for k in raw}
    if bad:
        raise ValueError(f"campi non ammessi nell'output del parser: {sorted(bad)}")


# ---------------------------------------------------------------- LLM
async def parse_llm(text: str) -> ParseResult:
    import anthropic

    async with anthropic.AsyncAnthropic(timeout=LLM_TIMEOUT_S, max_retries=0) as client:
        resp = await client.messages.parse(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=system_prompt(),
            messages=[{"role": "user", "content": text}],
            output_format=ParsedIntent,
            output_config={"effort": "low"},
        )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"parser LLM: stop_reason={resp.stop_reason}")
    reject_forbidden(resp.parsed_output.model_dump())
    return ParseResult(parsed=normalize(resp.parsed_output), parser="llm", model=CLAUDE_MODEL)


@lru_cache(maxsize=1)
def _groq_schema() -> dict:
    """Schema per Groq: `confidence` come intero 0-100.

    Il decoding vincolato di Groq sbaglia i float (osservato: `"confidence": 0. nine`, che fa fallire la
    richiesta con json_validate_failed). Sugli interi non accade. Il contratto ParsedIntent non cambia:
    parse_groq riporta il valore a 0-1 prima di validare.
    """
    s = ParsedIntent.model_json_schema()
    s["properties"]["confidence"] = {"type": "integer", "description": "confidenza da 0 a 100 (es. 90 = 0.9)"}
    return s


async def parse_groq(text: str) -> ParseResult:
    """Groq con structured output (json_schema strict sui modelli che lo supportano)."""
    from .groq_client import GROQ_MODEL, chat

    prompt = system_prompt() + "\nPer questo schema, confidence è un INTERO da 0 a 100 (esempio: 90), non un decimale."
    content, _ = await chat(prompt, text, max_tokens=1024, timeout_s=LLM_TIMEOUT_S,
                            schema=_groq_schema(), schema_name="parsed_intent")
    raw = json.loads(content)
    reject_forbidden(raw)
    confidence = raw.get("confidence")
    if type(confidence) is not int or not 0 <= confidence <= 100:
        raise ValueError("confidence Groq deve essere un intero tra 0 e 100")
    raw["confidence"] = confidence / 100
    return ParseResult(parsed=normalize(ParsedIntent(**raw)), parser="llm", model=GROQ_MODEL)


async def parse(text: str) -> ParseResult:
    """LLM se disponibile, altrimenti regole. Non solleva mai: in caso di errore LLM ripiega sulle regole."""
    text = (text or "").strip()
    if not text:
        return ParseResult(parsed=parse_rules(""), parser="rules", model=None, note="testo vuoto")
    engine = provider()
    if engine != "none":
        try:
            # Limite sull'intera operazione, non su ciascuna fase HTTP o tentativo.
            async with asyncio.timeout(LLM_TIMEOUT_S):
                return await (parse_groq(text) if engine == "groq" else parse_llm(text))
        except Exception as e:  # rete, refusal, validazione: mai bloccare il bot
            error = ("rate_limit" if getattr(e, "status_code", None) == 429 else
                     "timeout" if isinstance(e, (TimeoutError, httpx.TimeoutException)) else type(e).__name__)
            log.warning("parser LLM (%s) fallito (%s): uso le regole", engine, error)
            r = parse_rules(text)
            return ParseResult(parsed=normalize(r), parser="rules", model=None, note=f"fallback: {error}")
    return ParseResult(parsed=normalize(parse_rules(text)), parser="rules", model=None, note="LLM non configurato")
