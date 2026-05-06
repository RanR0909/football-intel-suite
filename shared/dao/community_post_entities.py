"""DAO: community_post_entities — 社媒帖子 ↔ 实体多对多。

调用方：ai_tasks/post_entity_extract.py
对偶于 shared/dao/comment_entities.py（reviews 版）。
"""

from __future__ import annotations

import logging
from datetime import datetime

from shared import db as _db
from shared.models import CommunityPostEntity

log = logging.getLogger("shared.dao.community_post_entities")


def upsert_links(post_id: int, entities: list[dict]) -> int:
    """entities = [{type, raw_value, canonical_id, ...}]
    重复 (post_id, canonical_id) 自动跳过（uniq 约束）。
    """
    if not _db.is_mysql_enabled() or not entities or not post_id:
        return 0
    n = 0
    with _db.session() as s:
        for ent in entities:
            cid = ent.get("canonical_id")
            ttype = ent.get("type")
            if not cid or not ttype:
                continue
            existing = (
                s.query(CommunityPostEntity)
                .filter(
                    CommunityPostEntity.post_id == post_id,
                    CommunityPostEntity.canonical_id == cid,
                )
                .first()
            )
            if existing:
                continue
            s.add(CommunityPostEntity(
                post_id=post_id,
                canonical_id=cid[:64],
                entity_type=ttype[:32],
                raw_value=(ent.get("raw_value") or "")[:255] or None,
                extracted_at=datetime.utcnow(),
            ))
            n += 1
    return n


def for_post(post_id: int) -> list[dict]:
    if not _db.is_mysql_enabled() or not post_id:
        return []
    with _db.session() as s:
        rows = (s.query(CommunityPostEntity)
                .filter(CommunityPostEntity.post_id == post_id).all())
        return [{
            "canonical_id": r.canonical_id,
            "type": r.entity_type,
            "raw_value": r.raw_value,
        } for r in rows]
