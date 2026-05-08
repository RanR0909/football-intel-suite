"""DAO: ad_creatives — Meta 广告库。

调用方：
- market_rank/scrape_fb_adlib.py（抓取层 upsert_ad_creatives）
- ai_tasks/ad_selling_point.py（AI 层 update_selling / fetch_unclassified_selling）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from shared import db as _db
from shared.dao import resolve_competitor_id
from shared.models import AdCreative

log = logging.getLogger("shared.dao.ads")


def upsert_ad_creatives(competitor_name: str, region: str, ads: list[dict]) -> int:
    """对每条 ad 按 (competitor_id, ad_id) UPSERT；同一广告多次抓刷新 fetched_at。

    ads 元素：{ad_id, text, start_date, platform, page_name, page_id, media_url}
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
                    "page_id": (a.get("page_id") or None),     # migration 0021 新加
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
                    page_id=stmt.inserted.page_id,
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
                        page_id=stmt.excluded.page_id,
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


# ─────────────────── AI v2 task #7 ad_selling_point ───────────────────


def fetch_unclassified_selling(*, limit: int = 200) -> list[dict]:
    """取出 selling_classified_at IS NULL 的创意。"""
    if not _db.is_mysql_enabled():
        return []
    import sqlalchemy as sa

    blacklist: set[int] = set()
    with _db.engine().connect() as c:
        rows = c.execute(sa.text("""
            SELECT DISTINCT JSON_EXTRACT(payload_json, '$.ad_id') AS aid
            FROM failed_ai_jobs
            WHERE task_name = 'ad_selling_point' AND resolved_at IS NULL
        """)).fetchall()
        for r in rows:
            try:
                blacklist.add(int(r[0]))
            except (TypeError, ValueError):
                pass

    with _db.session() as s:
        q = s.query(AdCreative).filter(AdCreative.selling_classified_at.is_(None))
        q = q.filter(AdCreative.text.isnot(None))
        if blacklist:
            q = q.filter(~AdCreative.id.in_(blacklist))
        rows = q.order_by(AdCreative.fetched_at.desc()).limit(limit).all()
        from shared.models import Competitor
        # 拼竞品名
        cid_map = {c.id: c.name for c in s.query(Competitor).all()}
        return [
            {
                "id": r.id,
                "ad_id": r.ad_id,
                "competitor_id": r.competitor_id,
                "competitor": cid_map.get(r.competitor_id),
                "country": r.region_code,
                "creative_text": r.text,
                "media_type": r.platform or "image",
            }
            for r in rows
        ]


def update_selling(ad_creative_id: int, payload: dict) -> bool:
    """payload: {selling_points, audience, tone, confidence}"""
    if not _db.is_mysql_enabled():
        return False
    with _db.session() as s:
        row = s.query(AdCreative).filter(AdCreative.id == ad_creative_id).first()
        if not row:
            return False
        sp = payload.get("selling_points") or []
        if not isinstance(sp, list):
            sp = []
        row.selling_points = json.dumps(sp, ensure_ascii=False)
        row.audience = (payload.get("audience") or "")[:32] or None
        row.tone = (payload.get("tone") or "")[:16] or None
        try:
            row.selling_confidence = float(payload.get("confidence") or 0)
        except (TypeError, ValueError):
            row.selling_confidence = None
        row.selling_classified_at = datetime.utcnow()
    return True
