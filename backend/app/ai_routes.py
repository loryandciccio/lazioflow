"""Endpoint del workstream AI+Safety (spec §12): POST /parse, POST /safety/check, POST /explain, POST /understand.
/understand = parse + safety in una chiamata sola (quello che usa il bot), con la regola: vince il safety layer."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ai.explain import explain
from ai.parser import normalize, parse, parse_rules
from ai.schemas import ParseResult
from .models import FacilityType
from safety.verifier import check

log = logging.getLogger("lazioflow.ai")
router = APIRouter()


class TextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=4096)


class ExplainRecommendation(BaseModel):
    """Accetta la scheda del ranking e valida i campi usati dalla spiegazione."""
    model_config = ConfigDict(extra="ignore")
    rank: int = Field(ge=1, le=10)
    name: str = Field(min_length=1, max_length=500)
    type: FacilityType
    distance_km: float = Field(ge=0, allow_inf_nan=False)
    reasons: list[str] = Field(default_factory=list, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=30)
    score: dict | None = None
    live: dict | None = None
    trend: dict | None = None
    compatibility_confidence: str | None = None


class ExplainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(default="", max_length=4096)
    recommendations: list[ExplainRecommendation] = Field(max_length=10)


@router.post("/parse", response_model=ParseResult)
async def post_parse(body: TextIn):
    r = await parse(body.text)
    log.info("parse engine=%s category=%s intent=%s conf=%.2f len=%d", r.parser, r.parsed.category, r.parsed.intent,
             r.parsed.confidence, len(body.text))
    return r


@router.post("/safety/check")
def post_safety(body: TextIn):
    return check(body.text).to_dict()


@router.post("/understand")
async def post_understand(body: TextIn):
    """parse + safety sul testo originale. Il safety layer decide: HARD -> nessun routing; UNCERTAIN -> solo scelta
    esplicita; NO_FLAG -> routing sulla categoria (o domanda se UNKNOWN / più tipi ammessi)."""
    safety = check(body.text)
    if safety.status == "HARD_RED_FLAG":
        # Le emergenze riconosciute dalle regole non aspettano la rete o il modello.
        parsed = ParseResult(parsed=normalize(parse_rules(body.text)), parser="rules", model=None,
                             note="safety: avviso immediato senza chiamata LLM")
    else:
        parsed = await parse(body.text)
        safety = check(body.text, emergency_detected_by_llm=parsed.parsed.emergency_detected_by_llm)
    if safety.status == "HARD_RED_FLAG":
        next_step = "SHOW_112"
    elif safety.status == "UNCERTAIN":
        next_step = "SHOW_116117_AND_ASK"
    elif parsed.parsed.category == "UNKNOWN":
        next_step = "ASK_SERVICE_TYPE"
    else:
        next_step = "ROUTE"
    log.info("understand safety=%s next=%s category=%s conf=%.2f engine=%s len=%d", safety.status, next_step, parsed.parsed.category,
             parsed.parsed.confidence, parsed.parser, len(body.text))
    return {"parse": parsed.model_dump(), "safety": safety.to_dict(), "next_step": next_step}


@router.post("/explain")
async def post_explain(body: ExplainIn):
    return await explain(body.text, [r.model_dump() for r in body.recommendations])
