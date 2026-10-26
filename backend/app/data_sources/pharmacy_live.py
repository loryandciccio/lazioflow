"""Aggiornamento automatico delle fonti ufficiali di Roma, senza modificare il catalogo."""
from __future__ import annotations

import asyncio
import html
import io
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from ..config import DB_PATH, LIVE_DISABLED

SITE = 'https://www.ordinefarmacistiroma.it'
CACHE = DB_PATH.with_name('pharmacy_openings.json')
log = logging.getLogger('lazioflow.pharmacies')
_snapshot: dict = {}
_errors: dict = {}


def address_key(value):
    value = re.split(r'\b\d{5}\b', value or '')[0]
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().upper()
    tokens = re.sub(r'[^A-Z0-9 ]+', ' ', value).split()
    ignored = {'VIA', 'VIALE', 'PIAZZA', 'PIAZZALE', 'LARGO', 'CORSO', 'VICOLO', 'DI', 'DEL', 'DELLA', 'DELLE', 'DEGLI', 'DEI', 'D', 'LE', 'V'}
    return re.sub(r'(\d)\s+([A-Z])\b', r'\1\2', ' '.join(t for t in tokens if t not in ignored))


def parse_daily(page, day):
    # Non attribuire a oggi una pagina che il server ha restituito per un altro giorno.
    visible = html.unescape(re.sub('<[^>]+>', ' ', page))
    expected = datetime.fromisoformat(day).strftime('%d/%m/%Y')
    if not re.search(r'Farmacie\s+di\s+turno\s+a\s+Roma\s+il\s+' + re.escape(expected), visible, re.I):
        raise ValueError('data della pagina non confermata')
    rows = []
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', page, re.S | re.I):
        cells = re.findall(r'<td\b[^>]*class=["\'][^"\']*shift_(\w+)[^"\']*["\'][^>]*>(.*?)</td>', row, re.S | re.I)
        data = {k: html.unescape(re.sub('<[^>]+>', '', v)).strip() for k, v in cells}
        if data.get('name') and data.get('address'):
            rows.append({'address': address_key(data['address']), 'phone': data.get('phone')})
    if not rows:
        raise ValueError('nessuna farmacia estratta: conservata ultima copia valida')
    return rows


def parse_pdf(content):
    from pypdf import PdfReader
    rows = []
    for page in PdfReader(io.BytesIO(content)).pages:
        for line in (page.extract_text() or '').splitlines():
            if not re.search(r'\b\d{5}\b', line):
                continue
            match = re.search(r'\b(?:VIALE|VIA|PIAZZALE|PIAZZA|LARGO|CORSO|VICOLO)\b', line, re.I)
            if match:
                rows.append({'address': address_key(line[match.start():])})
    if not rows:
        raise ValueError('PDF senza indirizzi validi')
    return rows


def load_cache():
    global _snapshot
    try:
        data = json.loads(CACHE.read_text())
        if isinstance(data, dict) and all(isinstance(v, dict) and isinstance(v.get('rows'), list) for v in data.values()):
            _snapshot = data
    except (OSError, ValueError):
        pass


def age(source, now):
    try:
        return (now - datetime.fromisoformat(source['retrieved_at'])).total_seconds()
    except (KeyError, ValueError, TypeError):
        return float('inf')


async def refresh():
    global _snapshot
    if LIVE_DISABLED:
        return
    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo('Europe/Rome')).date().isoformat()
    specs = [('daily', f'{SITE}/cittadino/turni-delle-farmacie.html?d={day}', 3600),
             ('h24', f'{SITE}/files/turni/farmacie_aperte_h24.pdf', 86400),
             ('h12', f'{SITE}/files/turni/farmacie_aperte_h12.pdf', 86400)]
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={'User-Agent': 'LazioFlow/0.1'}) as client:
        for key, url, ttl in specs:
            previous = _snapshot.get(key, {})
            if 0 <= age(previous, now) < ttl and (key != 'daily' or previous.get('date') == day):
                continue
            try:
                response = await client.get(url)
                response.raise_for_status()
                rows = parse_daily(response.text, day) if key == 'daily' else await asyncio.to_thread(parse_pdf, response.content)
                current = {'rows': rows, 'date': day, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'source_url': url}
                updated = {**_snapshot, key: current}
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                # Pubblicazione atomica: mai leggere o servire un file scritto a metà.
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', dir=CACHE.parent, delete=False) as f:
                    json.dump(updated, f)
                    temp = f.name
                from pathlib import Path
                Path(temp).replace(CACHE)
                _snapshot = updated
                _errors.pop(key, None)
            except Exception as exc:
                _errors[key] = {'at': now.isoformat(), 'error': type(exc).__name__}
                log.warning('aggiornamento farmacie %s fallito: %s', key, type(exc).__name__)


async def run():
    from . import cdc_hours, cdc_regional
    load_cache()
    cdc_hours.load_cache()
    cdc_regional.load_cache()
    while True:
        await refresh()
        await cdc_hours.refresh()
        await cdc_regional.refresh()
        await asyncio.sleep(300)  # retry e cambio giorno; TTL separati per ogni fonte


def overlay(facility):
    if facility.get('type') != 'pharmacy' or not re.search(r'\b\d{5}\s+Roma\s*\(RM\)', facility.get('address', ''), re.I):
        return facility
    now = datetime.now(timezone.utc)
    opening = dict(facility.get('opening') or {})
    for field in ('h24', 'h12'):
        opening[field + '_verified_at'] = opening.get('retrieved_at')
    key = address_key(facility['address'])
    phone = facility.get('phone')
    for kind in ('daily', 'h12', 'h24'):
        source = _snapshot.get(kind)
        if not source:
            continue
        matches = [r for r in source['rows'] if r.get('address') == key]
        # Abbinamento esatto e non ambiguo; non usare corrispondenze fuzzy sugli indirizzi.
        matched = len(matches) == 1
        if kind == 'daily':
            opening['on_duty'] = {'date': source['date'], 'value': matched}
            opening['daily_retrieved_at'] = source['retrieved_at']
            opening['daily_source_url'] = source['source_url']
            opening['source_url'] = source['source_url']
            opening['retrieved_at'] = source['retrieved_at']
            if matched:
                phone = matches[0].get('phone') or phone
        else:
            field = 'h24_all_year' if kind == 'h24' else 'h12_8_20_all_year'
            opening[field] = matched and 0 <= age(source, now) <= 172800
            opening[kind + '_verified_at'] = source['retrieved_at']
        if matched:
            opening['source_url'] = source['source_url']
            opening['retrieved_at'] = source['retrieved_at']
    return {**facility, 'opening': opening, 'phone': phone}


def status():
    now = datetime.now(timezone.utc)
    return {'sources': {key: {'retrieved_at': value['retrieved_at'], 'date': value['date'],
                              'rows': len(value['rows']), 'age_seconds': round(age(value, now)), 'source_url': value['source_url']}
                        for key, value in _snapshot.items()}, 'errors': dict(_errors), 'enabled': not LIVE_DISABLED}


if __name__ == '__main__':
    load_cache()
    asyncio.run(refresh())
    print(json.dumps(status(), ensure_ascii=False, indent=2))
