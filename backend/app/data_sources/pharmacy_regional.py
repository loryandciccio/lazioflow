"""Provincial official calendars: dated shifts, document fallback, no inferred opening."""
from __future__ import annotations

import asyncio
import calendar
import io
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, unquote
from zoneinfo import ZoneInfo

import httpx

from ..config import DB_PATH, LIVE_DISABLED
from .source_utils import PROVINCES, age, clean, fetch, key, municipality, province, save_atomic

SOURCES = {
    'RM': {'name':'Ordine Farmacisti Roma', 'url':'https://www.ordinefarmacistiroma.it/cittadino/turni-delle-farmacie.html'},
    'VT': {'name':'Ordine Farmacisti Viterbo', 'url':'https://www.ordinefarmacistiviterbo.it/?page_id=30'},
    'FR': {'name':'Ordine Farmacisti Frosinone', 'url':'https://www.ordinefarmacistifr.it/1-2/'},
    'LT': {'name':'Ordine Farmacisti Latina', 'url':'https://www.ordinefarmacistilatina.it/farmacie-di-turno/'},
    'RI': {'name':'ASL Rieti', 'url':'https://www.asl.rieti.it/organizzazione-aziendale/dipartimenti-aree-e-staff/dipartimento-del-farmaco/uoc-politica-del-farmaco-e-dei-dispositivi-medici/uos-assistenza-farmaceutica-territoriale/'},
}
CACHE = DB_PATH.with_name('pharmacy_regional.json')
MONTHS = 'gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre'.split()
TZ = ZoneInfo('Europe/Rome')
TTL = 6 * 3600
MAX_AGE = 24 * 3600
_snapshot = {}
_errors = {}


class Links(HTMLParser):
    def __init__(self, base):
        super().__init__()
        self.base, self.rows, self.current, self.text = base, {}, None, []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.current = dict(attrs).get('href')
            self.text = []

    def handle_data(self, data):
        if self.current:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.current:
            url = urljoin(self.base, self.current)
            label = clean(' '.join(self.text))
            if urlparse(url).hostname == urlparse(self.base).hostname and urlparse(url).path.lower().endswith('.pdf'):
                previous = self.rows.get(url)
                if not previous or label.lower() != 'download':
                    self.rows[url] = {'url': url, 'label': label}
            self.current = None


def document_links(page, code):
    links = Links(SOURCES[code]['url'])
    links.feed(page)
    return [r for r in links.rows.values() if 'turn' in (r['label'] + unquote(r['url'])).lower() or code == 'LT' and 'farmacie-di-turno/' in r['url']]


def pdf_pages(content):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    if len(reader.pages) > 80:
        raise ValueError('calendario troppo lungo')
    return [p.extract_text(extraction_mode='layout') or '' for p in reader.pages]


def parse_viterbo(pages):
    rows = []
    for text in pages:
        start = re.search(r'Da Luned[iì]\s+(\d{2}/\d{2}/\d{2,4})\s+Dalle ore\s+(\d{2}:\d{2})', text, re.I)
        end = re.search(r'A Luned[iì]\s+(\d{2}/\d{2}/\d{2,4})\s+Alle ore\s+(\d{2}:\d{2})', text, re.I)
        if not start or not end:
            continue
        def stamp(match):
            fmt = '%d/%m/%y %H:%M' if len(match[1]) == 8 else '%d/%m/%Y %H:%M'
            return datetime.strptime(match[1]+' '+match[2], fmt).replace(tzinfo=TZ)
        since, until = stamp(start), stamp(end)
        if until - since != timedelta(days=7) or 'REPERIBILITA' not in text.upper():
            continue
        for line in text.splitlines():
            m = re.match(r'^\s*([A-Z .\'’]+?)\s+Farm\s+(.+?)(?:\s{3,}|$)', line)
            if m:
                rows.append({'municipality': key(m[1]), 'name': clean(m[2]), 'starts_at': since.isoformat(),
                             'ends_at': until.isoformat(), 'kind': 'on_call'})
    return rows


