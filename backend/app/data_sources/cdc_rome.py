"""Rome ASL directory discovery and service opening notices, with site identity checks."""
import asyncio
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from ..config import DB_PATH, LIVE_DISABLED
from .source_utils import age, asl_key, clean, fetch, key, save_atomic

ROOTS = {'Roma 1':'https://www.aslroma1.it/case-della-comunita',
         'Roma 3':'https://www.aslroma3.it/servizi-dalla-a-alla-z/c/case-di-comunita/'}
PRELIEVI = 'https://www.aslroma2.it/index.php/strutture-8d/centri-prelievi-8'
CACHE = DB_PATH.with_name('cdc_rome.json')
_records = {}
_errors = {}


class Directory(HTMLParser):
    def __init__(self, base):
        super().__init__()
        self.base, self.links, self.href, self.text = base, {}, None, []
    def handle_starttag(self, tag, attrs):
        if tag=='a':
            self.href = dict(attrs).get('href'); self.text=[]
    def handle_data(self, text):
        if self.href:
            self.text.append(text)
    def handle_endtag(self, tag):
        if tag=='a' and self.href:
            url=urljoin(self.base,self.href)
            title=clean(' '.join(self.text))
            if urlparse(self.base).hostname == 'www.aslroma1.it':
                title = re.split(r'\s+(?:Via|Viale|Piazza|Circonvallazione)\b', title, maxsplit=1)[0]
            if urlparse(url).hostname==urlparse(self.base).hostname and '/casa-della-comunita-' in url and key(title).startswith('CASA DELLA COMUNITA'):
                self.links[url]=title
            self.href=None


def site_key(title):
    title=key(title).removeprefix('CASA DELLA COMUNITA ')
    for part in ('CDC HUB ', 'CDC SPOKE ', 'HUB ', 'SPOKE '):
        title=title.removeprefix(part)
    return title


def match_site(title, asl, catalog):
    name=site_key(title)
    candidates=[f for f in catalog if f['type']=='community_house' and asl_key(f.get('asl'))==asl]
    matches=[f for f in candidates if site_key(f['name'])==name or key((f.get('ids') or {}).get('salutelazio_card'))==name]
    return matches[0]['facility_id'] if len(matches)==1 else None


def parse_roma1(page):
    sections=[]
    # Extract the labelled accordion body, not menu text or unrelated hospital opening hours.
    for block in re.split(r'<div\s+class="details-ticket"',page)[1:]:
        header=re.search(r'<a[^>]*class="details-header"[^>]*>(.*?)</a>',block,re.S)
        content=re.search(r'<div\s+class="details-content"[^>]*>(.*?)</div>',block,re.S)
        if not header or not content:
            continue
        label=clean(header[1])
        if label in ('Orario Apertura Presidio','Orari Prenotazione Pagamento Ticket (CUP)'):
            # Sentence/paragraph boundary avoids truncating exclusions in the middle.
            paragraphs=[clean(p) for p in re.findall(r'<p\b[^>]*>(.*?)</p>',content[1],re.S)]
            paragraphs=[p for p in paragraphs if re.search(r'\d[.:]\d{2}|24 ore|h24',p,re.I)]
            if paragraphs:
                sections.append({'service':label,'text':' '.join(paragraphs)})
    return sorted(sections, key=lambda s: s['service'] != 'Orario Apertura Presidio')


