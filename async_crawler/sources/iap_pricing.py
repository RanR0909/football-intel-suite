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

    # 区域 → 默认货币（用于无法从符号识别时兜底）
    _REGION_CURRENCY = {
        "us": "USD", "ca": "CAD", "gb": "GBP", "de": "EUR", "fr": "EUR",
        "es": "EUR", "it": "EUR", "br": "BRL", "jp": "JPY", "kr": "KRW",
        "in": "INR", "au": "AUD", "mx": "MXN", "tr": "TRY", "sa": "SAR",
        "ae": "AED", "id": "IDR", "vn": "VND", "my": "MYR", "ng": "NGN",
    }
    # 货币符号 → ISO（粗略匹配；多义符号如 $ 用 region 兜底）
    _SYMBOL_TO_CURRENCY = {
        "£": "GBP", "€": "EUR", "¥": "JPY", "₹": "INR",
        "₩": "KRW", "₺": "TRY", "R$": "BRL", "RM": "MYR",
    }

    async def _scrape_iap(self, app_id, country):
        url = f"https://apps.apple.com/{country}/app/id{app_id}"
        try:
            html = await self.fetch(url)
        except Exception as e:
            self.log.warning(f"[id={app_id}/{country}] 页面抓取失败: {e}")
            return []

        # Apple 把 IAP 列表渲染在 svelte 模板：
        #   <div class="text-pair ..."><span>NAME</span> <span>$PRICE</span></div>
        # ld+json 的 offers 只是 APP 本身价格（free/paid），不是 IAP。
        pattern = re.compile(
            r'<div[^>]*class="[^"]*text-pair[^"]*"[^>]*>\s*<span>([^<]+)</span>\s*<span>([^<]+)</span>',
            re.IGNORECASE,
        )
        # 价格识别：必须含货币符号（过滤掉 "Compatibility" 这类元数据 text-pair）
        price_sig = re.compile(r'[$£€¥₹₩₺]|R\$|RM|kr\b|zł\b')

        seen = set()
        iaps = []
        default_ccy = self._REGION_CURRENCY.get(country.lower(), "")
        for m in pattern.finditer(html):
            name = m.group(1).strip()[:120]
            price_str = m.group(2).strip()[:60]
            if not price_sig.search(price_str):
                continue  # 非价格 text-pair 跳过

            # 去重：相同 (name, price) 只留一条
            key = (name, price_str)
            if key in seen:
                continue
            seen.add(key)

            # 解析数字与货币符号
            price_num = None
            num_match = re.search(r'([\d]+(?:[.,]\d+)?)', price_str)
            if num_match:
                try:
                    price_num = float(num_match.group(1).replace(",", "."))
                except ValueError:
                    pass
            # 货币：先尝试明确符号；fallback region 默认
            ccy = ""
            for sym, code in self._SYMBOL_TO_CURRENCY.items():
                if sym in price_str:
                    ccy = code
                    break
            if not ccy and "$" in price_str:
                ccy = default_ccy or "USD"   # $ 多义 → region 兜底
            if not ccy:
                ccy = default_ccy

            iaps.append({
                "name": name,
                "price": price_str,
                "price_num": price_num,
                "currency": ccy,
                "category": "iap",
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
        # 先写 raw（aggregator 消费），再尝试 db.save（失败不影响 raw）
        self._write_raw_snapshot(results)
        try:
            await database.save(self.source_name, results)
        except Exception as e:
            self.log.warning(f"db.save 跳过：{e}")
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
