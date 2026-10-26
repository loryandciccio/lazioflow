"""Coverage is measured separately from source freshness and actual service availability."""
from datetime import datetime, timezone

from . import facilities as F
from .data_sources import cdc_hours, cdc_regional, cdc_rome, pharmacy_live, pharmacy_regional, pharmacy_contacts
from .data_sources.pharmacies import opening_status
from .data_sources.source_utils import PROVINCES, province


def coverage():
    now = datetime.now(timezone.utc)
    catalog = F.all_facilities()
    provincial = pharmacy_regional.status()
    rome_sources = pharmacy_live.status()
    indexed = pharmacy_regional.indexed()
    rows = []
    for code, name in PROVINCES.items():
        facilities = [f for f in catalog if province(f) == code]
        pharmacies = [f for f in facilities if f['type'] == 'pharmacy']
        houses = [f for f in facilities if f['type'] == 'community_house']
        ps = [f for f in facilities if f['type'] == 'emergency_room']
        openings = [opening_status(pharmacy_live.overlay(f), now) for f in pharmacies]
        source = provincial.get(code, {})
        if code == 'RM':
            feeds = rome_sources.get('sources', {})
            source = {'documents': list(feeds), 'retrieved_at': max((s['retrieved_at'] for s in feeds.values()), default=None),
                      'fresh': bool(feeds) and all(s['age_seconds'] <= (7200 if k == 'daily' else 172800) for k,s in feeds.items()),
                      'error': rome_sources.get('errors') or None}
        rows.append({'code':code, 'name':name,
                     'catalog':{'pharmacies':len(pharmacies), 'community_houses':len(houses), 'emergency_rooms':len(ps)},
                     'pharmacies':{'known_open':sum(o['known'] and o['status']=='open' for o in openings),
                                   'verified_contacts':sum('contact_source' in pharmacy_contacts.overlay(f) for f in pharmacies),
                                   'published_shift_now':sum(bool(o.get('on_duty')) for o in openings),
                                   'calendar_matched_sites':sum(f['facility_id'] in indexed for f in pharmacies),
                                   'source_url':pharmacy_regional.SOURCES[code]['url'],
                                   'documents':len(source.get('documents', [])), 'fresh':source.get('fresh'),
                                   'retrieved_at':source.get('retrieved_at'), 'error':source.get('error')},
                     'community_houses':{'regional_cards_matched':sum(cdc_regional.record(f) is not None for f in houses),
                                         'service_hours_matched':sum(cdc_rome.details(f['facility_id']) is not None or cdc_hours.details(f['facility_id']) is not None for f in houses)},
                     'emergency_rooms':{'live_supported':sum(bool(F.emergency_id(f)) and (f.get('live') or {}).get('supported',False) for f in ps)}})
    return {'synthetic':bool(F.meta().get('synthetic')), 'generated_at':now.isoformat(), 'provinces':rows,
            'unassigned_geography':sum(province(f) is None for f in catalog),
            'rome_sources':rome_sources, 'cdc_regional':cdc_regional.status(),
            'limits':['Catalogo presente non significa orari completi.',
                      'Un turno pubblicato può prevedere reperibilità: non significa porta aperta.',
                      'I PDF non riconosciuti restano consultabili; gli orari non vengono inventati.',
                      'I calendari sono verificati periodicamente; variazioni improvvise vanno confermate con la struttura.']}
