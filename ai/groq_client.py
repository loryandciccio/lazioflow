"""Client Groq (API OpenAI-compatible) via httpx: nessuna dipendenza nuova nel progetto.

Groq serve modelli open (gpt-oss, llama, qwen), NON Claude: è un provider alternativo dietro lo stesso
contratto. Per il parser chiediamo structured output in modalità `strict`, dove il decoding vincolato
garantisce la conformità allo schema; i modelli che la supportano sono in STRICT_SCHEMA_MODELS. Con gli
altri lo schema non è garantito: se il JSON non valida, ai/parser.py ripiega sulle regole come fa con Claude.

La chiave sta in GROQ_API_KEY (.env, mai committato).
"""
from __future__ import annotations

import json
import os

import httpx

BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
STRICT_SCHEMA_MODELS = {"openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"}
SCHEMA_MODELS = STRICT_SCHEMA_MODELS | {"openai/gpt-oss-safeguard-20b"}
# lo structured output strict rifiuta i vincoli numerici: li togliamo dallo schema inviato,
# Pydantic li riapplica quando valida la risposta (è lì che contano).
_DROP_KEYS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "title", "default")


class GroqError(RuntimeError):
    def __init__(self, status_code: int):
        self.status_code = status_code
        # Il corpo remoto può contenere testo sanitario e identificativi dell'account.
        super().__init__(f"Groq HTTP {status_code}")


def groq_enabled() -> bool:
    return bool(os.getenv("GROQ_API_KEY", "").strip())


def strict_supported(model: str | None = None) -> bool:
    return (model or GROQ_MODEL) in STRICT_SCHEMA_MODELS


def _clean(node):
    if isinstance(node, dict):
        return {k: _clean(v) for k, v in node.items() if k not in _DROP_KEYS}
    if isinstance(node, list):
        return [_clean(v) for v in node]
    return node


async def chat(system: str, user: str, *, max_tokens: int, timeout_s: float,
               schema: dict | None = None, schema_name: str = "output") -> tuple[str, dict]:
    """-> (testo della risposta, usage). Solleva in caso di errore: il fallback lo decide il chiamante."""
    model = GROQ_MODEL
    body: dict = {"model": model, "max_completion_tokens": max_tokens, "temperature": 0,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = os.getenv("GROQ_REASONING_EFFORT", "low")
    if schema:
        if model in SCHEMA_MODELS:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema_name, "strict": strict_supported(model), "schema": _clean(schema)}}
        else:
            # https://console.groq.com/docs/structured-outputs#supported-models
            body["response_format"] = {"type": "json_object"}
            body["messages"][0]["content"] += "\nRestituisci JSON conforme a questo schema: " + json.dumps(_clean(schema))
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(f"{BASE_URL.rstrip('/')}/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"})
    if r.status_code >= 400:
        raise GroqError(r.status_code)
    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("Groq: risposta senza choices")
    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if choice.get("finish_reason") not in (None, "stop") or message.get("refusal"):
        raise ValueError("Groq: risposta incompleta o rifiutata")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Groq: risposta testuale vuota")
    return content, data.get("usage") or {}
