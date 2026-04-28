"""DAO: ad_creatives — Meta 广告库。

调用方：market_rank/scrape_fb_adlib.py
"""

from __future__ import annotations

import logging
from datetime import datetime

from shared import db as _db
from shared.dao import resolve_competitor_id
from shared.models import AdCreative

log = logging.getLogger("shared.dao.ads")


def upsert_ad_creatives(competitor_name: str, region: str, ads: list[dict]) -> int:
    """对每条 ad 按 (competitor_id, ad_id) UPSERT；同一广告多次抓刷新 fetched_at。

    ads 元素：{ad_id, text, start_date, platform, page_name, media_url}
    """
    if not _db.is_mysql_enabled() or not ads:
        return 0
    try:
        from sqlalchemy.dialects.mysql import insert as mysql_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        from sqlalchemy import text

        with _db.session() as s:
            cid = resolve_competitor_id(competitor_name, sess=s)
            if cid is None:
                log.warning(f"[ads] competitor {competitor_name!r} 未在 lookup")
                return 0
            now = datetime.utcnow()
            rows = []
            for a in ads:
                ad_id = a.get("ad_id")
                if not ad_id:
                    continue
                rows.append({
                    "competitor_id": cid,
                    "region_code": region,
                    "ad_id": ad_id,
                    "text": a.get("text"),
                    "start_date": a.get("start_date"),
                    "platform": a.get("platform"),
                    "page_name": a.get("page_name"),
                    "media_url": a.get("media_url"),
                    "fetched_at": now,
                })
            if not rows:
                return 0

            # 按 dialect 选 upsert 语法
            dialect = s.bind.dialect.name
            if dialect == "mysql":
                stmt = mysql_insert(AdCreative).values(rows)
                stmt = stmt.on_duplicate_key_update(
                    text=stmt.inserted.text,
                    start_date=stmt.inserted.start_date,
                    platform=stmt.inserted.platform,
                    page_name=stmt.inserted.page_name,
                    media_url=stmt.inserted.media_url,
                    fetched_at=stmt.inserted.fetched_at,
                )
                s.execute(stmt)
            elif dialect == "sqlite":
                stmt = sqlite_insert(AdCreative).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["competitor_id", "ad_id"],
                    set_=dict(
                        text=stmt.excluded.text,
                        start_date=stmt.excluded.start_date,
                        platform=stmt.excluded.platform,
                        page_name=stmt.excluded.page_name,
                        media_url=stmt.excluded.media_url,
                        fetched_at=stmt.excluded.fetched_at,
                    ),
                )
                s.execute(stmt)
            else:
                # 通用兜底：先 delete 再 insert
                s.query(AdCreative).filter(
                    AdCreative.competitor_id == cid,
                    AdCreative.ad_id.in_([r["ad_id"] for r in rows]),
                ).delete(synchronize_session=False)
                s.bulk_insert_mappings(AdCreative, rows)
            return len(rows)
    except Exception as e:
        log.warning(f"[ads] upsert 失败（{competitor_name}/{region}）: {e}")
        return 0
