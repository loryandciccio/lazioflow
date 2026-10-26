"""Schema RIGIDO dell'output del parser (spec §4). Tutto a classi chiuse; campi extra rifiutati (extra=forbid).
Niente diagnosi, niente severità, niente codice triage, niente struttura: il modello non può produrli perché
non esistono nello schema. La gravità la decide SOLO il safety layer deterministico (safety/verifier.py)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal["seek_care", "pharmacy", "emergency_room", "community_care", "scheduled_care", "emergency", "unknown"]
Category = Literal["EMERGENZA", "TRAUMA_MINORE", "PEDIATRICO", "OCCHIO", "ORECCHIO_NASO_GOLA", "GRAVIDANZA", "DENTI",
                   "PROBLEMA_GENERICO_NON_URGENTE", "FARMACIA", "ASSISTENZA_TERRITORIALE", "UNKNOWN"]
ProblemDomain = Literal["musculoskeletal", "eye", "ent", "pregnancy_gynecology", "dental", "general_malaise", "skin",
                        "cardio_respiratory", "neurological", "mental_health", "other", "unknown"]
BodyArea = Literal["head", "eye", "ear_nose_throat", "mouth_teeth", "chest", "abdomen", "back", "arm_hand", "leg_knee",
                   "ankle_foot", "skin", "whole_body", "unknown"]
RequestedService = Literal["pharmacy", "emergency_room", "community_house", "scheduled_visit", "advice"]
AgeGroup = Literal["child", "adult", "unknown"]

FORBIDDEN_KEYS = {"diagnosis", "diagnosi", "severity", "gravita", "gravità", "triage", "triage_code", "codice_triage",
                  "facility", "struttura", "prescription", "prognosis"}


class ParsedIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent
    category: Category = Field(description="Una delle categorie chiuse di instradamento (categories.json) o UNKNOWN")
    problem_domain: ProblemDomain
    body_area: BodyArea
    requested_service: RequestedService | None
    age_group: AgeGroup
    needs_location: bool
    emergency_detected_by_llm: bool = Field(description="True se il testo descrive una possibile emergenza. Solo un segnale: la decisione è del safety layer")
    confidence: float = Field(ge=0.0, le=1.0)


class ParseResult(BaseModel):
    """Output di /parse: il JSON validato + come è stato ottenuto."""
    parsed: ParsedIntent
    parser: Literal["llm", "rules"]
    model: str | None
    note: str | None = None