def parse_frosinone(pages):
    rows = []
    for text in pages:
        if not re.search(r"TURNI FARMACIE CITT[AÀ]['’]? DI FROSINONE", text, re.I):
            continue
        header = re.search(r'\b('+'|'.join(MONTHS)+r')\s+(20\d{2})\b', text, re.I)
        if not header:
            continue
        year, month = int(header[2]), MONTHS.index(header[1].lower())+1
        found = []
        for line in text.splitlines():
            m = re.match(r'^\s*(\d{1,2})\s+(?:LUNEDI|MARTEDI|MERCOLEDI|GIOVEDI|VENERDI|SABATO|DOMENICA)[’\'ÌI]*\s+(.+?)\s+[–—-]\s+(.+)', line, re.I)
            if m:
                since = datetime(year, month, int(m[1]), 8, 30, tzinfo=TZ)
                found.append({'municipality':'FROSINONE', 'name':clean(m[2]), 'address':clean(m[3]),
                              'starts_at':since.isoformat(), 'ends_at':(since+timedelta(days=1)).isoformat(), 'kind':'shift'})
        # Partial extraction must not masquerade as a complete city calendar.
        if len({r['starts_at'] for r in found}) == calendar.monthrange(year, month)[1]:
            rows.extend(found)
    return rows


def parse_rieti(pages):
    rows = []
    city_section = False
    for text in pages:
        if re.search(r"TURNI CITT[AÀ]['’]? DI RIETI", text, re.I):
            city_section = True
        if 'TURNI DOMENICALI' in text.upper():
            city_section = False
        if not city_section:
            continue
        for line in text.splitlines():
            m = re.match(r'^\s*(?:lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica)\s+(\d{1,2})\s+('+'|'.join(MONTHS)+r')\s+(20\d{2})\s+(.+?)\s*\((.+)\)\s*$', line, re.I)
            if m:
                day = datetime(int(m[3]), MONTHS.index(m[2].lower())+1, int(m[1])).date()
                rows.append({'municipality':'RIETI', 'name':clean(m[4]), 'address':clean(m[5]),
                             'date':day.isoformat(), 'kind':'calendar_day'})
    return rows


def parse_pdf(content, code):
    pages = pdf_pages(content)
    parser = {'VT':parse_viterbo, 'FR':parse_frosinone, 'RI':parse_rieti}.get(code)
    return (parser(pages) if parser else []), any(p.strip() for p in pages)


def relevant(doc, code, now):
    # Upload directories are not calendar validity (a 2027 PDF can be uploaded in 2026).
    text = unquote(urlparse(doc['url']).path.rsplit('/', 1)[-1]+' '+doc['label']).lower()
    years = re.findall(r'\b20\d{2}\b', text)
    if years and str(now.year) not in years:
        return False
    months = [m for m in MONTHS if m in text]
    if code in ('FR','VT') and len(months) == 1 and not any(MONTHS[(now.month-1+i)%12] in months for i in (-1,0,1)):
        return False
    return True


def load_cache():
    global _snapshot
    try:
        data = json.loads(CACHE.read_text())
        if isinstance(data, dict) and all(isinstance(v, dict) and isinstance(v.get('documents'), list) and isinstance(v.get('rows'), list) for v in data.values()):
            _snapshot = data
    except (OSError, ValueError):
        pass


