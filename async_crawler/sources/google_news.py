"""Google News RSS 商业新闻抓取（参考 score-app-tracker/search.py）。

迁移自 Google CSE API（需 key，限额 100/day）→ Google News RSS（免费、无限）。
**周更**（在 weekly_sync 里跑，每周一 09:00 ± launchd 误差），不再日更。

每个竞品发 2 个 RSS 请求：
  1. broad   ：`"<app>" -site:<own.com> when:7d`         — 大范围捞
  2. business：`"<app>" + (funding OR acquires OR ...)`  — 命中商业关键词，标 ⭐ 排前

Google News 的 source 字段会被用来过滤 social media / 招聘站 / 自家网站。

输出：
  data/async_google_news.json   — async_crawler 标准 shape（aggregator 待接入）
  data/raw/google_news_<DATE>.md — 人类可读 markdown 快照（结构同 score-app-tracker）

配置：config/google_news.json（business_keywords / block_sources / 9 app + per-app exclude_sites）
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_RAW_OUTPUT_DIR = _PROJECT_ROOT / "data" / "raw"
_CONFIG_PATH = _PROJECT_ROOT / "config" / "google_news.json"

ENDPOINT = "https://news.google.com/rss/search"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# ---- 工具 ------------------------------------------------------------------

def _build_query(app_query: str, exclude_sites: list[str], when: str, extra: str = "") -> str:
    """拼出最终的 Google News 检索字符串。"""
    parts = [app_query]
    if extra:
        parts.append(extra)
    for d in exclude_sites or []:
        parts.append(f"-site:{d}")
    parts.append(f"when:{when}")
    return " ".join(parts)


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_pub(pub: str):
    if not pub:
        return None
    try:
        return parsedate_to_datetime(pub)
    except Exception:
        return None


def _parse_items(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[dict] = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        src_el = it.find("source")
        source = src_el.text.strip() if src_el is not None and src_el.text else ""
        desc = _strip_html(it.findtext("description") or "")
        items.append({
            "title": title,
            "link": link,
            "pub": pub,
            "pub_dt": _parse_pub(pub),
            "source": source,
            "desc": desc,
        })
    return items


def _is_blocked(source: str, block_sources: list[str]) -> bool:
    if not source:
        return False
    s = source.lower()
    return any(b.lower() in s for b in block_sources)


def _app_source_aliases(app_name: str) -> list[str]:
    """app 名变体（OneFootball / One Football / onefootball ...）"""
    base = app_name.strip()
    aliases = {base, base.lower(), base.replace(" ", ""), base.replace(" ", "").lower()}
    spaced = re.sub(r"(?<!^)([A-Z])", r" \1", base).strip()
    aliases.add(spaced)
    aliases.add(spaced.lower())
    return [a for a in aliases if a]


def _merge_and_rank(broad: list[dict], biz: list[dict], block_sources: list[str], limit: int) -> list[dict]:
    """合并两组结果：去重 by link → 过滤 block → 标 is_biz → 排序 (biz 优先 → 时间倒序)。"""
    by_link: dict[str, dict] = {}
    biz_links = {it["link"] for it in biz if it["link"]}
    for it in biz + broad:
        if not it["link"] or it["link"] in by_link:
            continue
        if _is_blocked(it["source"], block_sources):
            continue
        it["is_biz"] = it["link"] in biz_links
        by_link[it["link"]] = it
    items = list(by_link.values())
    items.sort(
        key=lambda x: (
            0 if x["is_biz"] else 1,
            -(x["pub_dt"].timestamp() if x["pub_dt"] else 0),
        )
    )
    return items[:limit]


# ---- BaseCrawler ----------------------------------------------------------

class GoogleNewsCrawler(BaseCrawler):
    source_name = "google_news"
    rate_limit = 1.0   # RSS 较快，但留 1s 节流避免 Google 限频

    async def crawl(self, database) -> list[dict]:
        if not _CONFIG_PATH.exists():
            self.log.warning(f"[google_news] config 缺失 {_CONFIG_PATH}，跳过")
            return []

        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        s = cfg.get("settings", {})
        num = int(s.get("num_results", 10))
        when = s.get("when", "7d")
        hl = s.get("hl", "en-US")
        gl = s.get("gl", "US")
        ceid = s.get("ceid", "US:en")
        biz_kw = s.get("business_keywords", "")
        block = s.get("block_sources", [])

        results: list[dict] = []
        all_md_sections: list[str] = []
        today = datetime.now().strftime("%Y-%m-%d")
        all_md_sections.append(f"# Score App Business News — week of {today}\n")
        all_md_sections.append(
            f"_Source: Google News RSS · past {when} · top {num} per app · "
            f"⭐ = matched business keywords · self-published & social sources excluded._\n"
        )

        # 累积要入库的所有条目（DB 写入比 JSON 写入更怕异常 — 走全部循环结束后一次 upsert）
        rows_for_db: list[dict] = []

        for app in cfg.get("apps", []):
            name = app["name"]
            self.log.info(f"[{name}] broad...")
            q_broad = _build_query(app["query"], app.get("exclude_sites", []), when)
            xml_b = await self._fetch_rss(q_broad, hl=hl, gl=gl, ceid=ceid)
            broad_items = _parse_items(xml_b) if xml_b else []

            self.log.info(f"[{name}] biz...")
            q_biz = _build_query(app["query"], app.get("exclude_sites", []), when, extra=biz_kw)
            xml_z = await self._fetch_rss(q_biz, hl=hl, gl=gl, ceid=ceid)
            biz_items = _parse_items(xml_z) if xml_z else []

            # 屏蔽自家 app 名作 source（Google News 偶尔把 app 自家文章 attribute 给 app）
            full_block = list(block) + _app_source_aliases(name)
            merged = _merge_and_rank(broad_items, biz_items, full_block, num)
            biz_count = sum(1 for x in merged if x.get("is_biz"))
            self.log.info(f"[{name}] {len(merged)} kept ({biz_count} ⭐)")

            # 标准 shape — 注意 datetime 不能 JSON 序列化，转 ISO
            normalized = [{
                "title": it["title"],
                "link": it["link"],
                "pub": it["pub"],
                "pub_iso": it["pub_dt"].isoformat() if it["pub_dt"] else None,
                "source": it["source"],
                "desc": it["desc"],
                "is_biz": bool(it.get("is_biz")),
            } for it in merged]

            # 准备入库 — DAO 期望 {title, link, pub_dt(datetime), source, desc, app_name, matched_keyword}
            for it in merged:
                rows_for_db.append({
                    "title": it["title"],
                    "link": it["link"],
                    "pub_dt": it["pub_dt"],   # 已是 datetime（_parse_items 解析过）
                    "source": it["source"],
                    "desc": it["desc"],
                    "app_name": name,
                    "matched_keyword": "biz" if it.get("is_biz") else "broad",
                })

            rec = self.standardize(name, {
                "query_broad": q_broad,
                "query_biz": q_biz,
                "item_count": len(normalized),
                "biz_count": biz_count,
                "items": normalized,
            })
            results.append(rec)
            all_md_sections.append(self._format_md_section(name, merged, biz_count))

        if results:
            await database.save(self.source_name, results)
            self._write_markdown(all_md_sections, today)

        # 入库 — JSON / MD 主路径已保留，DB 失败不影响 JSON / MD 输出（铁律 1 落地：
        # google_news 是抓取队列，不要被下游 DB / AI 拖死）
        if rows_for_db:
            try:
                from shared.dao import news_items as dao_news
                inserted = dao_news.upsert_news_items(rows_for_db)
                self.log.info(f"[google_news] DB upsert {inserted}/{len(rows_for_db)}")
            except Exception as e:
                self.log.warning(f"[google_news] DB upsert failed (JSON/MD 仍可用): {e}")

        return results

    async def _fetch_rss(self, query: str, *, hl: str, gl: str, ceid: str) -> str:
        params = {"q": query, "hl": hl, "gl": gl, "ceid": ceid}
        url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
        try:
            return await self.fetch(url, headers={"User-Agent": UA})
        except Exception as e:
            self.log.warning(f"RSS 请求失败：{e}")
            return ""

    @staticmethod
    def _format_md_section(name: str, items: list[dict], biz_count: int) -> str:
        out = [f"## {name}", f"_{biz_count} hit(s) on business keywords_", ""]
        if not items:
            out.append("_No results in the past week (after filtering)._\n")
            return "\n".join(out)
        for i, it in enumerate(items, 1):
            title = it["title"] or "(no title)"
            flag = " ⭐" if it.get("is_biz") else ""
            line = f"{i}.{flag} [{title}]({it['link']})"
            meta = []
            if it["source"]:
                meta.append(f"`{it['source']}`")
            if it["pub_dt"]:
                meta.append(it["pub_dt"].astimezone(timezone.utc).strftime("%d %b %Y"))
            elif it["pub"]:
                meta.append(it["pub"])
            if meta:
                line += " — " + " · ".join(meta)
            out.append(line)
            if it["desc"]:
                snippet = it["desc"][:240] + ("…" if len(it["desc"]) > 240 else "")
                out.append(f"   > {snippet}")
            out.append("")
        return "\n".join(out)

    def _write_markdown(self, sections: list[str], date_str: str) -> None:
        _RAW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = _RAW_OUTPUT_DIR / f"google_news_{date_str}.md"
        out_path.write_text("\n".join(sections), encoding="utf-8")
        self.log.info(f"markdown 快照已写入 {out_path}")


async def crawl(session, database) -> list[dict]:
    return await GoogleNewsCrawler(session).crawl(database)
