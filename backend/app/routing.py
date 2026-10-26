"""Compatibilità struttura ↔ categoria (STEP 2 del ranking gerarchico).

Regole (docs/FATTIBILITA.md §3 e §7):
- filtro DURO: tipo di struttura ammesso dalla categoria; per i PS lo scope (mai un PS oculistico per una storta,
  mai un PS solo-adulti per un bambino);
- filtro MORBIDO: `requires` (es. reparto di ortopedia-traumatologia). Livello 1 = soddisfatto e verificato da fonte;
  livello 2 = non risulta dalle fonti (mostrato DOPO, con etichetta), perché l'assenza in un dataset annuale
  non è la prova che il servizio manchi.
- `prefer` non filtra: aggiunge solo una motivazione.
La categoria è un instradamento, non una diagnosi: qui non si valuta mai la gravità.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PS_TYPES = ("emergency_room",)
CAP_IT = {"orthopedics_trauma": "ortopedia-traumatologia", "pediatrics": "pediatria", "ophthalmology": "oculistica",
          "ent": "otorinolaringoiatria", "obstetrics_gynecology": "ostetricia-ginecologia", "trauma_network": "rete trauma",
          "pediatric_emergency_room": "PS pediatrico", "community_house_dm77": "Casa della Comunità (DM 77)", "pharmacy": "farmacia"}


def cap_it(c: str) -> str:
    return CAP_IT.get(c, c)


@dataclass
class Compatibility:
    level: int                    # 0 = escluso (filtro duro), 1 = requisiti verificati, 2 = requisiti non verificati
    confidence: str               # "verified" | "unverified" | "not_applicable" | "excluded"
    reasons: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    prefer_rank: int = 0          # 0 = servizio preferito presente (o non richiesto in modo stretto), 1 = manca

    @property
    def compatible(self) -> bool:
        return self.level > 0


def effective_rules(category: dict, age_group: str | None) -> dict:
    """Applica la regola d'età: bambino -> serve pediatria, preferisce PS pediatrico, ammette lo scope pediatrico."""
    allowed_types = list(category.get("allowed_types") or [])
    ps_scope = list(category.get("ps_scope") or [])
    exclude_scope = list(category.get("exclude_scope") or [])
    requires = list(category.get("requires") or [])
    prefer = list(category.get("prefer") or [])
    if age_group == "child" and "emergency_room" in allowed_types:
        if "pediatrics" not in requires:
            requires.append("pediatrics")
        if "pediatric_emergency_room" not in prefer:
            prefer.append("pediatric_emergency_room")
        if ps_scope and "pediatric" not in ps_scope:
            ps_scope.append("pediatric")
        exclude_scope = [s for s in exclude_scope if s != "pediatric"]
    return {"allowed_types": allowed_types, "ps_scope": ps_scope, "exclude_scope": exclude_scope,
            "requires": requires, "prefer": prefer}


def compatibility(facility: dict, category: dict, age_group: str | None = None) -> Compatibility:
    rules = effective_rules(category, age_group)
    ftype = facility["type"]
    if ftype not in rules["allowed_types"]:
        return Compatibility(0, "excluded", [f"tipo di struttura non previsto per questa richiesta ({ftype})"])
    caps = set(facility.get("capabilities") or [])
    cap_src = facility.get("capability_sources") or {}
    reasons: list[str] = []
    if ftype in PS_TYPES:
        scope = facility.get("ps_scope") or "general"
        if scope in rules["exclude_scope"]:
            return Compatibility(0, "excluded", [f"PS specialistico ({scope}) non pertinente"])
        if rules["ps_scope"] and scope not in rules["ps_scope"]:
            return Compatibility(0, "excluded", [f"PS specialistico ({scope}) non pertinente"])
        if scope != "general":
            reasons.append(f"PS specialistico: {scope}")
    if not rules["requires"]:
        return Compatibility(1, "not_applicable", reasons + ["nessun reparto specifico richiesto"])
    missing = [r for r in rules["requires"] if r not in caps]
    sources = {r: cap_src.get(r, "") for r in rules["requires"] if r in caps}
    if missing:
        return Compatibility(2, "unverified",
                             reasons + [f"reparto non risultante dalle fonti: {', '.join(cap_it(m) for m in missing)}"], missing, sources)
    reasons.append(("requisito nel catalogo sintetico: " if facility.get("synthetic") else "reparto verificato da fonte ufficiale: ")
                   + ", ".join(cap_it(r) for r in rules["requires"]))
    prefer_rank = 0
    for p in rules["prefer"]:
        if p in caps:
            reasons.append(f"servizio dedicato presente: {cap_it(p)}")
            sources[p] = cap_src.get(p, "")
        elif category.get("prefer_strict"):
            prefer_rank = 1
    return Compatibility(1, "not_applicable" if facility.get("synthetic") else "verified", reasons, [], sources, prefer_rank)
