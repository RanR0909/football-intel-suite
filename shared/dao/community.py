"""DAO: community_posts — Reddit + Twitter。

调用方：
- async_crawler/sources/reddit.py
- async_crawler/sources/twitter.py
"""

from __future__ import annotations

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
