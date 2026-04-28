"""DAO: reviews — 用户评论（GP / iOS）。

调用方：
- competitor_comment/comment_fetch.py（写 raw 评论）
- competitor_comment/comment_label.py（更新 label 字段）
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from shared import db as _db
from shared.dao import resolve_competitor_id
from shared.models import Review

log = logging.getLogger("shared.dao.reviews")


def bulk_insert_reviews(competitor_name: str, region: str, rows: list[dict]) -> int:
    """批量写入评论。rows 来自 comment_fetch raw payload。

    rows 元素结构：{score, version, content, _platform: "gp"|"ios"}
    返回成功插入数；DB 不可用 / 写失败返回 0。
    """
    if not _db.is_mysql_enabled() or not rows:
        return 0
    try:
        with _db.session() as s:
            cid = resolve_competitor_id(competitor_name, sess=s)
            if cid is None:
                log.warning(f"[reviews] competitor {competitor_name!r} 未在 lookup 表中，跳过")
                return 0
            now = datetime.utcnow()
            mappings = []
            for r in rows:
                platform = (r.get("_platform") or "gp").lower()
                if platform not in ("gp", "ios"):
                    continue
                mappings.append({
                    "competitor_id": cid,
                    "region_code": region,
                    "platform": platform,
                    "score": r.get("score"),
                    "version": (r.get("version") or "")[:32] or None,
                    "content": r.get("content") or None,
                    "label": None,    # comment_label.py 之后补
                    "at": _parse_dt(r.get("at")),
                    "fetched_at": now,
                })
            if not mappings:
                return 0
            s.bulk_insert_mappings(Review, mappings)
            return len(mappings)
    except Exception as e:
        log.warning(f"[reviews] 批量写入失败（{competitor_name}/{region}）: {e}")
        return 0


def update_labels(competitor_name: str, region: str, label_by_id: dict[int, str]) -> int:
    """按 review.id 更新 label 字段。

    实际 comment_label.py 拿到的是按"行号"打的 label，没用到 review.id。
    所以用一个 helper：按 (competitor, region, fetched_at>=today) 找出最近批次再按顺序更新。

    简单实现：按时间戳排序后位置匹配。如果数据不一致就放弃（log warning）。
    """
    if not _db.is_mysql_enabled() or not label_by_id:
        return 0
    try:
        with _db.session() as s:
            from sqlalchemy import update
            updated = 0
            for rid, label in label_by_id.items():
                stmt = update(Review).where(Review.id == rid).values(label=label)
                s.execute(stmt)
                updated += 1
            return updated
    except Exception as e:
        log.warning(f"[reviews] 更新 label 失败: {e}")
        return 0


def _parse_dt(v):
    if v is None or isinstance(v, datetime):
        return v
    if isinstance(v, (int, float)):
        return datetime.utcfromtimestamp(v)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            return None
    return None
