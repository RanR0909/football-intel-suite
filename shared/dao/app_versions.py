"""DAO: app_versions — strategy_monitor 抓回的版本明细 + release notes。

调用方:
- strategy_monitor/changelog_*.py（抓取层 upsert_version）
- comment_label 任务复用做 release_notes 翻译（update_translation）
- /api/versions 端点（list_versions / get_with_related_reviews）
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from shared import db as _db
from shared.dao import resolve_competitor_id
from shared.models import AppVersion

log = logging.getLogger("shared.dao.app_versions")


def upsert_version(
    *,
    competitor_name: str,
    platform: str,
    version: str,
    release_notes: str | None = None,
    release_notes_lang: str | None = None,
    released_at: datetime | None = None,
) -> Optional[int]:
    """对 (competitor, platform, version) UPSERT。返回 row id（新建/已有）。

    若 release_notes 已存在但本次为空，不覆盖（避免 iTunes 偶尔返回空 notes 把已有的清掉）。
    """
    if not _db.is_mysql_enabled():
        return None
    if platform not in ("ios", "gp") or not competitor_name or not version:
        return None
    with _db.session() as s:
        cid = resolve_competitor_id(competitor_name, sess=s)
        if cid is None:
            log.warning(f"[app_versions] competitor {competitor_name!r} 未找到 id")
            return None
        row = (
            s.query(AppVersion)
            .filter(AppVersion.competitor_id == cid)
            .filter(AppVersion.platform == platform)
            .filter(AppVersion.version == version[:64])
            .first()
        )
        is_new = row is None
        if is_new:
            row = AppVersion(
                competitor_id=cid,
                platform=platform,
                version=version[:64],
                first_seen_at=datetime.utcnow(),
            )
            s.add(row)
        # 只在本次有内容时更新 release_notes，避免回滚
        if release_notes:
            row.release_notes = release_notes[:65535]
            if release_notes_lang:
                row.release_notes_lang = release_notes_lang[:8]
        if released_at:
            row.released_at = released_at
        s.flush()
        return row.id


def update_translation(version_id: int, translated_zh: str) -> bool:
    """comment_label 翻译完成后写回。"""
    if not _db.is_mysql_enabled() or not translated_zh:
        return False
    with _db.session() as s:
        row = s.query(AppVersion).filter(AppVersion.id == version_id).first()
        if not row:
            return False
        row.release_notes_translated_zh = translated_zh[:65535]
        row.translated_at = datetime.utcnow()
    return True


def fetch_untranslated(*, limit: int = 50) -> list[dict]:
    """release_notes 已抓但未翻译的版本（translated_at IS NULL & release_notes IS NOT NULL）。"""
    if not _db.is_mysql_enabled():
        return []
    with _db.session() as s:
        rows = (
            s.query(AppVersion)
            .filter(AppVersion.translated_at.is_(None))
            .filter(AppVersion.release_notes.isnot(None))
            .order_by(AppVersion.released_at.desc().nullslast(), AppVersion.id.desc())
            .limit(limit).all()
        )
        return [
            {
                "id": r.id,
                "competitor_id": r.competitor_id,
                "platform": r.platform,
                "version": r.version,
                "release_notes": r.release_notes,
                "release_notes_lang": r.release_notes_lang,
            }
            for r in rows
        ]


def list_versions(*, competitor: str | None = None, since_days: int = 30,
                  limit: int = 200) -> list[dict]:
    """前端 /api/versions 用：按发版时间倒序。"""
    if not _db.is_mysql_enabled():
        return []
    cutoff = datetime.utcnow() - timedelta(days=since_days)
    from shared.models import Competitor
    with _db.session() as s:
        q = (s.query(AppVersion, Competitor.name)
             .join(Competitor, Competitor.id == AppVersion.competitor_id)
             .filter(AppVersion.released_at >= cutoff))
        if competitor:
            q = q.filter(Competitor.name == competitor)
        rows = q.order_by(AppVersion.released_at.desc()).limit(limit).all()
        out = []
        for r, comp_name in rows:
            out.append({
                "id": r.id,
                "competitor": comp_name,
                "platform": r.platform,
                "version": r.version,
                "release_notes": r.release_notes,
                "release_notes_lang": r.release_notes_lang,
                "release_notes_zh": r.release_notes_translated_zh,
                "released_at": r.released_at.isoformat() if r.released_at else None,
                "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
            })
        return out


def get_by_id(version_id: int) -> dict | None:
    if not _db.is_mysql_enabled():
        return None
    from shared.models import Competitor
    with _db.session() as s:
        row = (
            s.query(AppVersion, Competitor.name)
            .join(Competitor, Competitor.id == AppVersion.competitor_id)
            .filter(AppVersion.id == version_id)
            .first()
        )
        if not row:
            return None
        r, comp_name = row
        return {
            "id": r.id,
            "competitor": comp_name,
            "competitor_id": r.competitor_id,
            "platform": r.platform,
            "version": r.version,
            "release_notes": r.release_notes,
            "release_notes_lang": r.release_notes_lang,
            "release_notes_zh": r.release_notes_translated_zh,
            "released_at": r.released_at.isoformat() if r.released_at else None,
        }
