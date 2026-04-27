"""Meta Ad Library 抓取器。

策略（按优先级）：
  1) 如配置 META_AD_LIBRARY_TOKEN（或 FB_ACCESS_TOKEN）→ 走官方 Graph API，
     稳定可靠，配额 200 calls/h（开发者 App 的默认限）
     文档：https://www.facebook.com/ads/library/api/
  2) 否则退化到 HTML 抓取 — 容易遭 403 'Client challenge' 反爬，
     成功率 < 30%，仅用作 fallback
  3) 任何错误都记 warning 但不抛，避免影响其他抓取源

获取 token：
  - 进 https://developers.facebook.com/apps/ → 创建 App
  - App 设置 → Add Use Case → Ad Library
  - Tools → Graph API Explorer → 选 App → Get User Access Token →
    勾选 ads_read → 生成长效 token
  - 在 .env.local 加：META_AD_LIBRARY_TOKEN=EAAxxx
"""
import asyncio
import json
import os
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import get_comment_competitors

AD_COUNTRIES = ["US", "GB", "BR"]

# 官方 Graph API（优先）
META_TOKEN = os.environ.get("META_AD_LIBRARY_TOKEN") or os.environ.get("FB_ACCESS_TOKEN", "")
META_API_VERSION = "v19.0"
META_API_BASE = f"https://graph.facebook.com/{META_API_VERSION}/ads_archive"
META_API_FIELDS = (
    "id,ad_creative_bodies,ad_creative_link_titles,ad_creative_link_descriptions,"
    "ad_delivery_start_time,ad_delivery_stop_time,publisher_platforms,page_name,"
    "ad_snapshot_url,impressions,spend"
)

# HTML 抓取（fallback，受反爬限制）
# 多套 UA 轮换，降低识别概率
UA_POOL = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


