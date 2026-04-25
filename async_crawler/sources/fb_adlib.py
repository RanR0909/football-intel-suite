"""Facebook Ad Library 公开广告数据爬虫（无需 API Token）"""
import asyncio
import json
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import get_comment_competitors

AD_COUNTRIES = ["US", "GB", "BR"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


class FBAdLibCrawler(BaseCrawler):
    source_name = "fb_adlib"
    rate_limit = 3.0
    max_retries = 2

    async def _search_ads(self, keyword, country):
        """通过 Ad Library 搜索页面抓取广告数据"""
        url = (
            f"https://www.facebook.com/ads/library/"
            f"?active_status=active&ad_type=all&country={country}"
            f"&q={keyword}&search_type=keyword_unordered"
        )
        ads = []
        try:
            html = await self.fetch(url, headers=HEADERS)
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
