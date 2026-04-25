"""App Store IAP 定价"""
import re
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import get_comment_competitors
from regions import get_region_codes

IAP_REGIONS = ["us", "gb", "br", "de", "jp"]


class IAPPricingCrawler(BaseCrawler):
    source_name = "iap_pricing"
    rate_limit = 1.5

    async def _scrape_iap(self, app_id, country):
        url = f"https://apps.apple.com/{country}/app/id{app_id}"
        try:
            html = await self.fetch(url)
            ld_blocks = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
            iaps = []
            for block in ld_blocks:
                try:
                    obj = json.loads(block)
                    offers = obj.get("offers") if isinstance(obj, dict) else None
                    if not offers:
                        continue
                    if isinstance(offers, dict):
                        offers = [offers]
                    for o in offers:
                        iaps.append({
                            "name": o.get("name", ""),
                            "price": o.get("price", ""),
                            "currency": o.get("priceCurrency", ""),
                            "category": o.get("category", ""),
                        })
                except json.JSONDecodeError:
                    continue
            return iaps
        except Exception:
            return []

    async def crawl(self, database) -> list[dict]:
        competitors = get_comment_competitors()
        results = []
        for app_name, comp in competitors.items():
            app_id = comp["ios"]
            for region in IAP_REGIONS:
                self.log.info(f"[{app_name}/{region}] IAP...")
                iaps = await self._scrape_iap(app_id, region)
                rec = self.standardize(app_name, {
                    "iap_count": len(iaps),
                    "iaps": iaps,
                }, region=region)
                results.append(rec)
        self.log.info(f"IAP 定价: {len(results)} 条")
        await db.save(self.source_name, results)
        return results


async def crawl(session, database) -> list[dict]:
    return await IAPPricingCrawler(session).crawl(database)
