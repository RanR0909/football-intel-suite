"""DAO: news_items — Google News RSS 抓取条目 + AI v2 任务 5 news_classifier 输出。

调用方:
- async_crawler/sources/google_news.py（抓取层 upsert_news_items）
- ai_tasks/news_classifier.py（AI 层 update_classification + fetch_unclassified）

设计：
- 主键 url（UNIQUE）— 同一新闻多次抓只保留最新 fetched_at
- AI 字段 (is_business / business_category / competitors_mentioned /
  classified_at / classification_confidence) 由 news_classifier 单独 update
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Iterable

from shared import db as _db
from shared.models import NewsItem

log = logging.getLogger("shared.dao.news_items")


def upsert_news_items(items: Iterable[dict]) -> int:
    """对每条新闻按 url UPSERT。

    items 元素结构（与 google_news.py 输出对齐 — 见 _parse_items）:
      {title, link, pub, pub_dt, source, desc, is_biz, app_name, matched_keyword?}
    """
    if not _db.is_mysql_enabled():
        return 0
    ok = 0
    with _db.session() as s:
        for it in items:
            url = (it.get("link") or "").strip()
            title = (it.get("title") or "").strip()
            if not url or not title:
                continue
            row = s.query(NewsItem).filter(NewsItem.url == url[:1024]).first()
            if row is None:
                row = NewsItem(url=url[:1024], title=title[:512])
                s.add(row)
            else:
                row.title = title[:512]
            row.snippet = (it.get("desc") or "")[:8000] or None
            row.source = (it.get("source") or "")[:128] or None
            row.published_at = it.get("pub_dt") if isinstance(it.get("pub_dt"), datetime) else None
            row.matched_keyword = (it.get("matched_keyword") or "")[:128] or None
            row.app_name = (it.get("app_name") or "")[:64] or None
            row.fetched_at = datetime.utcnow()
            ok += 1
    return ok


def fetch_unclassified(*, limit: int = 200) -> list[dict]:
    """取出还没跑 news_classifier 的条目（classified_at IS NULL）。

    排除已在 failed_ai_jobs 里的 news_id，避免反复死磕同一条 garbage payload。
    """
    if not _db.is_mysql_enabled():
        return []
    import sqlalchemy as sa

    blacklist: set[int] = set()
    with _db.engine().connect() as c:
        rows = c.execute(sa.text("""
            SELECT DISTINCT JSON_EXTRACT(payload_json, '$.news_id') AS nid
            FROM failed_ai_jobs
            WHERE task_name = 'news_classifier' AND resolved_at IS NULL
        """)).fetchall()
        for r in rows:
            try:
                blacklist.add(int(r[0]))
            except (TypeError, ValueError):
                pass

    with _db.session() as s:
        q = s.query(NewsItem).filter(NewsItem.classified_at.is_(None))
        if blacklist:
            q = q.filter(~NewsItem.id.in_(blacklist))
        rows = q.order_by(NewsItem.published_at.desc().nullslast(),
                          NewsItem.id.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "snippet": r.snippet,
                "source": r.source,
                "url": r.url,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "matched_keyword": r.matched_keyword,
                "app_name": r.app_name,
            }
            for r in rows
        ]


def update_classification(news_id: int, payload: dict) -> bool:
    """payload: {is_business, category, competitors_mentioned, confidence}"""
    if not _db.is_mysql_enabled():
        return False
    with _db.session() as s:
        row = s.query(NewsItem).filter(NewsItem.id == news_id).first()
        if not row:
            return False
        row.is_business = bool(payload.get("is_business")) if payload.get("is_business") is not None else None
        row.business_category = (payload.get("category") or "")[:32] or None
        comps = payload.get("competitors_mentioned") or []
        if not isinstance(comps, list):
            comps = []
        row.competitors_mentioned = json.dumps(comps, ensure_ascii=False)
        try:
            row.classification_confidence = float(payload.get("confidence") or 0)
        except (TypeError, ValueError):
            row.classification_confidence = None
        row.classified_at = datetime.utcnow()
    return True


def is_classified(url: str) -> bool:
    """url 是否已被分类。"""
    if not _db.is_mysql_enabled() or not url:
        return False
    with _db.session() as s:
        return s.query(
            s.query(NewsItem)
            .filter(NewsItem.url == url[:1024])
            .filter(NewsItem.classified_at.isnot(None))
            .exists()
        ).scalar()


def list_business(*, since_days: int = 30, category: str | None = None,
                  app_name: str | None = None, limit: int = 200) -> list[dict]:
    """前端 /api/news 用：仅返回 is_business=True，按 published_at 倒序。"""
    if not _db.is_mysql_enabled():
        return []
    cutoff = datetime.utcnow() - timedelta(days=since_days)
    with _db.session() as s:
        q = (s.query(NewsItem)
             .filter(NewsItem.is_business.is_(True))
             .filter(NewsItem.published_at >= cutoff))
        if category:
            q = q.filter(NewsItem.business_category == category)
        if app_name:
            q = q.filter(NewsItem.app_name == app_name)
        rows = q.order_by(NewsItem.published_at.desc()).limit(limit).all()
        return [_row_to_dict(r) for r in rows]


def _row_to_dict(r: NewsItem) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "snippet": r.snippet,
        "source": r.source,
        "url": r.url,
        "published_at": r.published_at.isoformat() if r.published_at else None,
        "matched_keyword": r.matched_keyword,
        "app_name": r.app_name,
        "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
        "is_business": r.is_business,
        "business_category": r.business_category,
        "competitors_mentioned": json.loads(r.competitors_mentioned) if r.competitors_mentioned else [],
        "classification_confidence": float(r.classification_confidence) if r.classification_confidence is not None else None,
        "classified_at": r.classified_at.isoformat() if r.classified_at else None,
    }
