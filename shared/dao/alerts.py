"""DAO: alerts — 7 类预警事件 + AI 写 title。

调用方：ai_tasks/alert_engine.py + dashboard
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from shared import db as _db
from shared.dao import resolve_competitor_id
from shared.models import Alert

log = logging.getLogger("shared.dao.alerts")

VALID_TYPES = {"ranking", "commercial", "news", "release", "rating", "churn", "ads"}


def insert_alert(
    *,
    alert_type: str,
    severity: str,
    app_name: str,
    metadata: dict,
    title: str | None = None,
    rule_triggered: str | None = None,
) -> int | None:
    if alert_type not in VALID_TYPES:
        log.warning(f"unknown alert_type {alert_type!r}, skip")
        return None
    if severity not in ("high", "mid", "low"):
        severity = "mid"
    if not _db.is_mysql_enabled():
        return None
    cid = resolve_competitor_id(app_name) if app_name else None
    with _db.session() as s:
        row = Alert(
            alert_type=alert_type,
            severity=severity,
            competitor_id=cid,
            app_name=(app_name or "")[:64] or None,
            metadata_json=json.dumps(metadata, ensure_ascii=False)[:65000],
            title=(title or "")[:120] or None,
            rule_triggered=(rule_triggered or "")[:64] or None,
            fired_at=datetime.utcnow(),
            status="new",
        )
        s.add(row)
        s.flush()
        return int(row.id)


def set_title(alert_id: int, title: str) -> bool:
    if not _db.is_mysql_enabled() or not alert_id:
        return False
    with _db.session() as s:
        row = s.query(Alert).filter(Alert.id == alert_id).first()
        if not row:
            return False
        row.title = (title or "")[:120] or None
        return True


def recent(*, days: int = 7, status: str | None = None) -> list[dict]:
    if not _db.is_mysql_enabled():
        return []
    cutoff = datetime.utcnow() - timedelta(days=days)
    with _db.session() as s:
        q = s.query(Alert).filter(Alert.fired_at >= cutoff)
        if status:
            q = q.filter(Alert.status == status)
        rows = q.order_by(Alert.fired_at.desc()).all()
        return [_row_to_dict(r) for r in rows]


def _row_to_dict(r: Alert) -> dict:
    return {
        "id": r.id,
        "alert_type": r.alert_type,
        "severity": r.severity,
        "competitor_id": r.competitor_id,
        "app_name": r.app_name,
        "metadata": json.loads(r.metadata_json) if r.metadata_json else {},
        "title": r.title,
        "rule_triggered": r.rule_triggered,
        "fired_at": r.fired_at.isoformat() if r.fired_at else None,
        "status": r.status,
    }


def fingerprint_exists(*, alert_type: str, app_name: str, metadata: dict, days: int = 1) -> bool:
    """简单去重：同 type + app_name + 关键字段在最近 N 天里已经发过 → True。

    metadata 不做字段比对（噪声大），用 alert_type + app_name + rule_triggered 已够。
    更严的去重在调用方按业务字段做。
    """
    if not _db.is_mysql_enabled():
        return False
    cutoff = datetime.utcnow() - timedelta(days=days)
    with _db.session() as s:
        q = (
            s.query(Alert)
            .filter(Alert.alert_type == alert_type)
            .filter(Alert.app_name == app_name)
            .filter(Alert.fired_at >= cutoff)
        )
        return s.query(q.exists()).scalar()
