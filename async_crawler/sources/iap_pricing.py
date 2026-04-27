"""App Store IAP 定价。

抓 ld+json 中的 offers 字段，按 (app, region) 切片落盘到
data/raw/iap_pricing.json，供 aggregator 消费。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import get_comment_competitors
from regions import get_region_codes  # noqa: F401  (保留，便于未来切换 region 来源)

IAP_REGIONS = ["us", "gb", "br", "de", "jp"]
_RAW_OUTPUT = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "iap_pricing.json"


class IAPPricingCrawler(BaseCrawler):
    source_name = "iap_pricing"
    rate_limit = 1.5

    async def _scrape_iap(self, app_id, country):
        url = f"https://apps.apple.com/{country}/app/id{app_id}"
        try:
            html = await self.fetch(url)
        except Exception as e:
            self.log.warning(f"[id={app_id}/{country}] 页面抓取失败: {e}")
            return []
        ld_blocks = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
        iaps = []
        for block in ld_blocks:
            try:
                obj = json.loads(block)
            except json.JSONDecodeError:
                continue
            offers = obj.get("offers") if isinstance(obj, dict) else None
            if not offers:
                continue
            if isinstance(offers, dict):
                offers = [offers]
            for o in offers:
                price = o.get("price", "")
                try:
                    price_num = float(price) if price not in ("", None) else None
                except (ValueError, TypeError):
                    price_num = None
                iaps.append({
                    "name": (o.get("name", "") or "")[:120],
                    "price": price,
                    "price_num": price_num,
                    "currency": o.get("priceCurrency", ""),
                    "category": o.get("category", ""),
                })
        return iaps

    async def crawl(self, database) -> list[dict]:
        competitors = get_comment_competitors()
        results = []
        for app_name, comp in competitors.items():
            app_id = comp.get("ios") or comp.get("app_id")
            if not app_id:
                self.log.warning(f"[{app_name}] 缺 ios id，跳过")
                continue
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
        # 持久化 raw 给 aggregator 消费
        self._write_raw_snapshot(results)
        return results

    def _write_raw_snapshot(self, results: list[dict]):
        """合并写入 data/raw/iap_pricing.json，按 (source, competitor, region) 覆盖。"""
        _RAW_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, dict] = {}
        if _RAW_OUTPUT.exists():
            try:
                payload = json.loads(_RAW_OUTPUT.read_text(encoding="utf-8"))
                for rec in payload if isinstance(payload, list) else []:
                    key = f"{rec.get('source')}_{rec.get('competitor')}_{rec.get('region')}"
                    existing[key] = rec
            except Exception:
                existing = {}
        for rec in results:
            key = f"{rec.get('source')}_{rec.get('competitor')}_{rec.get('region')}"
            existing[key] = rec
        _RAW_OUTPUT.write_text(
            json.dumps(list(existing.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.log.info(f"raw snapshot 已写入 {_RAW_OUTPUT}")


async def crawl(session, database) -> list[dict]:
    return await IAPPricingCrawler(session).crawl(database)
