"""X (Twitter) 社媒舆情抓取器。

使用 X API v2 search/recent 端点。读取环境变量 X_BEARER_TOKEN（OAuth 2.0 Bearer Token）。
未配置 token 时整体跳过，不影响其他爬虫运行。

下游：
- data/raw/twitter_posts.json — 与 reddit_posts.json 同结构，aggregator 多源融合
- data_pipeline.aggregator._fill_community 自动按 _platform 字段拆 platform_breakdown
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import get_comment_competitors


_RAW_OUTPUT = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "twitter_posts.json"

X_API_BASE = "https://api.twitter.com/2/tweets/search/recent"
X_TWEET_FIELDS = "created_at,public_metrics,author_id,lang"
X_USER_FIELDS = "username"


class TwitterCrawler(BaseCrawler):
    source_name = "twitter"
    rate_limit = 1.0                          # X API v2 严格速率
    max_retries = 2

    SEARCH_TWEETS_PER_COMP = 100              # X free tier 月配额有限，按 month 控量
    KEYWORD_TEMPLATES = ["{name}", "@{name}", "{name} app"]
    DEFAULT_LANG_FILTER = ["en", "es", "pt"]   # 限定主流英语 / 西语 / 葡语，过滤噪声

    @property
    def _bearer_token(self) -> str:
        return os.environ.get("X_BEARER_TOKEN", "").strip()

    async def crawl(self, database) -> list[dict]:
        if not self._bearer_token:
            self.log.warning("X_BEARER_TOKEN 未配置，跳过 Twitter 抓取")
            return []

        competitors = get_comment_competitors()
        results: list[dict] = []
        for app_name in competitors:
            posts = await self._crawl_competitor(app_name)
            rec = self.standardize(app_name, {
                "competitor": app_name,
                "posts": posts,
            })
            results.append(rec)

        if results:
            await database.save(self.source_name, results)
            self._write_raw_snapshot(results)
        self.log.info(
            f"twitter: 抓取 {len(results)} 个竞品，共 "
            f"{sum(len(r['data'].get('posts', [])) for r in results)} 条推文"
        )
        return results

    async def _crawl_competitor(self, app_name: str) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        # X API v2 single query：组合多个 keyword + 排除转推
        # 例：("SofaScore" OR @SofaScore OR "SofaScore app") -is:retweet lang:en
        terms = " OR ".join('"' + t.format(name=app_name) + '"' for t in self.KEYWORD_TEMPLATES)
        lang_filter = " OR ".join("lang:" + lg for lg in self.DEFAULT_LANG_FILTER)
        query = f"({terms}) -is:retweet ({lang_filter})"
        url = (
            f"{X_API_BASE}?query={quote(query)}"
            f"&max_results={self.SEARCH_TWEETS_PER_COMP}"
            f"&tweet.fields={X_TWEET_FIELDS}"
            f"&expansions=author_id&user.fields={X_USER_FIELDS}"
        )

        try:
            data = await self.fetch_json(url, headers={
                "Authorization": "Bearer " + self._bearer_token,
                "User-Agent": "FootballIntelBot/1.0",
            })
        except Exception as e:
            self.log.error(f"[{app_name}] X 搜索失败: {e}")
            return []

        # X 响应结构：{data: [tweets], includes: {users: [...]}}
        tweets = data.get("data") or []
        users_by_id = {u["id"]: u for u in (data.get("includes", {}) or {}).get("users", [])}

        for t in tweets:
            tid = t.get("id")
            if not tid or tid in seen:
                continue
            seen.add(tid)

            author_obj = users_by_id.get(t.get("author_id")) or {}
            metrics = t.get("public_metrics", {}) or {}
            created_at_str = t.get("created_at") or ""
            try:
                created_utc = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")).timestamp() if created_at_str else 0
            except ValueError:
                created_utc = 0

            out.append({
                "post_id": tid,
                "platform": "twitter",
                "author": author_obj.get("username", ""),
                "subreddit": None,                                  # X 无 sub-channel 概念
                "title": "",                                         # X 没有 title，仅 text
                "selftext": "",                                      # 兼容 schema
                "text": (t.get("text") or "")[:1000],                # 主文本
                "url": (
                    f"https://twitter.com/{author_obj.get('username')}/status/{tid}"
                    if author_obj.get("username") else None
                ),
                "score": int(metrics.get("like_count", 0) or 0),
                "num_comments": int(metrics.get("reply_count", 0) or 0),
                "shares_count": int(metrics.get("retweet_count", 0) or 0),
                "upvote_ratio": None,
                "created_utc": created_utc,
                "lang": t.get("lang"),
                "comments": [],
            })
        return out

    def _write_raw_snapshot(self, results: list[dict]):
        """合并写入 data/raw/twitter_posts.json，按 (source, competitor) 覆盖。"""
        _RAW_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, dict] = {}
        if _RAW_OUTPUT.exists():
            try:
                payload = json.loads(_RAW_OUTPUT.read_text(encoding="utf-8"))
                for rec in payload if isinstance(payload, list) else []:
                    key = f"{rec.get('source')}_{rec.get('competitor')}"
                    existing[key] = rec
            except Exception:
                existing = {}
        for rec in results:
            existing[f"{rec.get('source')}_{rec.get('competitor')}"] = rec
        _RAW_OUTPUT.write_text(
            json.dumps(list(existing.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.log.info(f"raw snapshot 已写入 {_RAW_OUTPUT}")


async def crawl(session, database) -> list[dict]:
    return await TwitterCrawler(session).crawl(database)