async def refresh():
    if LIVE_DISABLED:
        return
    now = datetime.now(TZ)
    semaphore = asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=25, headers={'User-Agent':'LazioFlow/0.1 public healthcare directory'}) as client:
        async def one(code):
            if 0 <= age(_snapshot.get(code, {}).get('retrieved_at')) < TTL:
                return
            spec = SOURCES[code]
            hosts = {urlparse(spec['url']).hostname}
            try:
                async with semaphore:
                    page = (await fetch(client, spec['url'], hosts)).decode('utf-8', 'replace')
                links = document_links(page, code)
                if not links:
                    raise ValueError('nessun calendario provinciale trovato')
                documents, rows = [], []
                # Keep every official link, parse bounded selection near the current date.
                for doc in links:
                    item = {**doc, 'extraction':'document_only'}
                    if relevant(doc, code, now) and len(documents) < 40:
                        try:
                            async with semaphore:
                                content = await fetch(client, doc['url'], hosts)
                            extracted, has_text = await asyncio.to_thread(parse_pdf, content, code)
                            checked = datetime.now(timezone.utc).isoformat()
                            item.update({'retrieved_at':checked, 'extraction':'structured' if extracted else 'unsupported_layout' if has_text else 'scanned_pdf', 'rows':len(extracted)})
                            rows.extend({**r, 'source_url':doc['url'], 'retrieved_at':checked} for r in extracted)
                        except Exception as exc:
                            previous = _snapshot.get(code, {})
                            old = next((d for d in previous.get('documents', []) if d['url'] == doc['url']), {})
                            if old:
                                item = {**old, **doc}
                                rows.extend(r for r in previous.get('rows', []) if r.get('source_url') == doc['url'])
                            item['error'] = type(exc).__name__
                    documents.append(item)
                _snapshot[code] = {'retrieved_at':datetime.now(timezone.utc).isoformat(), 'documents':documents, 'rows':rows}
                _errors.pop(code, None)
            except Exception as exc:
                _errors[code] = {'at':datetime.now(timezone.utc).isoformat(), 'error':type(exc).__name__}
        await asyncio.gather(*(one(code) for code in SOURCES if code != 'RM'))
    save_atomic(CACHE, _snapshot)


# Explicit town abbreviations in the Viterbo weekly calendar, never fuzzy matching.
TOWNS = {'CIVITACASTELLANA':'CIVITA CASTELLANA', 'MONTALTO':'MONTALTO DI CASTRO',
         'SORIANO':'SORIANO NEL CIMINO', 'GROTTE CASTRO':'GROTTE DI CASTRO',
         'VT BAGNAIA':'VITERBO', 'VT GROTTE S STEFANO':'VITERBO', 'TARQUINIA LIDO':'TARQUINIA',
         'VILLA S GIOVANNI':'VILLA SAN GIOVANNI IN TUSCIA'}


def pharmacy_name(value):
    tokens = key(value).split()
    ignored = {'FARMACIA','FARMACIE','FARM','DR','DOTT','DOTTSSA','SAS','SNC','SRL','SPA','DI','DEL','DELLA','DEI','E'}
    return ' '.join(t for t in tokens if t not in ignored)


def match_row(row, code, catalog):
    town = TOWNS.get(row['municipality'], row['municipality'])
    local = [f for f in catalog if province(f) == code and municipality(f) == town]
    name = pharmacy_name(row['name'])
    if not name:
        return None
    # Exact normalized name, or distinctive complete name within the legal denomination.
    matches = [f for f in local if pharmacy_name(f['name']) == name or len(name) >= 5 and (' '+name+' ') in (' '+pharmacy_name(f['name'])+' ')]
    if len(matches) == 1:
        return matches[0]['facility_id']
    if row.get('address'):
        from .pharmacy_live import address_key
        address = row['address']
        m = re.search(r'\b(?:via|viale|piazza|p\.zza)\b', address, re.I)
        if m:
            address = address[m.start():]
        addr = address_key(address)
        matches = [f for f in local if address_key(f['address']) == addr]
        if len(matches) == 1:
            return matches[0]['facility_id']
    return None


def active(row, now):
    if row.get('date'):
        return row['date'] == now.astimezone(TZ).date().isoformat()
    try:
        return datetime.fromisoformat(row['starts_at']) <= now < datetime.fromisoformat(row['ends_at'])
    except (ValueError, KeyError, TypeError):
        return False


