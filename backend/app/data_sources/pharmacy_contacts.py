"""Daily public Rome/province phone directory. No opening hours inferred from contacts."""
import asyncio
import html
import json
import re
from datetime import datetime, timezone

import httpx

from ..config import DB_PATH, LIVE_DISABLED
from .pharmacy_live import address_key
from .source_utils import age, clean, fetch, key, municipality, province, save_atomic

SOURCE = 'https://www.ordinefarmacistiroma.it/cittadino/farmacie.html'
CACHE = DB_PATH.with_name('pharmacy_contacts.json')
_snapshot = {}
_error = None


def parse(page):
    counter = re.search(r'Pagina\s+(\d+)\s+di\s+(\d+)', clean(page))
    if not counter or not 1 <= int(counter[2]) <= 100:
        raise ValueError('paginazione elenco farmacie non riconosciuta')
    rows = []
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', page, re.S|re.I):
        cells = {k:clean(v) for k,v in re.findall(r'<td\b[^>]*class=["\'][^"\']*pharmacy_(\w+)[^"\']*["\'][^>]*>(.*?)</td>', row, re.S|re.I)}
        address, phone = cells.get('address',''), cells.get('phone','')
        town = municipality({'address':address})
        # Ministry address uses a comma where this directory has " - postcode".
        phone = re.sub(r'[^\d+]', '', phone)
        if town and len(phone) >= 6 and '*' not in address:
            rows.append({'address':address_key(address), 'town':town, 'phone':phone})
    return rows, int(counter[1]), int(counter[2])


def load_cache():
    global _snapshot
    try:
        data = json.loads(CACHE.read_text())
        if isinstance(data.get('rows'),list):
            _snapshot = data
    except (OSError, ValueError, AttributeError):
        pass


async def refresh():
    global _snapshot, _error
    if LIVE_DISABLED or 0 <= age(_snapshot.get('retrieved_at')) < 86400:
        return
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            semaphore = asyncio.Semaphore(3)
            async def page(number):
                async with semaphore:
                    content = await fetch(client, SOURCE+f'?page={number}', {'www.ordinefarmacistiroma.it'})
                rows, current, total = parse(content.decode('utf-8','replace'))
                if current != number:
                    raise ValueError('pagina restituita diversa da quella richiesta')
                return rows, total
            first, count = await page(1)
            other = await asyncio.gather(*(page(n) for n in range(2,count+1)))
            if any(total != count for _,total in other):
                raise ValueError('elenco modificato durante il download')
            rows = first + [r for rs,_ in other for r in rs]
            if not rows or len(rows) < .8 * len(_snapshot.get('rows',[])):
                raise ValueError('elenco vuoto o incompleto')
            updated = {'retrieved_at':datetime.now(timezone.utc).isoformat(),'rows':rows,'pages':count}
            save_atomic(CACHE,updated)
            _snapshot, _error = updated,None
    except Exception as exc:
        _error = type(exc).__name__


def overlay(facility):
    if facility.get('type') != 'pharmacy' or province(facility) != 'RM' or not 0 <= age(_snapshot.get('retrieved_at')) <= 7*86400:
        return facility
    address, town = address_key(facility.get('address')), municipality(facility)
    matches = {r['phone'] for r in _snapshot.get('rows',[]) if r['address'] == address and r['town']==town}
    if len(matches) != 1:
        return facility
    return {**facility, 'phone':next(iter(matches)), 'contact_source':{'source_url':SOURCE,'retrieved_at':_snapshot['retrieved_at']}}


def status():
    return {'source_url':SOURCE,'retrieved_at':_snapshot.get('retrieved_at'), 'rows':len(_snapshot.get('rows',[])),
            'fresh':0 <= age(_snapshot.get('retrieved_at')) <= 7*86400, 'error':_error}
