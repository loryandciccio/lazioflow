"""Schede ASL pilota: dati per servizio, distinti dall'apertura complessiva della sede."""
import asyncio
import html
import json
import logging
import re
from datetime import datetime, timezone

import httpx

from ..config import DB_PATH, LIVE_DISABLED

CACHE = DB_PATH.with_name('cdc_hours.json')
MAGLIANA = 'https://www.aslroma3.it/servizi-dalla-a-alla-z/c/case-di-comunita/casa-della-comunita-cdc-hub-magliana/'
PRELIEVI = 'https://www.aslroma2.it/index.php/strutture-8d/centri-prelievi-8'
_records = {}
_errors = {}


def parse(page, source):
    page = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', page, flags=re.S|re.I)
    text = ' '.join(html.unescape(re.sub('<[^>]*>', ' ', page)).split())
    out = {}
    if source == MAGLIANA:
        if re.search(r'via Vaiano,? 53', text, re.I) and re.search(r'aperta tutti i giorni dal lunedì alla domenica,? 24 ore', text, re.I):
            out['cdc:curalazio:25'] = 'Sede dichiarata h24 dalla ASL. Gli orari dei singoli servizi e le modalità di accesso variano: contatta la struttura.'
    else:
        for fid, marker in [('cdc:curalazio:35', 'Casa della Comunità San Nemesio Garbatella'),
                            ('cdc:curalazio:50', 'Casa della Comunità Malfante Navigatori')]:
            if marker not in text:
                continue
            section = text.split(marker, 1)[1].split('Sede:', 1)[0]
            prelievi = re.search(r'Orari Prelievi:\s*(.*?)\s*Orario Ritiro', section, re.I)
            referti = re.search(r'Orario Ritiro Referti presso CUP:\s*(.*?)(?:Referti sul|Linee di Attività:)', section, re.I)
            if prelievi and referti and len(prelievi[1]) < 120 and len(referti[1]) < 160:
                out[fid] = f'Prelievi: {prelievi[1]}. Ritiro referti CUP: {referti[1]}. Orari del servizio, non dell’intera sede; verifica festivi e modalità di accesso.'
    if not out:
        raise ValueError('scheda ASL non riconosciuta')
    return out


def load_cache():
    global _records
    try:
        data = json.loads(CACHE.read_text())
        if isinstance(data, dict):
            _records = data
    except (OSError, ValueError):
        pass


def age(record):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(record['retrieved_at'])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return float('inf')


async def refresh():
    global _records
    if LIVE_DISABLED:
        return
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for url in (MAGLIANA, PRELIEVI):
            cached = [r for r in _records.values() if r.get('source_url') == url]
            if cached and all(0 <= age(r) < 86400 for r in cached):
                continue
            try:
                response = await client.get(url)
                response.raise_for_status()
                parsed = parse(response.text, url)
                now = datetime.now(timezone.utc).isoformat()
                updated = {k:v for k,v in _records.items() if v.get('source_url') != url}
                updated.update({k:{'label':v,'source_url':url,'retrieved_at':now} for k,v in parsed.items()})
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                import tempfile
                from pathlib import Path
                with tempfile.NamedTemporaryFile(mode='w', dir=CACHE.parent, delete=False) as f:
                    json.dump(updated, f)
                    name = f.name
                Path(name).replace(CACHE)
                _records = updated
                _errors.pop(url, None)
            except Exception as exc:
                _errors[url] = type(exc).__name__
                logging.getLogger('lazioflow.cdc').warning('aggiornamento scheda ASL fallito: %s', type(exc).__name__)


def details(fid):
    record = _records.get(fid)
    if record and 0 <= age(record) <= 7 * 86400:
        return {**record, 'status':'unknown_hours','known':False, 'evidence_label':'Scheda ASL consultata'}
    return None


def status():
    return {'sources':_records, 'errors':_errors}


if __name__ == '__main__':
    load_cache()
    asyncio.run(refresh())
    print(json.dumps(status(), ensure_ascii=False, indent=2))
