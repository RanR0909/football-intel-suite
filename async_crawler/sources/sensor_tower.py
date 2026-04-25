"""Sensor Tower 市场数据"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import get_comment_competitors


class SensorTowerCrawler(BaseCrawler):
    source_name = "sensor_tower"
    rate_limit = 1.5

    async def crawl(self, database) -> list[dict]:
        competitors = get_comment_competitors()
        results = []
        for app_name, comp in competitors.items():
            pkg = comp["gp"]
            url = f"https://app.sensortower.com/api/android/apps/{pkg}?country=US"
            self.log.info(f"[{app_name}] Sensor Tower...")
            try:
                data = await self.fetch_json(url)
                rec = self.standardize(app_name, {
                    "downloads": data.get("worldwide_last_month_downloads", {}).get("units"),
                    "revenue": data.get("worldwide_last_month_revenue", {}).get("revenue"),
                    "rating": data.get("rating"),
                    "ratings_count": data.get("ratings_count"),
                })
                results.append(rec)
            except Exception as e:
                self.log.error(f"[{app_name}] Sensor Tower 失败: {e}")
                results.append(self.standardize(app_name, {"error": str(e)}))
        self.log.info(f"Sensor Tower: {len(results)} 条")
        await db.save(self.source_name, results)
        return results


async def crawl(session, database) -> list[dict]:
    return await SensorTowerCrawler(session).crawl(database)
