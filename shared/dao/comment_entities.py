"""DAO: comment_entities — 评论 ↔ 实体多对多。

调用方：ai_tasks/entity_extract.py
"""

from __future__ import annotations

import logging
from datetime import datetime

from shared import db as _db
from shared.models import CommentEntity

log = logging.getLogger("shared.dao.comment_entities")


def upsert_links(review_id: int, entities: list[dict]) -> int:
    """entities = [{type, raw_value, canonical_id, ...}]
    重复（review_id, canonical_id）自动跳过（uniq 约束）。
    """
    if not _db.is_mysql_enabled() or not entities or not review_id:
        return 0
    n = 0
    with _db.session() as s:
        for ent in entities:
            cid = ent.get("canonical_id")
            ttype = ent.get("type")
            if not cid or not ttype:
                continue
            # 查重
            existing = (
                s.query(CommentEntity)
                .filter(
                    CommentEntity.review_id == review_id,
                    CommentEntity.canonical_id == cid,
                )
                .first()
            )
            if existing:
                continue
            s.add(CommentEntity(
                review_id=review_id,
                canonical_id=cid[:64],
                entity_type=ttype[:32],
                raw_value=(ent.get("raw_value") or "")[:255] or None,
                extracted_at=datetime.utcnow(),
            ))
            n += 1
    return n


def for_review(review_id: int) -> list[dict]:
    if not _db.is_mysql_enabled() or not review_id:
        return []
    with _db.session() as s:
        rows = s.query(CommentEntity).filter(CommentEntity.review_id == review_id).all()
        return [{
            "canonical_id": r.canonical_id,
            "type": r.entity_type,
            "raw_value": r.raw_value,
        } for r in rows]
