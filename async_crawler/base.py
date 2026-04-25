"""BaseCrawler — 精简版，统一 fetch，Semaphore 并发控制"""
import asyncio
import logging
import random
import ssl
import time
from datetime import datetime, timezone

import aiohttp

from async_crawler.config import MAX_CONCURRENT, REQUEST_TIMEOUT

_semaphore = asyncio.Semaphore(MAX_CONCURRENT)


def create_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class BaseCrawler:
    source_name: str = "unknown"
    rate_limit: float = 1.0
    max_retries: int = 3

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.log = logging.getLogger(f"crawler.{self.source_name}")
        self._last_request = 0.0

    async def _throttle(self):
        elapsed = time.monotonic() - self._last_request
        wait = self.rate_limit - elapsed + random.uniform(0, 0.5)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = time.monotonic()

    async def _request(self, url: str, as_json: bool, **kwargs):
        kwargs.setdefault("headers", {}).setdefault(
            "User-Agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        kwargs.setdefault("ssl", create_ssl_context())
        kwargs.setdefault("timeout", aiohttp.ClientTimeout(total=REQUEST_TIMEOUT))

        for attempt in range(1, self.max_retries + 1):
            await self._throttle()
            async with _semaphore:
                try:
                    async with self.session.get(url, **kwargs) as resp:
                        resp.raise_for_status()
                        return await resp.json(content_type=None) if as_json else await resp.text()
                except Exception as e:
                    self.log.warning(f"[{attempt}/{self.max_retries}] {url} — {e}")
                    if attempt < self.max_retries:
                        await asyncio.sleep(min(attempt ** 2, 10))
                    else:
                        raise

    async def fetch(self, url: str, **kwargs) -> str:
        return await self._request(url, as_json=False, **kwargs)

    async def fetch_json(self, url: str, **kwargs) -> dict:
        return await self._request(url, as_json=True, **kwargs)

    def standardize(self, competitor: str, data: dict, region: str = "") -> dict:
        rec = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": self.source_name,
            "competitor": competitor,
            "data": data,
        }
        if region:
            rec["region"] = region
        return rec

    async def crawl(self, db) -> list[dict]:
        raise NotImplementedError
