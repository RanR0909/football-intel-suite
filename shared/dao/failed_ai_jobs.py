"""DAO: failed_ai_jobs — AI 任务死信队列。

调用方：ai_tasks/* 重试耗尽后写入；运维或 cron 周期性重放。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from shared import db as _db
from shared.models import FailedAiJob

log = logging.getLogger("shared.dao.failed_ai_jobs")


def push(
    *,
    task_name: str,
    payload: dict,
    error_msg: str | None = None,
    error_kind: str | None = None,
) -> int | None:
    if not _db.is_mysql_enabled():
        return None
    with _db.session() as s:
        row = FailedAiJob(
            task_name=task_name[:64],
            payload_json=json.dumps(payload, ensure_ascii=False)[:65000],
            error_msg=(error_msg or "")[:8000] or None,
            error_kind=(error_kind or "unknown")[:32],
            attempts=1,
            first_failed_at=datetime.utcnow(),
            last_attempt_at=datetime.utcnow(),
        )
        s.add(row)
        s.flush()
        return int(row.id)


def list_pending(*, task_name: str | None = None, limit: int = 100) -> list[dict]:
    if not _db.is_mysql_enabled():
        return []
    with _db.session() as s:
        q = s.query(FailedAiJob).filter(FailedAiJob.resolved_at.is_(None))
        if task_name:
            q = q.filter(FailedAiJob.task_name == task_name)
        rows = q.order_by(FailedAiJob.first_failed_at).limit(limit).all()
        return [{
            "id": r.id,
            "task_name": r.task_name,
            "payload": json.loads(r.payload_json),
            "error_msg": r.error_msg,
            "error_kind": r.error_kind,
            "attempts": r.attempts,
            "first_failed_at": r.first_failed_at.isoformat() if r.first_failed_at else None,
            "last_attempt_at": r.last_attempt_at.isoformat() if r.last_attempt_at else None,
        } for r in rows]


def mark_resolved(job_id: int) -> bool:
    if not _db.is_mysql_enabled() or not job_id:
        return False
    with _db.session() as s:
        row = s.query(FailedAiJob).filter(FailedAiJob.id == job_id).first()
        if not row:
            return False
        row.resolved_at = datetime.utcnow()
        return True


def increment_attempt(job_id: int, *, error_msg: str | None = None) -> bool:
    if not _db.is_mysql_enabled() or not job_id:
        return False
    with _db.session() as s:
        row = s.query(FailedAiJob).filter(FailedAiJob.id == job_id).first()
        if not row:
            return False
        row.attempts = (row.attempts or 0) + 1
        row.last_attempt_at = datetime.utcnow()
        if error_msg:
            row.error_msg = error_msg[:8000]
        return True
