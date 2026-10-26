"""Contratto API (spec §12). Campi chiusi: niente diagnosi, niente severità, niente triage."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Preference = Literal["balanced", "nearest", "less_crowded"]
AgeGroup = Literal["child", "adult", "unknown"]
FacilityType = Literal["emergency_room", "community_house", "community_hospital", "pharmacy"]


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class RecommendRequest(BaseModel):
    """`category` è l'id di una categoria chiusa (data/normalized/categories.json). I campi intent/problem_domain/
    body_area sono quelli del parser e servono solo per il log: il routing usa esclusivamente la categoria."""
    model_config = ConfigDict(extra="forbid")
    category: str
    location: Location
    preference: Preference = "balanced"
    age_group: AgeGroup = "unknown"
    facility_type: FacilityType | None = None   # per categorie con più tipi ammessi (es. CdC o PS): scelta dell'utente
    limit: int = Field(default=3, ge=1, le=10)
    intent: str | None = None
    problem_domain: str | None = None
    body_area: str | None = None


class LiveOut(BaseModel):
    available: bool
    freshness: Literal["live", "recent", "stale", "unavailable"]
    total_waiting: int | None
    observed_wait_minutes: int | None
    observed_wait_code: str | None
    groups: dict | None
    data_timestamp: str | None
    retrieved_at: str | None
    note: str | None


class TrendOut(BaseModel):
    current: int | None
    delta_15m: int | None
    delta_30m: int | None
    delta_60m: int | None
    direction: Literal["increasing", "stable", "decreasing", "insufficient_data"]
    samples: int
    observed_at: str | None
    text: str | None


class Score(BaseModel):
    mode: Preference
    mode_label: str
    travel_minutes: int
    wait_minutes: int | None
    estimated_minutes: int | None
    wait_used_for_ranking: bool = False
    formula: str


class Source(BaseModel):
    source_name: str
    source_url: str | None
    retrieved_at: str | None
    data_timestamp: str | None
    freshness: Literal["live", "recent", "stale", "unavailable", "static"]
    what: str


class Recommendation(BaseModel):
    rank: int
    facility_id: str
    name: str
    type: FacilityType
    ps_scope: str | None
    address: str | None
    phone: str | None
    asl: str | None
    lat: float
    lng: float
    distance_km: float
    maps_url: str
    compatible: bool
    compatibility_level: int
    compatibility_confidence: Literal["verified", "unverified", "not_applicable"]
    compatibility_sources: dict[str, str]
    classification: dict
    opening: dict | None
    live: LiveOut | None
    trend: TrendOut | None
    score: Score
    reasons: list[str]
    warnings: list[str]
    sources: list[Source]


class RecommendResponse(BaseModel):
    synthetic: bool = False
    generated_at: str
    category: str
    category_label: str
    preference: Preference
    facility_type: FacilityType | None
    escalation: Literal["112", "116117"] | None = None
    escalation_text: str | None = None
    candidates_considered: int
    recommendations: list[Recommendation]
    disclaimer: str
    limits: list[str]
