"""Google Play + App Store 用户评论（近 3 天）"""
import asyncio
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import get_comment_competitors
from regions import get_region_codes, load_regions

CUTOFF_DAYS = 3


class ReviewsCrawler(BaseCrawler):
    source_name = "reviews"
    rate_limit = 0.5

    async def _fetch_gp(self, pkg, country):
        from google_play_scraper import reviews, Sort
        cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)
        result, _ = await asyncio.to_thread(
            reviews, pkg, lang="en", country=country, sort=Sort.NEWEST, count=200
        )
        rows = []
        for r in result:
            at = r["at"].replace(tzinfo=timezone.utc) if r["at"].tzinfo is None else r["at"]
            if at >= cutoff:
                rows.append({"score": r["score"], "version": r.get("appVersion", ""), "content": r["content"], "platform": "gp"})
        return rows

    async def _fetch_ios(self, app_id, country):
        rows, page = [], 1
        while len(rows) < 200 and page <= 10:
            url = f"https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"
            try:
                data = await self.fetch_json(url)
            except Exception:
                break
            entries = data.get("feed", {}).get("entry", [])
            if isinstance(entries, dict):
                entries = [entries]
            if not entries:
                break
            start = 1 if entries and isinstance(entries[0], dict) and "im:name" in entries[0] else 0
            for e in entries[start:]:
                rows.append({
                    "score": int(e.get("im:rating", {}).get("label", 5)),
                    "version": e.get("im:version", {}).get("label", ""),
                    "content": e.get("content", {}).get("label", ""),
                    "platform": "ios",
                })
            page += 1
        return rows

    async def crawl(self, database) -> list[dict]:
        competitors = get_comment_competitors()
        regions = get_region_codes()
        results = []
        for app_name, comp in competitors.items():
            for region in regions:
                self.log.info(f"[{app_name}/{region}] 抓取评论...")
                gp_rows = await self._fetch_gp(comp["gp"], region)
                ios_rows = await self._fetch_ios(comp["ios"], region)
                all_rows = gp_rows + ios_rows
                rec = self.standardize(app_name, {
                    "count": len(all_rows),
                    "negative_count": sum(1 for r in all_rows if r["score"] <= 3),
                    "reviews": all_rows,
                }, region=region)
                results.append(rec)
        self.log.info(f"评论: {len(results)} 条记录")
        await db.save(self.source_name, results)
        return results


async def crawl(session, database) -> list[dict]:
    return await ReviewsCrawler(session).crawl(database)
