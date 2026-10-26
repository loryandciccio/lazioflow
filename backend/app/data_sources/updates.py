"""Independent public-source refresh loops: a slow province cannot block another feed."""
import asyncio
import logging

from . import pharmacy_live, pharmacy_regional, pharmacy_contacts, cdc_hours, cdc_regional, cdc_rome

FEEDS = (pharmacy_live, pharmacy_regional, pharmacy_contacts, cdc_hours, cdc_regional, cdc_rome)
log = logging.getLogger('lazioflow.sources')
_state = {}


def load_caches():
    for feed in FEEDS:
        feed.load_cache()


async def _loop(feed):
    name = feed.__name__.rsplit('.', 1)[-1]
    while True:
        try:
            await feed.refresh()
            _state[name] = 'running'
        except Exception as exc:
            _state[name] = type(exc).__name__
            log.warning('Source refresh %s failed: %s', name, type(exc).__name__)
        await asyncio.sleep(300)


async def run():
    tasks = [asyncio.create_task(_loop(feed)) for feed in FEEDS]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def status():
    return dict(_state)
