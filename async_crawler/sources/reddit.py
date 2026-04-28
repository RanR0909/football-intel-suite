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
from shared.dao import community as dao_community


_RAW_OUTPUT = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "reddit_posts.json"


class RedditCrawler(BaseCrawler):
    source_name = "reddit"
    rate_limit = 2.0

    POST_LIMIT = 30                 # 50 → 30
    COMMENT_TOP_N = 20
    POST_SELFTEXT_MAX = 2000
    COMMENT_BODY_MAX = 1000
    # 用引号包裹精确短语匹配（避免 "365Scores" 被分词为 score+足球新闻噪声）
    # %22 = URL-encoded "；保持 1 个模板减少调用次数
    KEYWORD_TEMPLATES = ['%22{name}%22']
    SEARCH_TIME_FILTER = "month"   # hour / day / week / month / year / all
    # Reddit sort=new 会跳过 quoted-phrase 匹配 → 用 relevance 抓全后再按时间重排
    SEARCH_SORT = "relevance"
    # post-filter：抓回来再确认 title+selftext 真含关键词（兜底假阳性）
    POSTFILTER_REQUIRE_KEYWORD = True
    UA = "FootballIntelBot/1.0 (competitive analysis)"
    # 是否对每条帖子单独 fetch 评论（默认关，开启会让总调用 × 30）
    # 通过 env 变量 REDDIT_FETCH_COMMENTS=1 启用
    FETCH_COMMENTS = (os.environ.get("REDDIT_FETCH_COMMENTS", "0") == "1")

    async def crawl(self, database) -> list[dict]:
        competitors = get_comment_competitors()
        results: list[dict] = []
        total_db = 0
        for app_name in competitors:
            posts = await self._crawl_competitor(app_name)
            rec = self.standardize(app_name, {
                "competitor": app_name,
                "posts": posts,
            })
            results.append(rec)
            # 双写 MySQL
            if posts:
                total_db += dao_community.upsert_community_posts(app_name, "reddit", posts)

        if results:
            await database.save(self.source_name, results)
            self._write_raw_snapshot(results)
        total_posts = sum(len(r['data'].get('posts', [])) for r in results)
        self.log.info(f"reddit: 抓取 {len(results)} 个竞品，共 {total_posts} 条帖子；MySQL upsert {total_db} 条")
        return results

    async def _crawl_competitor(self, app_name: str) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        # 关键词小写形式用于 post-filter 比对
        name_lc = app_name.lower()
        for tpl in self.KEYWORD_TEMPLATES:
            kw = tpl.format(name=app_name)
            url = (
                "https://www.reddit.com/search.json"
                f"?q={kw.replace(' ', '+')}"
                f"&sort={self.SEARCH_SORT}&limit={self.POST_LIMIT}&t={self.SEARCH_TIME_FILTER}"
            )
            self.log.info(f"[{app_name}/{kw}] {url}")
            try:
                data = await self.fetch_json(url, headers={"User-Agent": self.UA})
            except Exception as e:
                self.log.error(f"[{app_name}/{kw}] 搜索失败: {e}")
                continue

            dropped = 0
            for child in (data.get("data") or {}).get("children") or []:
                d = child.get("data") or {}
                pid = d.get("id")
                if not pid or pid in seen:
                    continue

                title = (d.get("title") or "")[:500]
                selftext = (d.get("selftext") or "")[:self.POST_SELFTEXT_MAX]

                # post-filter 兜底：title + selftext 任一含关键词才保留
                if self.POSTFILTER_REQUIRE_KEYWORD:
                    haystack = (title + " " + selftext).lower()
                    if name_lc not in haystack:
                        dropped += 1
                        continue

                seen.add(pid)
                subreddit = d.get("subreddit") or ""
                permalink = d.get("permalink") or ""
                comments = await self._fetch_comments(subreddit, pid) if self.FETCH_COMMENTS else []

                out.append({
                    "post_id": pid,
                    "keyword": kw,
                    "subreddit": subreddit,
                    "title": title,
                    "selftext": selftext,
                    "url": f"https://www.reddit.com{permalink}" if permalink else d.get("url", ""),
                    "score": int(d.get("score") or 0),
                    "num_comments": int(d.get("num_comments") or 0),
                    "upvote_ratio": float(d.get("upvote_ratio") or 0),
                    "created_utc": float(d.get("created_utc") or 0),
                    "comments": comments,
                })
            if dropped:
                self.log.info(f"[{app_name}/{kw}] post-filter 丢弃 {dropped} 条假阳性")

        # 按 created_utc 降序（API 用了 relevance，这里恢复时序）
        out.sort(key=lambda p: p.get("created_utc") or 0, reverse=True)
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