_index = {}
_index_token = None


def indexed():
    global _index, _index_token
    token = tuple((code, value.get('retrieved_at')) for code, value in _snapshot.items())
    if token != _index_token:
        from ..facilities import all_facilities
        catalog = [f for f in all_facilities() if f['type'] == 'pharmacy']
        result = {}
        for code, snapshot in _snapshot.items():
            for row in snapshot.get('rows', []):
                fid = match_row(row, code, catalog)
                if fid:
                    result.setdefault(fid, []).append(row)
        _index, _index_token = result, token
    return _index


def opening(facility, now):
    code = province(facility)
    if code not in SOURCES or code == 'RM':
        return None
    spec = SOURCES[code]
    snapshot = _snapshot.get(code, {})
    is_fresh = 0 <= age(snapshot.get('retrieved_at'), now) <= MAX_AGE
    rows = [r for r in indexed().get(facility['facility_id'], []) if active(r, now) and 0 <= age(r.get('retrieved_at'), now) <= MAX_AGE] if is_fresh else []
    base = {'status':'unknown_hours','known':False,'source_url':spec['url'],
            'retrieved_at':snapshot.get('retrieved_at'), 'evidence_label':'Elenco provinciale consultato',
            'province':code, 'on_duty':False, 'label':'Orario della farmacia non verificato; consulta i turni provinciali o chiama.'}
    if code == 'LT' and is_fresh:
        town = municipality(facility)
        docs = [d for d in snapshot.get('documents', [])
                if key(re.split(r'\s+Agg\.?', d['label'], flags=re.I)[0].removesuffix('.pdf')) == town
                and not d.get('error') and d.get('retrieved_at')]
        if len(docs) == 1:
            base.update({'source_url':docs[0]['url'], 'retrieved_at':docs[0]['retrieved_at'],
                         'evidence_label':'Calendario comunale consultato',
                         'label':'Orari, turni e ferie nel calendario comunale collegato; apertura attuale da verificare.'})
    if rows:
        # Multiple differing matches remain documentary information, never "open now".
        row = sorted(rows, key=lambda r:r['retrieved_at'], reverse=True)[0]
        if row['kind'] == 'on_call':
            label = 'Nel turno settimanale; durante la chiusura reperibilità a chiamata per ricette urgenti. Chiama prima.'
        elif row['kind'] == 'calendar_day':
            label = 'Indicata nel calendario di oggi; fascia oraria non pubblicata nel calendario: chiama prima.'
        else:
            start, end = datetime.fromisoformat(row['starts_at']), datetime.fromisoformat(row['ends_at'])
            label = f"Turno pubblicato: {start:%d/%m %H:%M}–{end:%d/%m %H:%M}. Modalità di accesso da verificare: chiama prima."
        return {**base, 'label':label, 'on_duty':True, 'source_url':row['source_url'],
                'retrieved_at':row['retrieved_at'], 'evidence_label':'Calendario turni consultato',
                'source_date':row.get('date'), 'starts_at':row.get('starts_at'), 'ends_at':row.get('ends_at'), 'kind':row['kind']}
    if not is_fresh:
        base['label'] = 'Aggiornamento dei turni non disponibile; consulta la fonte provinciale o chiama.'
    return base


def status():
    now = datetime.now(timezone.utc)
    return {code: {**spec, 'province_name':PROVINCES[code],
                   'retrieved_at':_snapshot.get(code, {}).get('retrieved_at'),
                   'fresh':0 <= age(_snapshot.get(code, {}).get('retrieved_at'), now) <= MAX_AGE,
                   'documents':_snapshot.get(code, {}).get('documents', []),
                   'calendar_rows':len(_snapshot.get(code, {}).get('rows', [])),
                   'active_rows':sum(active(r, now) for r in _snapshot.get(code, {}).get('rows', [])),
                   'error':_errors.get(code)} for code, spec in SOURCES.items() if code != 'RM'}
