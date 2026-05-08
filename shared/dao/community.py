"""DAO: community_posts — Reddit + Twitter。

调用方：
- async_crawler/sources/reddit.py / twitter.py（抓取层 upsert_community_posts）
- ai_tasks/post_topic.py（AI 层 update_topic / fetch_unclassified_topic）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from shared import db as _db
from shared.dao import resolve_competitor_id
from shared.models import CommunityPost

log = logging.getLogger("shared.dao.community")


def upsert_community_posts(competitor_name: str, source: str, posts: list[dict]) -> int:
    """对每条帖子按 (source, post_id) UPSERT；同一 post 多次抓刷新 score / num_comments / fetched_at。

    posts 元素结构（与 reddit.py / twitter.py 输出对齐）：
      {post_id, subreddit, title, selftext, score, num_comments, url, created_utc}
    """
    if not _db.is_mysql_enabled() or not posts:
        return 0
    if source not in ("reddit", "twitter"):
        log.warning(f"[community] 未知 source: {source}")
        return 0
    try:
        from sqlalchemy.dialects.mysql import insert as mysql_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        with _db.session() as s:
            cid = resolve_competitor_id(competitor_name, sess=s)
            if cid is None:
                log.warning(f"[community] competitor {competitor_name!r} 未在 lookup")
                return 0
            now = datetime.utcnow()
            rows = []
            for p in posts:
                pid = p.get("post_id")
                if not pid:
                    continue
                rows.append({
                    "competitor_id": cid,
                    "source": source,
                    "post_id": str(pid)[:64],
                    "subreddit": (p.get("subreddit") or "")[:64] or None,
                    "title": (p.get("title") or "")[:512] or None,
                    "selftext": p.get("selftext") or None,
                    "score": int(p.get("score") or 0),
                    "num_comments": int(p.get("num_comments") or 0),
                    "url": (p.get("url") or "")[:1024] or None,
                    "created_utc": _to_dt(p.get("created_utc")),
                    "fetched_at": now,
                })
            if not rows:
                return 0

            dialect = s.bind.dialect.name
            if dialect == "mysql":
                stmt = mysql_insert(CommunityPost).values(rows)
                stmt = stmt.on_duplicate_key_update(
                    title=stmt.inserted.title,
                    selftext=stmt.inserted.selftext,
                    score=stmt.inserted.score,
                    num_comments=stmt.inserted.num_comments,
                    fetched_at=stmt.inserted.fetched_at,
                )
                s.execute(stmt)
            elif dialect == "sqlite":
                stmt = sqlite_insert(CommunityPost).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["source", "post_id"],
                    set_=dict(
                        title=stmt.excluded.title,
                        selftext=stmt.excluded.selftext,
                        score=stmt.excluded.score,
                        num_comments=stmt.excluded.num_comments,
                        fetched_at=stmt.excluded.fetched_at,
                    ),
                )
                s.execute(stmt)
            else:
                # 通用兜底
                s.query(CommunityPost).filter(
                    CommunityPost.source == source,
                    CommunityPost.post_id.in_([r["post_id"] for r in rows]),
                ).delete(synchronize_session=False)
                s.bulk_insert_mappings(CommunityPost, rows)
            return len(rows)
    except Exception as e:
        log.warning(f"[community] upsert 失败（{competitor_name}/{source}）: {e}")
        return 0


def _to_dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, (int, float)):
        return datetime.utcfromtimestamp(float(v))
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


# ─────────────────── AI v2 task #6 post_topic_classifier ───────────────────


def fetch_unclassified_topic(*, limit: int = 200) -> list[dict]:
    """topic_classified_at IS NULL 的帖子。"""
    if not _db.is_mysql_enabled():
        return []
    import sqlalchemy as sa

    blacklist: set[int] = set()
    with _db.engine().connect() as c:
        rows = c.execute(sa.text("""
            SELECT DISTINCT JSON_EXTRACT(payload_json, '$.post_id') AS pid
            FROM failed_ai_jobs
            WHERE task_name = 'post_topic_classifier' AND resolved_at IS NULL
        """)).fetchall()
        for r in rows:
            try:
                blacklist.add(int(r[0]))
            except (TypeError, ValueError):
                pass

    with _db.session() as s:
        q = s.query(CommunityPost).filter(CommunityPost.topic_classified_at.is_(None))
        if blacklist:
            q = q.filter(~CommunityPost.id.in_(blacklist))
        # MySQL DESC 默认 NULL 在末尾；不能用 .nullslast()（生成 "NULLS LAST" MySQL 不支持）
        rows = q.order_by(CommunityPost.score.desc(),
                          CommunityPost.id.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "post_id": r.post_id,
                "source": r.source,
                "subreddit": r.subreddit,
                "title": r.title,
                "body": r.selftext,
                "score": r.score,
                "url": r.url,
            }
            for r in rows
        ]


# ─────────────────── entity_extract on community_posts (migration 0016) ───────

def fetch_unentitied(*, limit: int = 200) -> list[dict]:
    """entity_extracted_at IS NULL 的帖子（task 2 还没在它上面跑过）。

    排除 failed_ai_jobs 里 task_name='post_entity_extract' 的 post_id。
    """
    if not _db.is_mysql_enabled():
        return []
    import sqlalchemy as sa

    blacklist: set[int] = set()
    with _db.engine().connect() as c:
        rows = c.execute(sa.text("""
            SELECT DISTINCT JSON_EXTRACT(payload_json, '$.post_id') AS pid
            FROM failed_ai_jobs
            WHERE task_name = 'post_entity_extract' AND resolved_at IS NULL
        """)).fetchall()
        for r in rows:
            try:
                blacklist.add(int(r[0]))
            except (TypeError, ValueError):
                pass

    with _db.session() as s:
        q = s.query(CommunityPost).filter(CommunityPost.entity_extracted_at.is_(None))
        if blacklist:
            q = q.filter(~CommunityPost.id.in_(blacklist))
        rows = q.order_by(CommunityPost.score.desc(),
                          CommunityPost.id.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "post_id": r.post_id,
                "title": r.title,
                "body": r.selftext,
                "score": r.score,
            }
            for r in rows
        ]


def mark_entity_extracted(post_db_id: int) -> bool:
    """跑完 entity_extract 后标记时间戳，避免下次重复跑（铁律 4）。"""
    if not _db.is_mysql_enabled():
        return False
    with _db.session() as s:
        row = s.query(CommunityPost).filter(CommunityPost.id == post_db_id).first()
        if not row:
            return False
        row.entity_extracted_at = datetime.utcnow()
    return True


def update_topic(post_db_id: int, payload: dict) -> bool:
    """payload: {primary_topic, secondary_topics, competitor_mentioned, confidence}"""
    if not _db.is_mysql_enabled():
        return False
    with _db.session() as s:
        row = s.query(CommunityPost).filter(CommunityPost.id == post_db_id).first()
        if not row:
            return False
        row.primary_topic = (payload.get("primary_topic") or "")[:32] or None
        sec = payload.get("secondary_topics") or []
        if not isinstance(sec, list):
            sec = []
        row.secondary_topics = json.dumps(sec, ensure_ascii=False)
        row.competitor_mentioned = (payload.get("competitor_mentioned") or "")[:64] or None
        try:
            row.topic_confidence = float(payload.get("confidence") or 0)
        except (TypeError, ValueError):
            row.topic_confidence = None
        row.topic_classified_at = datetime.utcnow()
    return True


# ─────────────────── post translate (migration 0019) ──────────────────────


def fetch_untranslated_posts(*, limit: int = 200) -> list[dict]:
    """translated_at IS NULL 的帖子（task 9 post_translate 还没跑过）。

    排除 failed_ai_jobs 里 task_name='post_translate' 的 post_id。
    """
    if not _db.is_mysql_enabled():
        return []
    import sqlalchemy as sa

    blacklist: set[int] = set()
    with _db.engine().connect() as c:
        rows = c.execute(sa.text("""
            SELECT DISTINCT JSON_EXTRACT(payload_json, '$.post_id') AS pid
            FROM failed_ai_jobs
            WHERE task_name = 'post_translate' AND resolved_at IS NULL
        """)).fetchall()
        for r in rows:
            try:
                blacklist.add(int(r[0]))
            except (TypeError, ValueError):
                pass

    with _db.session() as s:
        q = s.query(CommunityPost).filter(CommunityPost.translated_at.is_(None))
        if blacklist:
            q = q.filter(~CommunityPost.id.in_(blacklist))
        rows = q.order_by(CommunityPost.score.desc(),
                          CommunityPost.id.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "title": r.title or "",
                "selftext": r.selftext or "",
            }
            for r in rows
        ]


def update_post_translation(post_db_id: int, title_zh: str, selftext_zh: str) -> bool:
    """写回 title_zh + selftext_zh + translated_at。"""
    if not _db.is_mysql_enabled():
        return False
    with _db.session() as s:
        row = s.query(CommunityPost).filter(CommunityPost.id == post_db_id).first()
        if not row:
            return False
        # 切到 column 上限以防超长
        row.title_zh = (title_zh or "")[:512] or None
        row.selftext_zh = (selftext_zh or "")[:65535] or None
        row.translated_at = datetime.utcnow()
    return True
