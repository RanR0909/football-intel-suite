"""定时调度器 — 按配置间隔循环运行各数据源"""
import asyncio
import logging
import time

import aiohttp

from async_crawler.config import SCHEDULE
from async_crawler.base import create_ssl_context
from async_crawler.db import Database

log = logging.getLogger("crawler.scheduler")


class Scheduler:
    def __init__(self):
        self.db = Database()
        self._last_run: dict[str, float] = {}

    def _due(self, source_name: str) -> bool:
        interval = SCHEDULE.get(source_name, 86400)
        return time.monotonic() - self._last_run.get(source_name, 0) >= interval

    async def run_source(self, session, module):
        name = module.__name__.split(".")[-1]
        try:
            results = await module.crawl(session, self.db)
            self._last_run[name] = time.monotonic()
            log.info(f"[{name}] 完成: {len(results)} 条")
        except Exception as e:
            log.error(f"[{name}] 失败: {e}")

    async def loop(self, tick: int = 60):
        """主循环，每 tick 秒检查哪些源到期需要运行"""
        from async_crawler.sources import (
            appstore_rank, reviews, sensor_tower,
            androidrank, reddit, iap_pricing, fb_adlib,
        )
        modules = [appstore_rank, reviews, sensor_tower, androidrank, reddit, iap_pricing, fb_adlib]

        await self.db.connect()
        log.info("调度器启动")

        connector = aiohttp.TCPConnector(ssl=create_ssl_context(), limit=20)
        async with aiohttp.ClientSession(connector=connector) as session:
            while True:
                due = [m for m in modules if self._due(m.__name__.split(".")[-1])]
                if due:
                    log.info(f"本轮运行: {[m.__name__.split('.')[-1] for m in due]}")
                    await asyncio.gather(*[self.run_source(session, m) for m in due], return_exceptions=True)
                await asyncio.sleep(tick)

        await self.db.close()
