"""DAO: iap_items — IAP 内购定价。

调用方：async_crawler/sources/iap_pricing.py
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from shared import db as _db
from shared.dao import resolve_competitor_id
from shared.models import IapItem

log = logging.getLogger("shared.dao.iap")


def bulk_insert_iap(competitor_name: str, region: str, items: list[dict]) -> int:
    """每次抓取插一批 snapshot（不去重 — 时间序列，便于看价格趋势）。

    items 元素：{name, price, currency, category}
    """
    if not _db.is_mysql_enabled() or not items:
        return 0
    try:
        with _db.session() as s:
            cid = resolve_competitor_id(competitor_name, sess=s)
            if cid is None:
                log.warning(f"[iap] competitor {competitor_name!r} 未在 lookup")
                return 0
            now = datetime.utcnow()
            mappings = []
            for it in items:
                name = it.get("name")
                if not name:
                    continue
                mappings.append({
                    "competitor_id": cid,
                    "region_code": region,
                    "name": name[:255],
                    "price": (it.get("price") or "")[:32] or None,
                    "price_num": _parse_price(it.get("price")),
                    "currency": (it.get("currency") or "")[:8] or None,
                    "category": (it.get("category") or "")[:32] or None,
                    "fetched_at": now,
                })
            if not mappings:
                return 0
            s.bulk_insert_mappings(IapItem, mappings)
            return len(mappings)
    except Exception as e:
        log.warning(f"[iap] 批量写入失败（{competitor_name}/{region}）: {e}")
        return 0


_PRICE_RE = re.compile(r"([\d,]+\.?\d*)")


def _parse_price(s) -> Decimal | None:
    """从 '$9.99' / '￥68.00' / '9.99' 等抽出数值。"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        try:
            return Decimal(str(s))
        except InvalidOperation:
            return None
    m = _PRICE_RE.search(str(s).replace(",", ""))
    if not m:
        return None
    try:
        return Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None
