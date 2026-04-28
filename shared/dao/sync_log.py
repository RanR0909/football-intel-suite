"""DAO: sync_log — 子任务运行遥测。

调用方：
- main_dashboard/dashboard_server._append_sync_log（手动同步）
- scripts/daily_sync._append_sync_log（自动同步）
两者目前都写 JSON；这里加一个旁路把同一 entry 也插 MySQL + Redis LIST。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from shared import db as _db
from shared.models import SyncLog

log = logging.getLogger("shared.dao.sync_log")

REDIS_LIST_KEY = "sync_log:recent"
REDIS_LIST_MAX = 50


def append_sync_log(entry: dict) -> bool:
    """写入 MySQL sync_log 表 + Redis LPUSH+LTRIM 镜像。

    entry 结构（与 sync_log.json 一致）：
      script, label, competitor, started_at, finished_at, duration_sec, success,
      error_kind, stdout_tail, stderr_tail, cmd
    """
    ok_mysql = _to_mysql(entry)
    ok_redis = _to_redis(entry)
    return ok_mysql or ok_redis


def _to_mysql(entry: dict) -> bool:
    if not _db.is_mysql_enabled():
        return False
    try:
        with _db.session() as s:
            s.add(SyncLog(
                script=str(entry.get("script") or "")[:64],
                label=(entry.get("label") or "")[:64] or None,
                competitor=(entry.get("competitor") or "")[:64] or None,
                started_at=_to_dt(entry.get("started_at")) or datetime.utcnow(),
                finished_at=_to_dt(entry.get("finished_at")),
                duration_sec=_safe_float(entry.get("duration_sec")),
                success=bool(entry.get("success")),
                error_kind=(entry.get("error_kind") or "")[:32] or None,
                stdout_tail=entry.get("stdout_tail") or None,
                stderr_tail=entry.get("stderr_tail") or None,
                cmd=(entry.get("cmd") or "")[:512] or None,
            ))
        return True
    except Exception as e:
        log.warning(f"[sync_log] MySQL 写入失败: {e}")
        return False


def _to_redis(entry: dict) -> bool:
    rc = _db.redis_client()
    if rc is None:
        return False
    try:
        import json as _j
        rc.lpush(REDIS_LIST_KEY, _j.dumps(entry, ensure_ascii=False, default=str))
        rc.ltrim(REDIS_LIST_KEY, 0, REDIS_LIST_MAX - 1)
        return True
    except Exception as e:
        log.warning(f"[sync_log] Redis LPUSH 失败: {e}")
        return False


def _safe_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _to_dt(v):
    if v is None or isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v)
        except Exception:
            return None
    return None
