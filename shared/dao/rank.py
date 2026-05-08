"""DAO: market_rank_snapshots — 排名时间序列。

调用方：
- async_crawler/sources/appstore_rank.py（source='appstore_rank'）
- market_rank/appmagic_adapter.py（source='appmagic'）
- market_rank/scrape_sensor_tower.py（source='sensor_tower'）
"""

from __future__ import annotations

import logging
from datetime import date as _date, datetime
from typing import Optional

from shared import db as _db
from shared.dao import resolve_competitor_id
from shared.models import MarketRankSnapshot

log = logging.getLogger("shared.dao.rank")


def bulk_insert_rank_snapshots(
    source: str,
    rows: list[dict],
    snapshot_date: Optional[_date] = None,
) -> int:
    """批量插入排名快照。

    rows 元素：{
      "name": str,            # 应用名（competitor 也可能是 None）
      "competitor": str,      # 已知 tracked competitor 的 name；非 tracked 传 None
      "platform": str,        # 可选；"ios"/"android" — sensor_tower 必填，androidrank
                              #         调用方不填则 DAO 自动设 "android"，
                              #         appmagic / appstore_rank 留 NULL（不区分）
      "region": str,          # "us" / "gb" / None=worldwide
      "rank": int,
      "delta": int,
      "downloads": str,       # 原始字符串如 "200K"
      "downloads_num": int,   # 可选；解析后整数（sensor_tower 用）
      "revenue_num": int,     # 可选；月收入估算（sensor_tower 用，单位 USD）
    }
    """
    if not _db.is_mysql_enabled() or not rows:
        return 0
    if source not in ("appmagic", "appstore_rank", "sensor_tower", "androidrank"):
        log.warning(f"[rank] 未知 source: {source}")
        return 0
    try:
        with _db.session() as s:
            now = datetime.utcnow()
            sd = snapshot_date or _date.today()
            mappings = []
            for r in rows:
                comp_name = r.get("competitor")
                cid = resolve_competitor_id(comp_name, sess=s) if comp_name else None
                # platform 推导：调用方传了就用；没传时 androidrank 兜底为 'android'，其它源 None
                platform = r.get("platform")
                if platform is None and source == "androidrank":
                    platform = "android"
                mappings.append({
                    "source": source,
                    "platform": platform,
                    "region_code": r.get("region"),
                    "competitor_id": cid,
                    "name": (r.get("name") or "")[:128] or None,
                    "rank_value": r.get("rank"),
                    "delta": r.get("delta"),
                    "downloads": (r.get("downloads") or "")[:32] or None,
                    "downloads_num": r.get("downloads_num"),
                    "revenue_num": r.get("revenue_num"),
                    "snapshot_date": sd,
                    "fetched_at": now,
                })
            if not mappings:
                return 0
            s.bulk_insert_mappings(MarketRankSnapshot, mappings)
            return len(mappings)
    except Exception as e:
        log.warning(f"[rank] 批量写入失败（source={source}）: {e}")
        return 0