def _html_headers():
    return {
        "User-Agent": random.choice(UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": '"Not A(Brand";v="99", "Google Chrome";v="120", "Chromium";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }


class FBAdLibCrawler(BaseCrawler):
    source_name = "fb_adlib"
    rate_limit = 3.0
    max_retries = 2

    async def _search_ads_via_api(self, keyword, country):
        """官方 Graph API 路径（有 token 时优先）。"""
        params_qs = (
            f"search_terms={keyword}"
            f"&ad_reached_countries=[\"{country}\"]"
            f"&ad_active_status=ACTIVE"
            f"&ad_type=ALL"
            f"&fields={META_API_FIELDS}"
            f"&limit=50"
            f"&access_token={META_TOKEN}"
        )
        url = f"{META_API_BASE}?{params_qs}"
        try:
            data = await self.fetch_json(url)
        except Exception as e:
            self.log.warning(f"[{keyword}/{country}] Graph API 失败: {e} — 退化 HTML 抓取")
            return None
        ads = []
        for item in (data.get("data") or []):
            bodies = item.get("ad_creative_bodies") or []
            ads.append({
                "ad_id": item.get("id", ""),
                "text": (bodies[0] if bodies else "")[:500],
                "start_date": item.get("ad_delivery_start_time", "")[:10],
                "stop_date":  item.get("ad_delivery_stop_time", "")[:10] if item.get("ad_delivery_stop_time") else "",
                "country": country,
                "platform": item.get("publisher_platforms") or [],
                "media_url": item.get("ad_snapshot_url", ""),
                "page_name": item.get("page_name", ""),
                "source": "graph_api",
            })
        return ads

    async def _search_ads(self, keyword, country):
        """主入口：先试 Graph API，失败 / 无 token 时 fallback HTML 抓取。"""
        # 路径 1：Graph API（有 token）
        if META_TOKEN:
            api_ads = await self._search_ads_via_api(keyword, country)
            if api_ads is not None:
                return api_ads
        # 路径 2：HTML 抓取（容易 403，作 fallback）
        url = (
            f"https://www.facebook.com/ads/library/"
            f"?active_status=active&ad_type=all&country={country}"
            f"&q={keyword}&search_type=keyword_unordered"
        )
        ads = []
        try:
            html = await self.fetch(url, headers=_html_headers())
            # 尝试从页面内嵌 JSON 提取广告数据
            # Facebook 将广告数据嵌入 <script> 标签中
            json_blocks = []
            for marker in ['"ads":', '"adCards":', '"results":']:
                idx = html.find(marker)
                if idx == -1:
                    continue
                # 向前找到 { 起始
                start = html.rfind("{", max(0, idx - 500), idx)
                if start == -1:
                    continue
                depth, i = 0, start
                while i < len(html):
                    if html[i] == "{": depth += 1
                    elif html[i] == "}": depth -= 1
                    if depth == 0:
                        json_blocks.append(html[start:i+1])
                        break
                    i += 1

            for block in json_blocks:
                try:
                    obj = json.loads(block)
                    self._extract_ads(obj, ads, keyword, country)
                except json.JSONDecodeError:
                    continue

            # 备用：正则提取广告 ID 和文案片段
            if not ads:
                import re
                ad_ids = re.findall(r'"adArchiveID"\s*:\s*"(\d+)"', html)
                ad_texts = re.findall(r'"bodyText"\s*:\s*"([^"]{10,500})"', html)
                for i, aid in enumerate(ad_ids[:20]):
                    ads.append({
                        "ad_id": aid,
                        "text": ad_texts[i] if i < len(ad_texts) else "",
                        "start_date": "",
                        "country": country,
                        "platform": [],
                        "media_url": "",
                    })
        except Exception as e:
            self.log.warning(f"[{keyword}/{country}] Ad Library 请求失败: {e}")
        return ads

    def _extract_ads(self, obj, ads, keyword, country):
        """递归提取广告数据"""
        if isinstance(obj, dict):
            if "adArchiveID" in obj or "ad_id" in obj:
                ads.append({
                    "ad_id": obj.get("adArchiveID") or obj.get("ad_id", ""),
                    "text": obj.get("bodyText") or obj.get("body", {}).get("text", ""),
                    "start_date": obj.get("startDate") or obj.get("start_date", ""),
                    "country": country,
                    "platform": obj.get("publisherPlatform", []),
                    "media_url": obj.get("snapshot", {}).get("images", [{}])[0].get("url", "") if isinstance(obj.get("snapshot"), dict) else "",
                })
                return
            for v in obj.values():
                self._extract_ads(v, ads, keyword, country)
        elif isinstance(obj, list):
            for item in obj:
                self._extract_ads(item, ads, keyword, country)

    async def crawl(self, database) -> list[dict]:
        competitors = get_comment_competitors()
        if META_TOKEN:
            self.log.info(f"Ad Library: 走 Graph API（token: {META_TOKEN[:10]}...）")
        else:
            self.log.warning(
                "Ad Library: 未配置 META_AD_LIBRARY_TOKEN，走 HTML 抓取 fallback；"
                "成功率较低（Meta 反爬），建议在 .env.local 加 token。"
                "申请方式见文件头部注释。"
            )
        results = []
        seen_ids = set()
        for app_name in competitors:
            for country in AD_COUNTRIES:
                self.log.info(f"[{app_name}/{country}] Ad Library...")
                await asyncio.sleep(random.uniform(2, 5))
                ads = await self._search_ads(app_name, country)
                # 去重
                unique = []
                for ad in ads:
                    if ad["ad_id"] and ad["ad_id"] not in seen_ids:
                        seen_ids.add(ad["ad_id"])
                        unique.append(ad)
                rec = self.standardize(app_name, {
                    "ad_count": len(unique),
                    "ads": unique,
                }, region=country.lower())
                results.append(rec)
        self.log.info(f"Ad Library: {len(results)} 条记录, {len(seen_ids)} 条去重广告")
        await db.save(self.source_name, results)
        return results


async def crawl(session, database) -> list[dict]:
    return await FBAdLibCrawler(session).crawl(database)
