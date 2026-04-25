"""Reddit 社区舆情"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import get_comment_competitors


class RedditCrawler(BaseCrawler):
    source_name = "reddit"
    rate_limit = 2.0

    async def crawl(self, database) -> list[dict]:
        competitors = get_comment_competitors()
        results = []
        for app_name in competitors:
            url = f"https://www.reddit.com/search.json?q={app_name}+app&sort=new&limit=25&t=month"
            self.log.info(f"[{app_name}] Reddit...")
            try:
                data = await self.fetch_json(url, headers={
                    "User-Agent": "FootballIntelBot/1.0 (competitive analysis)"
                })
                posts = data.get("data", {}).get("children", [])
                mentions = []
                for p in posts:
                    d = p.get("data", {})
                    mentions.append({
                        "title": d.get("title", ""),
                        "subreddit": d.get("subreddit", ""),
                        "score": d.get("score", 0),
                        "upvote_ratio": d.get("upvote_ratio", 0),
                        "num_comments": d.get("num_comments", 0),
                        "created_utc": d.get("created_utc", 0),
                    })
                rec = self.standardize(app_name, {
                    "mention_count": len(mentions),
                    "mentions": mentions,
                })
                results.append(rec)
            except Exception as e:
                self.log.error(f"[{app_name}] Reddit 失败: {e}")
                results.append(self.standardize(app_name, {"error": str(e)}))
        self.log.info(f"Reddit: {len(results)} 条")
        await db.save(self.source_name, results)
        return results


async def crawl(session, database) -> list[dict]:
    return await RedditCrawler(session).crawl(database)
