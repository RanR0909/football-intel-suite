"""任务 3 — alert metadata 翻译为 ≤50 字事实陈述。

Spec: AI_tasks_spec_v1_1.md
模型：claude-haiku-4-5

输入：{"alert_type", "severity", "app_name", "metadata": {...}}
输出：{"title": "≤50 字事实陈述"}

调用：
    from ai_tasks.alert_title import generate_title
    title = generate_title(alert_type="ranking", severity="high", app_name="Sofascore",
                          metadata={"region": "us", "old_rank": 14, "new_rank": 6, "change": 8})
"""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.ai_client import run_task
from shared.dao import failed_ai_jobs as dao_failed

log = logging.getLogger("ai_tasks.alert_title")

VALID_TYPES = {"ranking", "commercial", "news", "release", "rating", "churn", "ads"}


def generate_title(
    *,
    alert_type: str,
    severity: str,
    app_name: str,
    metadata: dict[str, Any],
    alert_id: int | None = None,
) -> str:
    """返回 ≤50 字 title。失败时返回 fallback 字符串（不抛）。"""
    if alert_type not in VALID_TYPES:
        return _fallback_title(alert_type, app_name, metadata)
    context = {
        "alert_type": alert_type,
        "severity": severity or "mid",
        "app_name": app_name or "",
        "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
    }
    try:
        result = run_task("alert_title", context=context)
    except Exception as e:
        dao_failed.push(
            task_name="alert_title",
            payload={"alert_id": alert_id, "alert_type": alert_type, "app_name": app_name,
                     "severity": severity, "metadata": metadata},
            error_msg=str(e),
            error_kind="http",
        )
        log.warning(f"alert_title failed for alert_type={alert_type} app={app_name}: {e}")
        return _fallback_title(alert_type, app_name, metadata)

    if not isinstance(result, dict) or result.get("_parse_error"):
        dao_failed.push(
            task_name="alert_title",
            payload={"alert_id": alert_id, "alert_type": alert_type, "app_name": app_name,
                     "metadata": metadata},
            error_msg=str(result)[:1000],
            error_kind="json_parse",
        )
        return _fallback_title(alert_type, app_name, metadata)

    title = (result.get("title") or "").strip()
    if not title:
        return _fallback_title(alert_type, app_name, metadata)
    # spec 错误处理：超 50 字截断（不重新调用）
    return title[:50]


# ---- fallback：AI 调失败时给个能看的兜底 title -----------------------------


def _fallback_title(alert_type: str, app_name: str, metadata: dict) -> str:
    """AI 失败时本地拼一个简陋的事实陈述（dashboard 不至于空白）。"""
    app = app_name or "(unknown)"
    md = metadata or {}
    if alert_type == "ranking":
        return f"{app} {md.get('region', '')} 榜 #{md.get('old_rank')} → #{md.get('new_rank')}"[:50]
    if alert_type == "commercial":
        return f"{app} {md.get('iap_name', '')} ${md.get('old_price_usd')} → ${md.get('new_price_usd')}"[:50]
    if alert_type == "news":
        return f"{app} · {(md.get('headline') or '')[:30]}"[:50]
    if alert_type == "release":
        return f"{app} {md.get('version', '')} 上线"[:50]
    if alert_type == "rating":
        return f"{app} {md.get('region', '')} 评分 {md.get('old_rating')} → {md.get('new_rating')}"[:50]
    if alert_type == "churn":
        return f"{app} 流失信号 {md.get('old_pct')}% → {md.get('new_pct')}%"[:50]
    if alert_type == "ads":
        return f"{app} 广告投放 {md.get('count_old')} → {md.get('count_new')}"[:50]
    return f"{app} · {alert_type}"[:50]
