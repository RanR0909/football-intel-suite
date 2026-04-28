"""App Store 体育类 Top 100 排名"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import get_comment_competitors
from shared.dao import rank as dao_rank


def _build_name_to_competitor() -> dict[str, str]:
    """{lower(name): competitor name} —— 把 RSS 返回的应用名映射到 tracked competitor。"""
    out: dict[str, str] = {}
    for name in get_comment_competitors().keys():
        out[name.lower()] = name
    return out


class AppStoreRankCrawler(BaseCrawler):
    source_name = "appstore_rank"
    rate_limit = 1.0

    async def crawl(self, database) -> list[dict]:
        url = "https://itunes.apple.com/us/rss/topfreeapplications/limit=100/genre=6004/json"
        self.log.info("抓取 App Store Top 100 体育类...")
        data = await self.fetch_json(url)
        entries = data.get("feed", {}).get("entry", [])
        name_map = _build_name_to_competitor()
        results = []
        rank_rows = []
        for i, e in enumerate(entries):
            name = e.get("im:name", {}).get("label", "")
            app_id = e.get("id", {}).get("attributes", {}).get("im:id", "")
            bundle = e.get("id", {}).get("attributes", {}).get("im:bundleId", "")
            rank_value = i + 1
            results.append(self.standardize(name, {
                "rank": rank_value,
                "app_id": app_id,
                "bundle_id": bundle,
                "category": e.get("category", {}).get("attributes", {}).get("label", ""),
            }))
            # 试着把 RSS 应用名 fuzzy 匹配到 tracked competitor
            name_lc = (name or "").lower()
            comp_match = None
            for known_lc, known_name in name_map.items():
                if known_lc and known_lc in name_lc:
                    comp_match = known_name
                    break
            rank_rows.append({
                "name": name,
                "competitor": comp_match,
                "region": "us",
                "rank": rank_value,
                "delta": None,
                "downloads": None,
            })
        self.log.info(f"App Store 排名: {len(results)} 条")
        await db.save(self.source_name, results)
        # 双写 MySQL（market_rank_snapshots，source='appstore_rank'）
        n_db = dao_rank.bulk_insert_rank_snapshots("appstore_rank", rank_rows)
        if n_db:
            self.log.info(f"  MySQL: 写入 {n_db} 条 rank_snapshot")
        return results


async def crawl(session, database) -> list[dict]:
    return await AppStoreRankCrawler(session).crawl(database)
