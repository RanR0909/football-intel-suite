"""App Store 体育类 Top 100 排名"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db


class AppStoreRankCrawler(BaseCrawler):
    source_name = "appstore_rank"
    rate_limit = 1.0

    async def crawl(self, database) -> list[dict]:
        url = "https://itunes.apple.com/us/rss/topfreeapplications/limit=100/genre=6004/json"
        self.log.info("抓取 App Store Top 100 体育类...")
        data = await self.fetch_json(url)
        entries = data.get("feed", {}).get("entry", [])
        results = []
        for i, e in enumerate(entries):
            name = e.get("im:name", {}).get("label", "")
            app_id = e.get("id", {}).get("attributes", {}).get("im:id", "")
            bundle = e.get("id", {}).get("attributes", {}).get("im:bundleId", "")
            results.append(self.standardize(name, {
                "rank": i + 1,
                "app_id": app_id,
                "bundle_id": bundle,
                "category": e.get("category", {}).get("attributes", {}).get("label", ""),
            }))
        self.log.info(f"App Store 排名: {len(results)} 条")
        await db.save(self.source_name, results)
        return results


async def crawl(session, database) -> list[dict]:
    return await AppStoreRankCrawler(session).crawl(database)
