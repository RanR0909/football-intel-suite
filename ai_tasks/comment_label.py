"""任务 1 — 评论翻译 + 6 类标签。

Spec: AI_tasks_spec_v1_1.md
模型：claude-haiku-4-5（统一）

输入：{"comment_id", "raw_text", "language_hint": optional}
输出：{"comment_id", "language", "translated_text", "label"}

调用：
    from ai_tasks.comment_label import label_comment
    out = label_comment(review_id=123, raw_text="App is too slow", language_hint="en")
    # out = {"language": "en", "translated_text": "App 太慢了", "label": "complaint", "comment_id": 123}

存储：
- 写回 reviews 表的 label / language / translated_text / labeled_at 字段
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from shared.ai_client import run_task
from shared import db as _db
from shared.dao import failed_ai_jobs as dao_failed
from shared.models import Review

log = logging.getLogger("ai_tasks.comment_label")

VALID_LABELS = {"complaint", "feature_request", "competitor_compare",
                "churn_signal", "positive", "other"}

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TRANSLATION_TABLE_PATH = _PROJECT_ROOT / "ai_tasks" / "translation_table.json"

_translation_cache: dict | None = None


def _load_translation_table() -> dict:
    """读取 translation_table.json，缓存到内存。"""
    global _translation_cache
    if _translation_cache is None:
        if _TRANSLATION_TABLE_PATH.exists():
            _translation_cache = json.loads(_TRANSLATION_TABLE_PATH.read_text(encoding="utf-8"))
        else:
            _translation_cache = {}
    return _translation_cache


def _build_translation_table_json() -> str:
    """送给 prompt 的紧凑表（去掉 _doc / _version 这些）。"""
    table = _load_translation_table()
    compact = {k: v for k, v in table.items() if not k.startswith("_")}
    return json.dumps(compact, ensure_ascii=False, indent=None, separators=(",", ":"))


def _normalize_label(label: str) -> str:
    """非法标签兜底为 other（spec 错误处理约束）。"""
    if not label:
        return "other"
    label = str(label).strip().lower()
    return label if label in VALID_LABELS else "other"


def label_comment(
    review_id: int | None,
    raw_text: str,
    *,
    language_hint: str = "",
) -> dict[str, Any]:
    """单条评论 → {language, translated_text, label, comment_id}。

    失败时记录 failed_ai_jobs 并返回 {error: ...}。
    """
    if not raw_text or not raw_text.strip():
        return {"comment_id": review_id, "error": "empty raw_text"}

    context = {
        "raw_text": raw_text.strip()[:2000],   # 评论一般 < 2000 字符；超长截断省 token
        "language_hint": language_hint or "",
        "translation_table_json": _build_translation_table_json(),
    }
    try:
        result = run_task("comment_label", context=context)
    except Exception as e:
        dao_failed.push(
            task_name="comment_label",
            payload={"review_id": review_id, "raw_text": raw_text, "language_hint": language_hint},
            error_msg=str(e),
            error_kind="http",
        )
        log.warning(f"comment_label call failed for review_id={review_id}: {e}")
        return {"comment_id": review_id, "error": f"http: {e}"}

    if not isinstance(result, dict) or result.get("_parse_error"):
        # JSON 解析失败 — 写入失败队列
        dao_failed.push(
            task_name="comment_label",
            payload={"review_id": review_id, "raw_text": raw_text},
            error_msg=str(result)[:1000],
            error_kind="json_parse",
        )
        return {"comment_id": review_id, "error": "json_parse"}

    out = {
        "comment_id": review_id,
        "language": (result.get("language") or "").strip().lower()[:8] or None,
        "translated_text": (result.get("translated_text") or "").strip() or None,
        "label": _normalize_label(result.get("label")),
    }
    return out


def persist_label(review_id: int, ai_result: dict) -> bool:
    """把 label_comment 的结果写回 reviews 表。"""
    if ai_result.get("error"):
        return False
    if not _db.is_mysql_enabled():
        return False
    with _db.session() as s:
        row = s.query(Review).filter(Review.id == review_id).first()
        if not row:
            return False
        row.label = ai_result.get("label")
        row.language = ai_result.get("language")
        row.translated_text = ai_result.get("translated_text")
        row.labeled_at = datetime.utcnow()
        return True


def label_and_persist(review_id: int, raw_text: str, *, language_hint: str = "") -> dict:
    """合并：调 AI + 写库。"""
    out = label_comment(review_id, raw_text, language_hint=language_hint)
    if not out.get("error"):
        persist_label(review_id, out)
    return out


def fetch_unlabeled(*, limit: int = 200, competitor_id: int | None = None) -> list[dict]:
    """取出还没有 labeled_at 的评论（用于 daily_sync 触发）。

    排除已在 failed_ai_jobs 里的 review_id（多次重试都失败的），
    避免 daily_sync 反复死磕同一批 garbage review 触发 abort。
    """
    if not _db.is_mysql_enabled():
        return []
    import sqlalchemy as sa
    # 取 failed_ai_jobs 里已知失败的 review_id（comment_label 任务 + 未 resolved）
    blacklist: set[int] = set()
    with _db.engine().connect() as c:
        rows = c.execute(sa.text("""
            SELECT DISTINCT JSON_EXTRACT(payload_json, '$.review_id') AS rid
            FROM failed_ai_jobs
            WHERE task_name = 'comment_label' AND resolved_at IS NULL
        """)).fetchall()
        for r in rows:
            try:
                blacklist.add(int(r[0]))
            except (TypeError, ValueError):
                pass

    with _db.session() as s:
        q = s.query(Review).filter(Review.labeled_at.is_(None))
        q = q.filter(Review.content.isnot(None))
        if blacklist:
            q = q.filter(~Review.id.in_(blacklist))
        if competitor_id is not None:
            q = q.filter(Review.competitor_id == competitor_id)
        rows = q.order_by(Review.id.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "content": r.content,
                "competitor_id": r.competitor_id,
                "region_code": r.region_code,
            }
            for r in rows
        ]
