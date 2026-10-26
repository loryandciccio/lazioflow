"""Utilities for bounded public-source ingestion and geographic matching."""
import html
import json
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PROVINCES = {'RM': 'Roma', 'VT': 'Viterbo', 'RI': 'Rieti', 'LT': 'Latina', 'FR': 'Frosinone'}


def clean(value):
    return ' '.join(html.unescape(re.sub('<[^>]*>', ' ', value or '')).split())


def key(value):
    value = unicodedata.normalize('NFKD', clean(value)).encode('ascii', 'ignore').decode().upper()
    return ' '.join(re.sub('[^A-Z0-9]+', ' ', value).split())


def asl_key(value):
    value = key(value).removeprefix('ASL ')
    match = re.match(r'ROMA\s*([1-6])\b', value)
    if match:
        return 'Roma ' + match[1]
    for code, name in PROVINCES.items():
        if value in (code, name.upper()):
            return name
    return None


def province(facility):
    address = facility.get('address') or ''
    match = re.search(r'\b(RM|VT|RI|LT|FR)\b', address, re.I)
    if match:
        return match[1].upper()
    asl = asl_key(facility.get('asl'))
    if asl:
        return 'RM' if asl.startswith('Roma') else next((k for k,v in PROVINCES.items() if v == asl), None)
    postal = re.search(r'\b(00|01|02|03|04)\d{3}\b', address)
    return {'00':'RM','01':'VT','02':'RI','03':'FR','04':'LT'}.get(postal[1]) if postal else None


def municipality(facility):
    match = re.search(r'\b\d{5}\s+(.+?)\s*\((?:RM|VT|RI|LT|FR)\)', facility.get('address') or '', re.I)
    return key(match[1]) if match else None


def age(timestamp, now=None):
    try:
        return ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(timestamp)).total_seconds()
    except (ValueError, TypeError):
        return float('inf')


def save_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False)
        temp.replace(path)
    finally:
        if temp and temp.exists():
            temp.unlink()


async def fetch(client, url, hosts, max_bytes=12_000_000):
    """Only configured public hosts; bounded downloads, including redirects."""
    for _ in range(5):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password:
            raise ValueError('host della fonte non autorizzato')
        async with client.stream('GET', url, follow_redirects=False) as response:
            if response.is_redirect:
                from urllib.parse import urljoin
                url = urljoin(url, response.headers['location'])
                continue
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise ValueError('documento troppo grande')
            return bytes(data)
    raise ValueError('troppi redirect')
