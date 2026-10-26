"""Aggiornamento regionale delle schede pubbliche, senza dedurre orari mancanti."""
import html
import json
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from urllib.parse import urlparse

from ..config import DB_PATH, LIVE_DISABLED
from .source_utils import asl_key, clean, key

SOURCE = 'https://salutelazio.it/it/servizi/case-della-comunita'
CACHE = DB_PATH.with_name('cdc_regional.json')
_snapshot = {}
_error = None


def documents(page):
    """Read the public serialized document metadata, without executing site scripts."""
    result = {}
    def walk(value):
        if isinstance(value, dict):
            file = value.get('file')
            if isinstance(file, dict) and value.get('name'):
                url = file.get('full', '')
                if urlparse(url).hostname == 'minio-vra-prod.servicelazio.it' and url.startswith('https://') and url.endswith('.pdf'):
                    result[clean(value['name'])] = {'document_url': url, 'source_updated_at': value.get('updatedAt')}
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for raw in re.findall(r'self\.__next_f\.push\((.*?)\)</script>', page, re.S):
        try:
            chunk = json.loads(raw)
            if isinstance(chunk, list) and len(chunk) > 1 and isinstance(chunk[1], str):
                for line in chunk[1].splitlines():
                    if ':' in line:
                        try:
                            walk(json.loads(line.split(':', 1)[1]))
                        except ValueError:
                            pass
        except (ValueError, TypeError, RecursionError):
            continue
    return result


def parse(page):
    records = {}
    docs = documents(page)
    for card in re.findall(r'<div class="card-file shadow.*?</button>\s*</div>\s*</div>', page, re.S):
        title = re.search(r'<h3 class="card-file-title[^>]*>(.*?)</h3>', card, re.S)
        if not title:
            continue
        name = html.unescape(re.sub('<[^>]*>', '', title[1])).strip()
        text = ' '.join(html.unescape(re.sub('<[^>]*>', ' ', card)).split())
        asl = re.search(r'ASL\s+(Roma\s*[1-6]|Viterbo|Frosinone|Latina|Rieti)\b', text, re.I)
        if not asl and 'file-type' not in card:
            continue
        phone = re.search(r'Tel[.:]?\s*(?:PUA[.:]?\s*)?:?\s*([\d ][\d /]+)', text, re.I)
        weekend = re.search(r'festivi:\s*(SI|NO)', text, re.I)
        date = re.search(r'\b\d{2}/\d{2}/\d{4}\b', text)
        if not asl or name in records:
            raise ValueError('scheda incompleta o nome ambiguo')
        records[name] = {'asl': asl_key(asl[1]), 'phone': phone[1].strip() if phone else None,
                         'weekend': weekend[1].upper() == 'SI' if weekend else None,
                         'published_date': date[0] if date else None, **docs.get(name, {})}
    if not records:
        raise ValueError('nessuna scheda regionale riconosciuta')
    return records


def load_cache():
    global _snapshot
    try:
        data = json.loads(CACHE.read_text())
        if isinstance(data.get('records'), dict):
            _snapshot = data
    except (OSError, ValueError, AttributeError):
        pass


def fresh():
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(_snapshot['retrieved_at'])).total_seconds()
        return 0 <= age < 86400
    except (KeyError, ValueError, TypeError):
        return False


async def refresh():
    global _snapshot, _error
    if LIVE_DISABLED or fresh() and _snapshot.get('schema_version') == 2:
        return
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(SOURCE)
            response.raise_for_status()
        records = parse(response.text)
        # Una pagina parziale non deve sostituire l'ultima acquisizione completa.
        if len(records) < len(_snapshot.get('records', {})) * .8:
            raise ValueError('riduzione anomala delle schede')
        updated = {'schema_version': 2, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'records': records}
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=CACHE.parent, delete=False) as f:
            json.dump(updated, f)
            path = f.name
        Path(path).replace(CACHE)
        _snapshot, _error = updated, None
    except Exception as exc:
        _error = type(exc).__name__


def record(facility):
    if not fresh():
        return None
    records = _snapshot.get('records', {})
    name = clean((facility.get('ids') or {}).get('salutelazio_card'))
    if name in records:
        return records[name]
    name = key(facility.get('name')).removeprefix('CASA DELLA COMUNITA ')
    matches = [r for n, r in records.items() if key(n) == name and r.get('asl') == asl_key(facility.get('asl'))]
    return matches[0] if len(matches) == 1 else None


def overlay(facility):
    item = record(facility)
    if not item:
        return facility
    return {**facility, 'phone': item['phone'] or facility.get('phone'),
            'opening': {**(facility.get('opening') or {}), 'weekend_holidays_open': item['weekend']}}


def details(facility):
    item = record(facility)
    if not item:
        return None
    weekend = {True: 'La scheda indica apertura anche sabato, domenica e festivi.',
               False: 'La scheda indica chiusura sabato, domenica e festivi.',
               None: 'Apertura nei festivi non specificata.'}[item['weekend']]
    return {'known': False, 'status': 'unknown_hours',
            'label': weekend + ' Fasce orarie e disponibilità dei servizi da verificare con la sede.',
            'source_url': item.get('document_url') or SOURCE, 'retrieved_at': _snapshot['retrieved_at'],
            'evidence_label': 'Scheda regionale consultata', 'published_date': item['published_date']}


def status():
    from ..facilities import all_facilities
    catalog = [f for f in all_facilities() if f['type'] == 'community_house']
    records = _snapshot.get('records', {})
    matched = sum(record(f) is not None for f in catalog)
    return {'source_url': SOURCE, 'retrieved_at': _snapshot.get('retrieved_at'), 'fresh': fresh(),
            'error': _error, 'regional_cards': len(records), 'catalog_sites': len(catalog),
            'matched_sites': matched, 'unmatched_sites': len(catalog)-matched,
            'cards_by_asl': dict(Counter(r['asl'] for r in records.values())),
            'document_links': sum(bool(r.get('document_url')) for r in records.values()),
            'limitation': 'Schede pubblicate, non disponibilità in tempo reale dei servizi; gli orari completi non sono inclusi.'}
