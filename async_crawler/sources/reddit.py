"""Reddit 社区舆情抓取器。

继承 BaseCrawler，覆写 crawl()。
- 多关键词模板（`{name} app` / `{name} review` / `{name}`）
- 抓帖子 + Top N 评论
- post_id 去重（跨 keyword 不重复）
- 双重持久化：
  - db.save() → data/async_reddit.json + MongoDB（与 BaseCrawler 架构一致）
  - 额外写 data/raw/reddit_posts.json（社媒舆情模块 / aggregator 唯一入口）

下游：
- data_pipeline/aggregator._fill_community 按 created_utc 时间窗合并
- community_insights/ai_analyzer 按竞品 + 时间窗筛选送 Claude
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import get_comment_competitors


_RAW_OUTPUT = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "reddit_posts.json"


class RedditCrawler(BaseCrawler):
    source_name = "reddit"
    rate_limit = 2.0

    POST_LIMIT = 30                 # 50 → 30
    COMMENT_TOP_N = 20
    POST_SELFTEXT_MAX = 2000
    COMMENT_BODY_MAX = 1000
    # 默认只用 1 个关键词模板，把每竞品的搜索调用从 3 减到 1
    KEYWORD_TEMPLATES = ["{name}"]
    SEARCH_TIME_FILTER = "month"   # hour / day / week / month / year / all
    UA = "FootballIntelBot/1.0 (competitive analysis)"
    # 是否对每条帖子单独 fetch 评论（默认关，开启会让总调用 × 30）
    # 通过 env 变量 REDDIT_FETCH_COMMENTS=1 启用
    FETCH_COMMENTS = (os.environ.get("REDDIT_FETCH_COMMENTS", "0") == "1")

    async def crawl(self, database) -> list[dict]:
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
        self.log.info(f"reddit: 抓取 {len(results)} 个竞品，共 {sum(len(r['data'].get('posts', [])) for r in results)} 条帖子")
        return results

    async def _crawl_competitor(self, app_name: str) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        for tpl in self.KEYWORD_TEMPLATES:
            kw = tpl.format(name=app_name)
            url = (
                "https://www.reddit.com/search.json"
                f"?q={kw.replace(' ', '+')}"
                f"&sort=new&limit={self.POST_LIMIT}&t={self.SEARCH_TIME_FILTER}"
            )
            self.log.info(f"[{app_name}/{kw}] {url}")
            try:
                data = await self.fetch_json(url, headers={"User-Agent": self.UA})
            except Exception as e:
                self.log.error(f"[{app_name}/{kw}] 搜索失败: {e}")
                continue

            for child in (data.get("data") or {}).get("children") or []:
                d = child.get("data") or {}
                pid = d.get("id")
                if not pid or pid in seen:
                    continue
                seen.add(pid)

                subreddit = d.get("subreddit") or ""
                permalink = d.get("permalink") or ""
                # 默认跳过 per-post 评论抓取（避免 30 帖 × 6 竞品 = 180 + 调用），
                # 需要时设 env REDDIT_FETCH_COMMENTS=1
                comments = await self._fetch_comments(subreddit, pid) if self.FETCH_COMMENTS else []

                out.append({
                    "post_id": pid,
                    "keyword": kw,
                    "subreddit": subreddit,
                    "title": (d.get("title") or "")[:500],
                    "selftext": (d.get("selftext") or "")[:self.POST_SELFTEXT_MAX],
                    "url": f"https://www.reddit.com{permalink}" if permalink else d.get("url", ""),
                    "score": int(d.get("score") or 0),
                    "num_comments": int(d.get("num_comments") or 0),
                    "upvote_ratio": float(d.get("upvote_ratio") or 0),
                    "created_utc": float(d.get("created_utc") or 0),
                    "comments": comments,
                })
        return out

    async def _fetch_comments(self, subreddit: str, post_id: str) -> list[dict]:
        if not subreddit or not post_id:
            return []
        url = (
            f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json"
            f"?limit={self.COMMENT_TOP_N}&sort=top"
        )
        try:
            data = await self.fetch_json(url, headers={"User-Agent": self.UA})
        except Exception as e:
            self.log.warning(f"[{post_id}] 评论抓取失败（跳过）: {e}")
            return []
        if not isinstance(data, list) or len(data) < 2:
            return []
        out: list[dict] = []
        for c in (data[1].get("data") or {}).get("children") or []:
            cd = c.get("data") or {}
            body = (cd.get("body") or "").strip()
            if not body:
                continue
            out.append({
                "body": body[:self.COMMENT_BODY_MAX],
                "score": int(cd.get("score") or 0),
                "created_utc": float(cd.get("created_utc") or 0),
            })
            if len(out) >= self.COMMENT_TOP_N:
                break
        return out

    def _write_raw_snapshot(self, results: list[dict]):
        """合并写入 data/raw/reddit_posts.json，按 (source, competitor) 覆盖。"""
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
    return await RedditCrawler(session).crawl(database)