def parse_roma3(page):
    text=clean(re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', page,flags=re.S|re.I))
    # Site-specific sentence, not the generic DM77 standard in the page footer.
    match=re.search(r'(?:è|e\x27) aperta\s+(.{0,220}?)(?:\.(?=\s|$)|;)',text,re.I)
    if match and re.search(r'\d|h24',match[1],re.I):
        return [{'service':'Apertura della sede dichiarata dalla ASL','text':match[1]}]
    return []


def parse_prelievi(page, catalog):
    text=clean(re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', page,flags=re.S|re.I))
    result={}
    for section in text.split('Sede:')[1:]:
        if not section.startswith(' Casa della Comunità'):
            continue
        identity=re.split(r'\b[Vv]ia\b|Telefono:|Orari Prelievi:',section,maxsplit=1)[0].strip().rstrip(' ,')
        fid=match_site(identity,'Roma 2',catalog)
        if not fid:
            # Explicit, unambiguous prefix of the published site name (e.g. San Nemesio Garbatella).
            name=site_key(identity)
            matches=[f for f in catalog if f['type']=='community_house' and asl_key(f.get('asl'))=='Roma 2'
                     and len(site_key(f['name']))>=6 and name.startswith(site_key(f['name'])+' ')]
            fid=matches[0]['facility_id'] if len(matches)==1 else None
        hours=re.search(r'Orari Prelievi:\s*(.*?)\s*Orario Ritiro',section,re.I)
        pickup=re.search(r'Orario Ritiro Referti presso CUP:\s*(.*?)(?:Referti sul|Linee di Attività:)',section,re.I)
        if fid and hours and len(hours[1])<350:
            services=[{'service':'Prelievi','text':hours[1]}]
            if pickup and len(pickup[1])<350:
                services.append({'service':'Ritiro referti CUP','text':pickup[1]})
            result[fid]=services
    return result


def load_cache():
    global _records
    try:
        data=json.loads(CACHE.read_text())
        if isinstance(data,dict) and all(isinstance(v,dict) and isinstance(v.get('services'),list) for v in data.values()):
            _records=data
    except (OSError,ValueError):
        pass


async def refresh():
    if LIVE_DISABLED:
        return
    from ..facilities import all_facilities
    catalog=all_facilities()
    semaphore=asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=20) as client:
        async def get(url):
            async with semaphore:
                return (await fetch(client,url,{'www.aslroma1.it','www.aslroma2.it','www.aslroma3.it'})).decode('utf-8','replace')
        async def site(url,title,asl):
            fid=match_site(title,asl,catalog)
            if not fid or 0<=age(_records.get(fid,{}).get('retrieved_at'))<86400:
                return
            try:
                page=await get(url)
                services=(parse_roma1 if asl=='Roma 1' else parse_roma3)(page)
                if not services:
                    raise ValueError('orario non riconosciuto nella scheda')
                _records[fid]={'services':services,'source_url':url,'retrieved_at':datetime.now(timezone.utc).isoformat()}
                _errors.pop(url,None)
            except Exception as exc:
                _errors[url]=type(exc).__name__
        async def directory(asl,url):
            try:
                parser=Directory(url);parser.feed(await get(url))
                if not parser.links:
                    raise ValueError('nessuna sede trovata')
                await asyncio.gather(*(site(u,t,asl) for u,t in list(parser.links.items())[:40]))
                _errors.pop(url,None)
            except Exception as exc:
                _errors[url]=type(exc).__name__
        async def prelievi():
            existing=[r for r in _records.values() if r.get('source_url')==PRELIEVI]
            if existing and all(0<=age(r['retrieved_at'])<86400 for r in existing):
                return
            try:
                records=parse_prelievi(await get(PRELIEVI),catalog)
                if not records:
                    raise ValueError('nessun orario prelievi associato')
                now=datetime.now(timezone.utc).isoformat()
                for fid,services in records.items():
                    _records[fid]={'services':services,'source_url':PRELIEVI,'retrieved_at':now}
                _errors.pop(PRELIEVI,None)
            except Exception as exc:
                _errors[PRELIEVI]=type(exc).__name__
        await asyncio.gather(*(directory(a,u) for a,u in ROOTS.items()),prelievi())
    save_atomic(CACHE,_records)


def details(fid):
    record=_records.get(fid)
    if not record or not 0<=age(record.get('retrieved_at'))<=7*86400:
        return None
    parts=[]
    for service in record['services']:
        # Keep the card short; full service notices remain in API + source link.
        text=service['text']
        if len(text)>350:
            text=text[:text.rfind(' ',0,330)]+'… (dettagli nella scheda ASL)'
        parts.append(service['service']+': '+text)
    return {**record,'known':False,'status':'unknown_hours','evidence_label':'Scheda ASL consultata',
            'label':' '.join(parts[:2])+' Orari pubblicati; disponibilità e accesso dei singoli servizi da confermare.'}


def status():
    return {'matched_sites':len(_records),'fresh_sites':sum(details(fid) is not None for fid in _records),
            'sources':{fid:{'source_url':r['source_url'],'retrieved_at':r['retrieved_at']} for fid,r in _records.items()},'errors':dict(_errors)}
