"""DAO: app_classifications — peer app 分类（AI v2 任务 4）。

调用方：ai_tasks/app_classifier.py

upsert_classification 同 (app_id, platform) 重复 upsert 同一行（保留 classified_at 更新）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Iterable

from shared import db as _db
from shared.models import AppClassification

log = logging.getLogger("shared.dao.app_classifications")


def upsert_classification(
    *,
    app_id: str,
    platform: str,
    payload: dict,
    name: str | None = None,
    publisher: str | None = None,
    bundle_id: str | None = None,
    category: str | None = None,
    description_excerpt: str | None = None,
    matched_keywords: Iterable[str] | None = None,
) -> bool:
    """payload 来自 AI 输出：{is_relevant, topic, categories, confidence, rejection_reason}"""
    if not _db.is_mysql_enabled():
        return False
    if not app_id or platform not in ("ios", "gp"):
        return False
    with _db.session() as s:
        row = (
            s.query(AppClassification)
            .filter(AppClassification.app_id == app_id, AppClassification.platform == platform)
            .first()
        )
        if row is None:
            row = AppClassification(
                app_id=app_id[:32],
                platform=platform,
            )
            s.add(row)
        row.bundle_id = (bundle_id or "")[:128] or None
        row.name = (name or "")[:255] or None
        row.publisher = (publisher or "")[:255] or None
        row.category = (category or "")[:64] or None
        row.description_excerpt = (description_excerpt or "")[:8000] or None
        row.matched_keywords = json.dumps(list(matched_keywords or []), ensure_ascii=False)
        # AI fields
        row.is_relevant = bool(payload.get("is_relevant")) if payload.get("is_relevant") is not None else None
        row.topic = (payload.get("topic") or "")[:16] or None
        cats = payload.get("categories") or []
        if not isinstance(cats, list):
            cats = []
        row.categories = json.dumps(cats, ensure_ascii=False)
        try:
            row.confidence = float(payload.get("confidence") or 0)
        except (TypeError, ValueError):
            row.confidence = None
        row.rejection_reason = (payload.get("rejection_reason") or "")[:255] or None
        row.classified_at = datetime.utcnow()
    return True


def get(app_id: str, platform: str) -> dict | None:
    if not _db.is_mysql_enabled() or not app_id or platform not in ("ios", "gp"):
        return None
    with _db.session() as s:
        row = (
            s.query(AppClassification)
            .filter(AppClassification.app_id == app_id, AppClassification.platform == platform)
            .first()
        )
        if not row:
            return None
        return _row_to_dict(row)


def list_relevant(*, topic: str | None = None, limit: int = 200) -> list[dict]:
    """筛 is_relevant=True 的 app；可按 topic 过滤。"""
    if not _db.is_mysql_enabled():
        return []
    with _db.session() as s:
        q = s.query(AppClassification).filter(AppClassification.is_relevant.is_(True))
        if topic:
            q = q.filter(AppClassification.topic == topic)
        rows = q.order_by(AppClassification.confidence.desc(),
                          AppClassification.classified_at.desc()).limit(limit).all()
        return [_row_to_dict(r) for r in rows]


def is_already_classified(app_id: str, platform: str, *, max_age_days: int = 30) -> bool:
    """同 (app_id, platform) 在 max_age_days 内已分类过 → True（避免重复花钱）。"""
    if not _db.is_mysql_enabled():
        return False
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    with _db.session() as s:
        return s.query(
            s.query(AppClassification)
            .filter(AppClassification.app_id == app_id)
            .filter(AppClassification.platform == platform)
            .filter(AppClassification.classified_at >= cutoff)
            .exists()
        ).scalar()


def _row_to_dict(r: AppClassification) -> dict:
    return {
        "app_id": r.app_id,
        "platform": r.platform,
        "bundle_id": r.bundle_id,
        "name": r.name,
        "publisher": r.publisher,
        "category": r.category,
        "description_excerpt": r.description_excerpt,
        "matched_keywords": json.loads(r.matched_keywords) if r.matched_keywords else [],
        "is_relevant": r.is_relevant,
        "topic": r.topic,
        "categories": json.loads(r.categories) if r.categories else [],
        "confidence": r.confidence,
        "rejection_reason": r.rejection_reason,
        "classified_at": r.classified_at.isoformat() if r.classified_at else None,
    }
