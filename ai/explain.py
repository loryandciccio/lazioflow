"""Explanation generator (spec §15): riceve SOLO richiesta utente + ranking già calcolato + dati verificati.
Con LLM: testo in linguaggio semplice dai soli dati forniti. Senza LLM: template deterministico dalle `reasons`."""
from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache
from pathlib import Path

from .parser import CLAUDE_MODEL, LLM_TIMEOUT_S, provider

log = logging.getLogger("lazioflow.ai")
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "explanation.md"


@lru_cache(maxsize=1)
def system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _facts(rec: dict) -> dict:
    """Solo i dati verificati che l'LLM può usare: niente campi liberi, niente capability non verificate."""
    sc, lv, tr = rec.get("score") or {}, rec.get("live") or {}, rec.get("trend") or {}
    return {"rank": rec["rank"], "name": rec["name"], "type": rec["type"], "distance_km": rec["distance_km"],
            "travel_minutes": sc.get("travel_minutes"), "observed_wait_minutes": sc.get("wait_minutes"),
            "ordering_rule": sc.get("formula"), "wait_used_for_ranking": sc.get("wait_used_for_ranking"), "mode": sc.get("mode_label"),
            "total_waiting": lv.get("total_waiting"), "live_freshness": lv.get("freshness"), "data_timestamp": lv.get("data_timestamp"),
            "trend_direction": tr.get("direction"), "trend_delta_60m": tr.get("delta_60m"),
            "compatibility_confidence": rec.get("compatibility_confidence"), "reasons": rec.get("reasons"), "warnings": rec.get("warnings")}


def explain_rules(user_text: str, recs: list[dict]) -> str:
    out = []
    for r in recs:
        why = "; ".join(r.get("reasons") or [])
        warn = " Attenzione: " + "; ".join(r["warnings"]) + "." if r.get("warnings") else ""
        out.append(f"#{r['rank']} {r['name']}: {why}.{warn}")
    return "\n".join(out) or "Nessuna struttura da spiegare."


async def explain(user_text: str, recs: list[dict]) -> dict:
    if not recs:
        return {"text": "Nessuna struttura da spiegare.", "generator": "rules"}
    engine = provider()
    if engine != "none":
        try:
            payload = json.dumps({"strutture": [_facts(r) for r in recs]}, ensure_ascii=False)
            async with asyncio.timeout(LLM_TIMEOUT_S):
                if engine == "groq":
                    from .groq_client import chat
                    text, _ = await chat(system_prompt(), payload, max_tokens=1500, timeout_s=LLM_TIMEOUT_S)
                    text = text.strip()
                else:
                    import anthropic
                    async with anthropic.AsyncAnthropic(timeout=LLM_TIMEOUT_S, max_retries=0) as client:
                        resp = await client.messages.create(
                            model=CLAUDE_MODEL, max_tokens=1500, system=system_prompt(), output_config={"effort": "low"},
                            messages=[{"role": "user", "content": payload}])
                    text = "" if resp.stop_reason in ("refusal", "max_tokens") else "".join(
                        b.text for b in resp.content if b.type == "text").strip()
            if text:
                return {"text": text, "generator": "llm"}
        except Exception as e:
            log.warning("explanation LLM (%s) fallita (%s): uso il template", engine, type(e).__name__)
    return {"text": explain_rules(user_text, recs), "generator": "rules"}
