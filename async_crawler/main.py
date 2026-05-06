"""入口 — 支持单次运行 / 调度循环 / 单源过滤。

用法:
  python -m async_crawler                          # 单次全量抓取
  python -m async_crawler --loop                   # 按 config.SCHEDULE 定时循环
  python -m async_crawler --sources reddit,twitter  # 仅抓指定源（半角逗号）
"""
import asyncio
import logging
import sys
import time
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 加载 .env.local + ~/.intelops-secrets — 确保 MYSQL_DSN / REDIS_URL / 各 API key 可读
try:
    from shared.env_loader import load_all as _load_env_all
    _load_env_all()
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("crawler.main")


def _all_sources():
    """已注册数据源 (key, label, module)；新增源在此加。

    sensor_tower / fb_adlib 已迁移到 market_rank/ 下的 Playwright 脚本（需手动登录），
    不在 async_crawler 自动循环里跑 — 由 dashboard_server SCRIPTS 单独触发。
    """
    # iap_pricing 已从 async_crawler 注销 — Apple HTML 抓法在国内 IP 全被 redirect 到 CN
    # storefront，改用 market_rank/scrape_qimai_iap.py（qimai.cn 周更）
    from async_crawler.sources import (
        appstore_rank, reviews,
        androidrank, reddit, twitter, google_news,
    )
    return [
        ("appstore_rank", "App Store 排名", appstore_rank),
        ("reviews",       "用户评论",       reviews),
        ("androidrank",   "Androidrank",    androidrank),
        ("reddit",        "Reddit 舆情",    reddit),
        ("twitter",       "X (Twitter)",    twitter),
        ("google_news",   "Google 商业新闻", google_news),
    ]


def _parse_sources_arg(argv: list[str]) -> set[str] | None:
    """解析 `--sources a,b,c`，返回 keyset；缺省返回 None 表示跑全部。"""
    for i, a in enumerate(argv):
        if a == "--sources" and i + 1 < len(argv):
            return {s.strip() for s in argv[i + 1].split(",") if s.strip()}
        if a.startswith("--sources="):
            return {s.strip() for s in a.split("=", 1)[1].split(",") if s.strip()}
    return None


async def run_once(only: set[str] | None = None):
    from async_crawler.base import create_ssl_context
    from async_crawler.db import Database

    sources = _all_sources()
    if only is not None:
        sources = [s for s in sources if s[0] in only]
        if not sources:
            log.warning(
                f"--sources={only} 没匹配到任何源；可用：{[s[0] for s in _all_sources()]}"
            )
            return

    db = Database()
    await db.connect()
    t0 = time.monotonic()

    connector = aiohttp.TCPConnector(ssl=create_ssl_context(), limit=20)
    async with aiohttp.ClientSession(connector=connector) as session:
        results = await asyncio.gather(
            *[m.crawl(session, db) for _, _, m in sources],
            return_exceptions=True,
        )

    log.info("=" * 50)
    for (key, label, _), result in zip(sources, results):
        if isinstance(result, Exception):
            log.error(f"  {label} ({key}): 失败 — {result}")
        else:
            log.info(f"  {label} ({key}): {len(result)} 条")
    log.info(f"总耗时: {time.monotonic() - t0:.1f}s")
    await db.close()


def main():
    if "--loop" in sys.argv:
        from async_crawler.scheduler import Scheduler
        asyncio.run(Scheduler().loop())
    else:
        only = _parse_sources_arg(sys.argv[1:])
        asyncio.run(run_once(only=only))


if __name__ == "__main__":
    main()
