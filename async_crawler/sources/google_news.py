"""Google Custom Search 商业新闻抓取（参考 score-app-tracker/search.py）。

每个竞品一次 query：`"AppName" (funding OR acquisition OR partnership OR launch
OR revenue OR deal OR sponsorship OR investment OR layoffs)`，Google CSE 返回过去
1 周的相关网页，写到：

  data/async_google_news.json     — async_crawler 标准 shape（aggregator 待接入）
  data/raw/google_news_<DATE>.md  — 人类可读的每日 markdown 快照（参考原脚本）

**Key 配置（先留接口，未填时整源跳过不报错）**：
  .env.local 里加：
    GOOGLE_API_KEY=...
    GOOGLE_CSE_ID=...
  申请：https://developers.google.com/custom-search/v1/introduction
       https://programmablesearchengine.google.com/

参数 / 配额：
  Google CSE 免费层 100 query/day，足够覆盖 9 个竞品 × 1 query × 1 次/天。
  date_restrict=w1（过去 1 周），lr=lang_en，gl=us，num=10。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from competitors import get_comment_competitors


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_RAW_OUTPUT_DIR = _PROJECT_ROOT / "data" / "raw"

ENDPOINT = "https://www.googleapis.com/customsearch/v1"

# 商业新闻关键词（对齐 score-app-tracker/config.json）
NEWS_KEYWORDS = (
    "funding OR acquisition OR partnership OR launch OR revenue "
    "OR deal OR sponsorship OR investment OR layoffs"
)

# CSE 参数
NUM_RESULTS = 10
DATE_RESTRICT = "w1"  # 过去 1 周
LR = "lang_en"
GL = "us"
HL = "en"


class GoogleNewsCrawler(BaseCrawler):
    source_name = "google_news"
    rate_limit = 1.5  # CSE 推荐 ≥1s/req

    async def crawl(self, database) -> list[dict]:
        api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
        cse_id = os.environ.get("GOOGLE_CSE_ID", "").strip()
        if not api_key or not cse_id or "PLACEHOLDER" in api_key or "PLACEHOLDER" in cse_id:
            self.log.warning(
                "GOOGLE_API_KEY / GOOGLE_CSE_ID 未配置 → 整源跳过。"
                "在 .env.local 里填好两个 key 即可启用（详见 config/README.md）。"
            )
            return []

        competitors = get_comment_competitors()
        results: list[dict] = []
        for app_name in competitors:
            query = f'"{app_name}" ({NEWS_KEYWORDS})'
            self.log.info(f"[{app_name}] CSE → {query}")
            try:
                data = await self._search(query, api_key, cse_id)
            except Exception as e:
                self.log.error(f"[{app_name}] 搜索失败: {e}")
                data = {"error": str(e), "items": []}
            items = self._normalize_items(data)
            rec = self.standardize(app_name, {
                "query": query,
                "item_count": len(items),
                "items": items,
                "error": data.get("error") if isinstance(data, dict) else None,
            })
            results.append(rec)

        if results:
            await database.save(self.source_name, results)
            self._write_markdown_snapshot(results)
        total_items = sum(len(r["data"].get("items", [])) for r in results)
        self.log.info(f"google_news: {len(results)} 个竞品，共 {total_items} 条新闻")
        return results

    async def _search(self, query: str, api_key: str, cse_id: str) -> dict:
        params = {
            "key": api_key,
            "cx": cse_id,
            "q": query,
            "num": NUM_RESULTS,
            "dateRestrict": DATE_RESTRICT,
            "lr": LR,
            "gl": GL,
            "hl": HL,
            "safe": "off",
        }
        url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
        return await self.fetch_json(url)

    @staticmethod
    def _normalize_items(data) -> list[dict]:
        if not isinstance(data, dict):
            return []
        out: list[dict] = []
        for it in (data.get("items") or []):
            out.append({
                "title": (it.get("title") or "").strip(),
                "link": it.get("link") or "",
                "snippet": (it.get("snippet") or "").replace("\n", " ").strip(),
                "source": it.get("displayLink") or "",
            })
        return out

    def _write_markdown_snapshot(self, results: list[dict]) -> None:
        """每日一份人类可读 markdown（不是必须，但便于离线复盘）。"""
        _RAW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = _RAW_OUTPUT_DIR / f"google_news_{today}.md"
        lines = [f"# Score App Business News — {today}", ""]
        lines.append(f"_Past {DATE_RESTRICT}, top {NUM_RESULTS} per app, sorted by Google relevance._")
        lines.append("")
        for rec in results:
            comp = rec.get("competitor") or ""
            data = rec.get("data") or {}
            items = data.get("items") or []
            lines.append(f"## {comp}\n")
            if data.get("error"):
                lines.append(f"_Error: {data['error']}_\n")
                continue
            if not items:
                lines.append("_No results in the past week._\n")
                continue
            for i, it in enumerate(items, 1):
                title = it.get("title") or "(no title)"
                link = it.get("link") or ""
                snippet = it.get("snippet") or ""
                src = it.get("source") or ""
                lines.append(f"{i}. [{title}]({link}) — `{src}`")
                if snippet:
                    lines.append(f"   > {snippet}")
                lines.append("")
        out_path.write_text("\n".join(lines), encoding="utf-8")
        self.log.info(f"markdown 快照已写入 {out_path}")


async def crawl(session, database) -> list[dict]:
    return await GoogleNewsCrawler(session).crawl(database)
