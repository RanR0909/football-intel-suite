"""Androidrank 历史增长数据"""
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import get_comment_competitors

SLUG_MAP = {
    "com.sofascore.results": "sofascore-live-score-football/com.sofascore.results",
    "com.flashscore.app": "flashscore-live-scores/com.flashscore.app",
    "com.onefootball.onefootball.google": "onefootball-soccer-scores/com.onefootball.onefootball.google",
    "com.scores365.android": "365scores-live-scores-news/com.scores365.android",
    "com.fotmob.fotmob": "fotmob-soccer-live-scores/com.fotmob.fotmob",
    "com.livescore.livescores": "livescore-live-sports-scores/com.livescore.livescores",
}


class AndroidrankCrawler(BaseCrawler):
    source_name = "androidrank"
    rate_limit = 2.0

    async def crawl(self, database) -> list[dict]:
        competitors = get_comment_competitors()
        results = []
        for app_name, comp in competitors.items():
            pkg = comp["gp"]
            slug = SLUG_MAP.get(pkg, pkg)
            url = f"https://www.androidrank.org/application/{slug}"
            self.log.info(f"[{app_name}] Androidrank...")
            try:
                html = await self.fetch(url)
                downloads = re.findall(r'data:\s*\[([\d,\s]+)\]', html)
                ratings = re.findall(r'Rating History.*?data:\s*\[([\d.,\s]+)\]', html, re.DOTALL)
                rec = self.standardize(app_name, {
                    "download_history": downloads[0].split(",")[:10] if downloads else [],
                    "rating_history": ratings[0].split(",")[:10] if ratings else [],
                })
                results.append(rec)
            except Exception as e:
                self.log.error(f"[{app_name}] Androidrank 失败: {e}")
                results.append(self.standardize(app_name, {"error": str(e)}))
        self.log.info(f"Androidrank: {len(results)} 条")
        await db.save(self.source_name, results)
        return results


async def crawl(session, database) -> list[dict]:
    return await AndroidrankCrawler(session).crawl(database)
