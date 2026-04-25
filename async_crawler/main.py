"""入口 — 支持单次运行和调度循环两种模式

用法:
  python -m async_crawler          # 单次全量抓取
  python -m async_crawler --loop   # 按 config.SCHEDULE 定时循环
"""
import asyncio
import logging
import sys
import time
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("crawler.main")


async def run_once():
    from async_crawler.base import create_ssl_context
    from async_crawler.db import Database
    from async_crawler.sources import (
        appstore_rank, reviews, sensor_tower,
        androidrank, reddit, iap_pricing, fb_adlib,
    )
    SOURCES = [
        ("App Store 排名", appstore_rank),
        ("用户评论",       reviews),
        ("Sensor Tower",  sensor_tower),
        ("Androidrank",   androidrank),
        ("Reddit 舆情",   reddit),
        ("IAP 定价",      iap_pricing),
        ("Ad Library",    fb_adlib),
    ]

    db = Database()
    await db.connect()
    t0 = time.monotonic()

    connector = aiohttp.TCPConnector(ssl=create_ssl_context(), limit=20)
    async with aiohttp.ClientSession(connector=connector) as session:
        results = await asyncio.gather(
            *[m.crawl(session, db) for _, m in SOURCES],
            return_exceptions=True,
        )

    log.info("=" * 50)
    for (label, _), result in zip(SOURCES, results):
        if isinstance(result, Exception):
            log.error(f"  {label}: 失败 — {result}")
        else:
            log.info(f"  {label}: {len(result)} 条")
    log.info(f"总耗时: {time.monotonic() - t0:.1f}s")
    await db.close()


def main():
    if "--loop" in sys.argv:
        from async_crawler.scheduler import Scheduler
        asyncio.run(Scheduler().loop())
    else:
        asyncio.run(run_once())


if __name__ == "__main__":
    main()
