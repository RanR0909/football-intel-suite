"""X (Twitter) 社媒舆情抓取器 — 经 fapi.uk / utools 转发（取代官方 X API v2）。

背景
----
X 官方 API v2 的 free tier 配额已不足以支撑 9 竞品 × 多关键词的扫描，
改走第三方 fapi.uk（utools）服务。该服务通过用户自带 Twitter cookie
（auth_token）模拟登录抓取，**违反 X ToS，存在账号封禁风险**：

  ⚠️  强烈建议使用一次性"小号"的 auth_token，**不要用主号 / 工作号**。
  ⚠️  cookie 通常 30 天内失效，需要定期更新。
  ⚠️  若服务返回 401 / 风控错误，本爬虫会静默跳过并触发飞书告警。

环境变量
--------
- ``UTOOLS_AUTH_TOKEN`` — 必填，X 网页 cookie 中 ``auth_token`` 的值。
  获取：浏览器登录 X → DevTools → Application → Cookies → 复制 ``auth_token``。
  未配置时整体跳过，不影响其他爬虫。

下游
----
- ``data/raw/twitter_posts.json``         — 与 reddit_posts.json 同结构
- ``community_posts`` (MySQL) via dao_community
- aggregator._fill_community 自动按 platform 字段拆 platform_breakdown
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from competitors import get_comment_competitors
from shared.dao import community as dao_community

try:
    from shared import feishu_notify  # 可选；缺失时不影响核心流程
except Exception:  # pragma: no cover
    feishu_notify = None  # type: ignore


_RAW_OUTPUT = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "twitter_posts.json"

FAPI_ENDPOINT = "https://fapi.uk/api/base/apitools/search"


class TwitterCrawler(BaseCrawler):
    source_name = "twitter"
    rate_limit = 2.0           # 走第三方代理，节流稍宽以降低风控
    max_retries = 2

    POSTS_PER_QUERY = 30       # 单次查询 ≤ 30 条，避免触发风控
    PRODUCT = "Latest"         # Latest = 最新；Top = 热门
    DEFAULT_LANGS = {"en", "es", "pt", "zh", "ja", None, ""}  # 不强制过滤，宽松保留

    @property
    def _auth_token(self) -> str:
        return os.environ.get("UTOOLS_AUTH_TOKEN", "").strip()

    async def crawl(self, database) -> list[dict]:
        token = self._auth_token
        if not token:
            self.log.warning("UTOOLS_AUTH_TOKEN 未配置，跳过 Twitter 抓取")
            return []

        competitors = get_comment_competitors()
        results: list[dict] = []
        total_db = 0
        cookie_dead = False
        debug_dumped = False

        for app_name in competitors:
            posts, status = await self._crawl_competitor(app_name, token, debug=not debug_dumped)
            if status == "auth_failed":
                cookie_dead = True
                self.log.error("auth_token 已失效或被风控，停止后续竞品抓取")
                break
            if status == "schema_unknown":
                debug_dumped = True  # 已打印一次 raw，不再 dump
            rec = self.standardize(app_name, {
                "competitor": app_name,
                "posts": posts,
                "status": status,
            })
            results.append(rec)
            if posts:
                total_db += dao_community.upsert_community_posts(app_name, "twitter", posts)

        if cookie_dead:
            self._notify_cookie_dead()

        if results:
            await database.save(self.source_name, results)
            self._write_raw_snapshot(results)

        total_posts = sum(len(r["data"].get("posts", [])) for r in results)
        self.log.info(
            f"twitter: 抓取 {len(results)} 个竞品，共 {total_posts} 条推文；"
            f"MySQL upsert {total_db} 条"
        )
        return results

    # ---- 单竞品 -------------------------------------------------------------

    async def _crawl_competitor(
        self, app_name: str, token: str, *, debug: bool
    ) -> tuple[list[dict], str]:
        """返回 (posts, status)。status ∈ {ok, empty, auth_failed, schema_unknown, error}"""
        # fapi.uk 用单 words 字段；包双引号锁定 app 名
        words = f'"{app_name}"'
        params = {
            "words": words,
            "count": self.POSTS_PER_QUERY,
            "product": self.PRODUCT,
            "resFormat": "json",
            "apiKey": token,
        }
        url = f"{FAPI_ENDPOINT}?{urlencode(params)}"

        try:
            data = await self.fetch_json(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            })
        except Exception as e:
            msg = str(e).lower()
            if "401" in msg or "403" in msg or "auth" in msg:
                return [], "auth_failed"
            self.log.error(f"[{app_name}] fapi 请求失败: {e}")
            return [], "error"

        # fapi.uk 业务错误约定（实测）：
        #   - code=0 不一定成功；具体看 msg / data 字段
        #   - 鉴权失败时 data="apiKey cannot be empty" / "invalid apiKey"，code 还是 0
        if isinstance(data, dict):
            err_msg = str(data.get("msg") or data.get("message") or "").lower()
            data_field = data.get("data")
            # 业务错误：data 是字符串而不是 list/dict
            if isinstance(data_field, str):
                err_msg = (err_msg + " " + data_field.lower()).strip()
            if any(kw in err_msg for kw in (
                "apikey", "api key", "invalid", "auth", "token", "login",
                "expir", "unauthorized", "forbidden", "exceed", "limit",
            )):
                self.log.error(f"[{app_name}] fapi 鉴权 / 限流错误: {data}")
                # 鉴权类一律按 auth_failed 处理（让上层停抓 + 飞书告警）
                if any(kw in err_msg for kw in ("apikey", "api key", "auth", "token",
                                                "expir", "unauthorized", "invalid")):
                    return [], "auth_failed"
                return [], "error"
            biz_code = data.get("code")
            if biz_code not in (None, 0, 200, "0", "200", "success"):
                self.log.warning(f"[{app_name}] fapi 业务错误 code={biz_code} data={data}")
                return [], "error"

        tweets = self._extract_tweets(data)
        if tweets is None:
            if debug:
                # schema 未知：打印整个 response 便于第一次跑时人工对齐字段
                snippet = json.dumps(data, ensure_ascii=False)[:2000]
                self.log.warning(f"[{app_name}] 无法识别 fapi 响应 schema，原始片段:\n{snippet}")
            return [], "schema_unknown"

        seen: set[str] = set()
        out: list[dict] = []
        for t in tweets:
            normalized = self._normalize_tweet(t)
            if not normalized:
                continue
            tid = normalized["post_id"]
            if not tid or tid in seen:
                continue
            seen.add(tid)
            out.append(normalized)

        return out, ("ok" if out else "empty")

    # ---- 解析 ---------------------------------------------------------------

    @staticmethod
    def _extract_tweets(data) -> list | None:
        """fapi.uk schema 不稳定 — 尝试多种常见路径找推文 list。

        若全部失败返回 None（表示需要 dump raw 给开发者对齐 schema）。
        """
        if not isinstance(data, dict):
            return None
        candidates = [
            data.get("data"),
            data.get("data", {}).get("data") if isinstance(data.get("data"), dict) else None,
            data.get("data", {}).get("tweets") if isinstance(data.get("data"), dict) else None,
            data.get("data", {}).get("list") if isinstance(data.get("data"), dict) else None,
            data.get("tweets"),
            data.get("list"),
            data.get("results"),
        ]
        for c in candidates:
            if isinstance(c, list):
                return c
        return None

    @staticmethod
    def _normalize_tweet(t) -> dict | None:
        """尝试把 fapi 返回的 tweet 对象映射成 community_posts schema。

        fapi.uk 据观察返回的字段名不固定（可能是 X 简化结构，也可能是
        graphql legacy 结构），这里做最大努力的兼容映射。
        """
        if not isinstance(t, dict):
            return None

        legacy = t.get("legacy") if isinstance(t.get("legacy"), dict) else {}

        tid = (
            t.get("id_str") or t.get("id")
            or t.get("rest_id") or t.get("tweet_id")
            or legacy.get("id_str") or ""
        )
        tid = str(tid) if tid else ""
        if not tid:
            return None

        text = (
            t.get("full_text") or t.get("text") or t.get("content")
            or legacy.get("full_text") or legacy.get("text") or ""
        )
        text = (text or "")[:1000]

        # 作者：可能在 user / author / core / 顶层 / legacy
        author = ""
        for blk in (
            t.get("user"),
            t.get("author"),
            (t.get("core") or {}).get("user_results", {}).get("result"),
        ):
            if isinstance(blk, dict):
                author = (
                    blk.get("screen_name")
                    or blk.get("username")
                    or (blk.get("legacy") or {}).get("screen_name")
                    or ""
                )
                if author:
                    break

        # 计数 — 优先 public_metrics，依次 t.* 顶层 / legacy.*
        metrics = t.get("public_metrics") or {}

        def _pick(*names) -> int:
            for src in (metrics, t, legacy):
                for n in names:
                    v = src.get(n)
                    if v:
                        try:
                            return int(v)
                        except (ValueError, TypeError):
                            pass
            return 0

        likes = _pick("like_count", "favorite_count", "favoriteCount")
        replies = _pick("reply_count", "replyCount")
        retweets = _pick("retweet_count", "retweetCount")

        # 时间：created_at 可能是 RFC822 / ISO / 时间戳
        created_raw = (
            t.get("created_at") or t.get("createdAt") or t.get("date")
            or legacy.get("created_at") or ""
        )
        created_utc = 0.0
        if created_raw:
            try:
                if isinstance(created_raw, (int, float)):
                    created_utc = float(created_raw)
                elif "T" in created_raw and ("Z" in created_raw or "+" in created_raw):
                    created_utc = datetime.fromisoformat(
                        created_raw.replace("Z", "+00:00")
                    ).timestamp()
                else:
                    dt = parsedate_to_datetime(created_raw)
                    if dt:
                        created_utc = dt.timestamp()
            except Exception:
                created_utc = 0.0

        url = (
            t.get("url")
            or (f"https://twitter.com/{author}/status/{tid}" if author else None)
        )

        return {
            "post_id": tid,
            "platform": "twitter",
            "author": author or "",
            "subreddit": None,
            "title": "",
            "selftext": "",
            "text": text,
            "url": url,
            "score": likes,
            "num_comments": replies,
            "shares_count": retweets,
            "upvote_ratio": None,
            "created_utc": created_utc,
            "lang": t.get("lang") or legacy.get("lang"),
            "comments": [],
        }

    # ---- 输出 + 告警 --------------------------------------------------------

    def _write_raw_snapshot(self, results: list[dict]):
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

    @staticmethod
    def _notify_cookie_dead():
        if feishu_notify is None:
            return
        try:
            feishu_notify.send_card(
                "🚨 Twitter cookie 失效",
                fields=[
                    {"label": "症状", "value": "fapi.uk 返回 auth 错误，UTOOLS_AUTH_TOKEN 已失效"},
                    {"label": "处理", "value": "重新登录小号 → DevTools 复制 auth_token → 更新 .env.local → 重启 launchd"},
                ],
                color="red",
                footer=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        except Exception:
            pass


async def crawl(session, database) -> list[dict]:
    return await TwitterCrawler(session).crawl(database)
