"""CdC: orari pubblicati per sede/servizio, senza dedurre disponibilità clinica."""
from __future__ import annotations

from datetime import datetime


def opening_status(facility: dict, now: datetime) -> dict:
    from .cdc_rome import details as rome_details
    rome = rome_details(facility.get("facility_id"))
    if rome:
        return rome
    from .cdc_hours import details
    published = details(facility.get("facility_id"))
    if published:
        return published
    from .cdc_regional import details as regional_details
    regional = regional_details(facility)
    if regional:
        return regional
    # An old static weekend flag must not become a verified current closure.
    return {"status": "unknown_hours", "known": False, "label": "Orari della sede non verificati: consulta la scheda regionale o chiama prima.",
            "source_url": "https://salutelazio.it/it/servizi/case-della-comunita"}
