"""DAO: entity_aliases — 实体归一表（AI v2）。

调用方：ai_tasks/entity_extract.py

设计：
- aliases 字段存 JSON list of strings（兼容 SQLite 用 TEXT，MySQL 也用 TEXT）
- canonical_id 大小写敏感，外部约定全小写、{type}_{slug} 格式
- lookup_by_alias 是 O(N)（从内存里查）— alias 数量预计 < 10K，可接受；
  扩到 10K+ 时改用倒排索引 / 物化的 alias_lookup 表
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime
from typing import Iterable

from shared import db as _db
from shared.models import EntityAlias

log = logging.getLogger("shared.dao.entity_aliases")


# ---- 工具 ----------------------------------------------------------------


def _norm(s) -> str:
    """规范化字符串用于 alias 匹配（lowercase + 去重音符 + 去多余空白）。"""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _aliases_loaded(row: EntityAlias) -> list[str]:
    if not row.aliases:
        return []
    try:
        v = json.loads(row.aliases)
        return [str(x) for x in v] if isinstance(v, list) else []
    except Exception:
        return []


# ---- 读取 ----------------------------------------------------------------


def all_canonicals(*, type_filter: str | None = None) -> list[dict]:
    """返回所有 canonical（送给 AI prompt 用的紧凑 list）。"""
    if not _db.is_mysql_enabled():
        return []
    out: list[dict] = []
    with _db.session() as s:
        q = s.query(EntityAlias)
        if type_filter:
            q = q.filter(EntityAlias.entity_type == type_filter)
        for row in q.order_by(EntityAlias.entity_type, EntityAlias.canonical_id).all():
            out.append({
                "canonical_id": row.canonical_id,
                "type": row.entity_type,
                "primary_name": row.primary_name,
                "aliases": _aliases_loaded(row),
            })
    return out


def lookup_by_alias(raw_value: str, *, type_filter: str | None = None) -> str | None:
    """raw_value 是否匹配某个 canonical 的 primary_name / english_name / aliases？返回 canonical_id 或 None。"""
    if not raw_value or not _db.is_mysql_enabled():
        return None
    target = _norm(raw_value)
    with _db.session() as s:
        q = s.query(EntityAlias)
        if type_filter:
            q = q.filter(EntityAlias.entity_type == type_filter)
        for row in q.all():
            if _norm(row.primary_name) == target or _norm(row.english_name) == target:
                return row.canonical_id
            for a in _aliases_loaded(row):
                if _norm(a) == target:
                    return row.canonical_id
    return None


# ---- 写入 ----------------------------------------------------------------


def upsert_canonical(
    canonical_id: str,
    entity_type: str,
    primary_name: str,
    *,
    english_name: str | None = None,
    aliases: Iterable[str] | None = None,
    reviewed: bool = False,
) -> bool:
    """新建或更新 canonical 行。aliases 合并不覆盖。返回 True 表示有变更。"""
    if not _db.is_mysql_enabled():
        return False
    if not canonical_id or not entity_type or not primary_name:
        return False
    new_aliases = list(aliases or [])
    with _db.session() as s:
        row = s.query(EntityAlias).filter(EntityAlias.canonical_id == canonical_id).first()
        if row is None:
            row = EntityAlias(
                canonical_id=canonical_id[:64],
                entity_type=entity_type[:32],
                primary_name=primary_name[:255],
                english_name=(english_name or "")[:255] or None,
                aliases=json.dumps(new_aliases, ensure_ascii=False),
                reviewed=reviewed,
                reviewed_at=datetime.utcnow() if reviewed else None,
            )
            s.add(row)
            return True
        # update path：合并 aliases，primary_name 保留旧值（避免 AI 反复改名）
        merged: list[str] = list(_aliases_loaded(row))
        existing_norm = {_norm(x) for x in merged}
        for a in new_aliases:
            if _norm(a) not in existing_norm and a:
                merged.append(a)
                existing_norm.add(_norm(a))
        row.aliases = json.dumps(merged, ensure_ascii=False)
        if english_name and not row.english_name:
            row.english_name = english_name[:255]
        if reviewed and not row.reviewed:
            row.reviewed = True
            row.reviewed_at = datetime.utcnow()
        return True


def add_alias(canonical_id: str, raw_value: str) -> bool:
    """给已存在 canonical 加一个新 alias。重复 alias 自动去重。"""
    if not _db.is_mysql_enabled() or not canonical_id or not raw_value:
        return False
    with _db.session() as s:
        row = s.query(EntityAlias).filter(EntityAlias.canonical_id == canonical_id).first()
        if row is None:
            return False
        existing = _aliases_loaded(row)
        existing_norm = {_norm(x) for x in existing}
        if _norm(raw_value) in existing_norm:
            return False
        existing.append(raw_value)
        row.aliases = json.dumps(existing, ensure_ascii=False)
        # 加新 alias 后默认 reviewed=False（等人工审核）
        row.reviewed = False
        row.reviewed_at = None
        return True


def list_unreviewed(limit: int = 200) -> list[dict]:
    """周批审核用：返回 reviewed=False 的 canonical 清单。"""
    if not _db.is_mysql_enabled():
        return []
    out: list[dict] = []
    with _db.session() as s:
        rows = (
            s.query(EntityAlias)
            .filter(EntityAlias.reviewed.is_(False))
            .order_by(EntityAlias.created_at.desc())
            .limit(limit)
            .all()
        )
        for r in rows:
            out.append({
                "canonical_id": r.canonical_id,
                "type": r.entity_type,
                "primary_name": r.primary_name,
                "english_name": r.english_name,
                "aliases": _aliases_loaded(r),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
    return out


def mark_reviewed(canonical_ids: list[str]) -> int:
    """批量标记 reviewed=True。"""
    if not _db.is_mysql_enabled() or not canonical_ids:
        return 0
    n = 0
    now = datetime.utcnow()
    with _db.session() as s:
        for cid in canonical_ids:
            row = s.query(EntityAlias).filter(EntityAlias.canonical_id == cid).first()
            if row and not row.reviewed:
                row.reviewed = True
                row.reviewed_at = now
                n += 1
    return n


# ---- chinese_name 翻译（task #8 entity_translate）---------------------------


def fetch_untranslated(*, limit: int = 200) -> list[dict]:
    """取还没翻译过的 entity（chinese_name IS NULL）。

    为避免反复死磕同一条 garbage payload，排除已在 failed_ai_jobs 里的 canonical_id。
    """
    if not _db.is_mysql_enabled():
        return []
    import sqlalchemy as sa

    blacklist: set[str] = set()
    with _db.engine().connect() as c:
        rows = c.execute(sa.text(
            """
            SELECT DISTINCT JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.canonical_id')) AS cid
            FROM failed_ai_jobs
            WHERE task_name = 'entity_translate' AND resolved_at IS NULL
            """
        )).fetchall()
        blacklist = {r[0] for r in rows if r[0]}

    out: list[dict] = []
    with _db.session() as s:
        q = (
            s.query(EntityAlias)
            .filter(EntityAlias.chinese_name.is_(None))
            .order_by(EntityAlias.entity_type, EntityAlias.canonical_id)
        )
        for row in q.limit(max(1, limit + len(blacklist))).all():
            if row.canonical_id in blacklist:
                continue
            out.append({
                "canonical_id": row.canonical_id,
                "entity_type": row.entity_type,
                "primary_name": row.primary_name,
            })
            if len(out) >= limit:
                break
    return out


def set_chinese_name(canonical_id: str, chinese_name: str) -> bool:
    """写回 chinese_name + translated_at。"""
    if not _db.is_mysql_enabled() or not canonical_id or not chinese_name:
        return False
    with _db.session() as s:
        row = s.query(EntityAlias).filter(EntityAlias.canonical_id == canonical_id).first()
        if not row:
            return False
        row.chinese_name = chinese_name[:255]
        row.translated_at = datetime.utcnow()
        return True
