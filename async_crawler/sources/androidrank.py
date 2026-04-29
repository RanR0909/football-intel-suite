"""Androidrank 历史增长数据"""
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import get_comment_competitors
from shared.dao import rank as dao_rank

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
        db_rows = []
        for app_name, comp in competitors.items():
            pkg = comp["gp"]
            slug = SLUG_MAP.get(pkg, pkg)
            url = f"https://www.androidrank.org/application/{slug}"
            self.log.info(f"[{app_name}] Androidrank...")
            try:
                html = await self.fetch(url)
                # 新版 androidrank：drawChartRankTotalData = [["date1", N1], ["date2", N2], ...]
                # 旧 regex `data: [...]` 已失效（2026-04 验证）
                dl_match = re.search(r'drawChartRankTotalData\s*=\s*\[(.*?)\];', html, re.DOTALL)
                rt_match = re.search(r'drawChartRatingTotalData\s*=\s*\[(.*?)\];', html, re.DOTALL)
                dl_pairs = re.findall(r'\[\s*"([^"]+)"\s*,\s*(\d+)\s*\]', dl_match.group(1)) if dl_match else []
                rt_pairs = re.findall(r'\[\s*"([^"]+)"\s*,\s*([\d.]+)\s*\]', rt_match.group(1)) if rt_match else []
                rec = self.standardize(app_name, {
                    "download_history": [{"date": d, "value": int(n)} for d, n in dl_pairs[-10:]],
                    "rating_history": [{"date": d, "value": float(v)} for d, v in rt_pairs[-10:]],
                })
                results.append(rec)
                # 取最新一个累计下载量写入 MySQL
                if dl_pairs:
                    latest_dl = int(dl_pairs[-1][1])
                    db_rows.append({
                        "name": app_name,
                        "competitor": app_name,
                        "region": None,    # androidrank 是全球累计
                        "rank": None,
                        "delta": None,
                        "downloads": str(latest_dl),
                        "downloads_num": latest_dl,
                        "revenue_num": None,
                    })
            except Exception as e:
                self.log.error(f"[{app_name}] Androidrank 失败: {e}")
                results.append(self.standardize(app_name, {"error": str(e)}))
        self.log.info(f"Androidrank: {len(results)} 条")
        await db.save(self.source_name, results)
        # 双写 MySQL
        if db_rows:
            n_db = dao_rank.bulk_insert_rank_snapshots("androidrank", db_rows)
            if n_db:
                self.log.info(f"  MySQL: 写入 {n_db} 条 cumulative downloads")
        return results


async def crawl(session, database) -> list[dict]:
    return await AndroidrankCrawler(session).crawl(database)
