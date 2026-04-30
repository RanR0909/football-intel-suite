"""任务 4 — App 元数据分类（peer app 判定 + topic + categories）。

Spec: app_classifier_prompt.txt
模型：claude-haiku-4-5

输入：{name, publisher, description, category, matched_keywords}
输出：{is_relevant, topic, categories, confidence, rejection_reason}

主要使用场景：
- appstore_rank 抓 top 100 后，对每个未跟踪的 app（competitor_id IS NULL）跑一次分类
- 关键词搜索（"football", "soccer", "live scores" 等）发现的新 app
- 人工提交一个 bundle_id / iOS app id 让 AI 帮忙判断

调用：
    from ai_tasks.app_classifier import classify_app
    out = classify_app(
        app_id="1171012600",
        platform="ios",
        name="All Football",
        publisher="All Football Inc.",
        description="Football scores, news...",
        category="Sports",
        matched_keywords=["football", "scores"],
    )
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable

from shared.ai_client import run_task
from shared.dao import app_classifications as dao_class
from shared.dao import failed_ai_jobs as dao_failed

log = logging.getLogger("ai_tasks.app_classifier")

VALID_TOPICS = {"football", "basketball", "tennis", "F1", "cricket", "multi_sport", "non_sport"}
VALID_CATEGORIES = {"news", "score", "prediction", "tipster", "betting",
                    "analytics", "community", "video"}

DESC_MAX_CHARS = 1500   # description 截断长度（送 AI 时省 token）


def classify_app(
    *,
    app_id: str,
    platform: str,
    name: str,
    publisher: str = "",
    description: str = "",
    category: str = "",
    matched_keywords: Iterable[str] | None = None,
    skip_if_recent: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    """单个 app → {is_relevant, topic, categories, confidence, rejection_reason} + 入库。

    skip_if_recent=True 时，30 天内已分类过的 app 直接返回缓存（不调 AI 不入库）。
    """
    if platform not in ("ios", "gp"):
        return {"error": f"invalid platform: {platform}"}
    if not app_id or not name:
        return {"error": "missing app_id or name"}

    # 短路：最近 30 天已分类
    if skip_if_recent and dao_class.is_already_classified(app_id, platform, max_age_days=30):
        cached = dao_class.get(app_id, platform)
        if cached:
            return {
                "app_id": app_id, "platform": platform,
                "is_relevant": cached["is_relevant"],
                "topic": cached["topic"],
                "categories": cached["categories"],
                "confidence": cached["confidence"],
                "rejection_reason": cached["rejection_reason"],
                "_cached": True,
            }

    keywords = list(matched_keywords or [])
    desc_excerpt = (description or "").strip()[:DESC_MAX_CHARS]

    context = {
        "name": name[:255],
        "publisher": (publisher or "")[:255],
        "description": desc_excerpt or "(no description)",
        "category": (category or "")[:64],
        "matched_keywords": json.dumps(keywords, ensure_ascii=False),
    }
    try:
        result = run_task("app_classifier", context=context)
    except Exception as e:
        dao_failed.push(
            task_name="app_classifier",
            payload={"app_id": app_id, "platform": platform, "name": name},
            error_msg=str(e),
            error_kind="http",
        )
        log.warning(f"app_classifier failed for {platform}:{app_id} ({name}): {e}")
        return {"app_id": app_id, "platform": platform, "error": f"http: {e}"}

    if not isinstance(result, dict) or result.get("_parse_error"):
        dao_failed.push(
            task_name="app_classifier",
            payload={"app_id": app_id, "platform": platform, "name": name},
            error_msg=str(result)[:1000],
            error_kind="json_parse",
        )
        return {"app_id": app_id, "platform": platform, "error": "json_parse"}

    # 验证 + 兜底（spec 错误处理）
    out = _normalize_result(result)
    out["app_id"] = app_id
    out["platform"] = platform

    if persist:
        dao_class.upsert_classification(
            app_id=app_id,
            platform=platform,
            payload=out,
            name=name,
            publisher=publisher,
            category=category,
            description_excerpt=desc_excerpt,
            matched_keywords=keywords,
        )

    return out


def _normalize_result(raw: dict) -> dict:
    """验证 AI 输出 + 不合规字段兜底。"""
    is_relevant = bool(raw.get("is_relevant")) if raw.get("is_relevant") is not None else False

    topic = (raw.get("topic") or "").strip()
    if topic not in VALID_TOPICS:
        topic = "non_sport"     # 不合规 topic 默认归 non_sport（且 is_relevant 强制 False）
        is_relevant = False

    cats_raw = raw.get("categories") or []
    if not isinstance(cats_raw, list):
        cats_raw = []
    categories = [c for c in (str(x).strip() for x in cats_raw) if c in VALID_CATEGORIES]

    try:
        confidence = float(raw.get("confidence") or 0)
        if confidence < 0:
            confidence = 0.0
        elif confidence > 1:
            confidence = 1.0
    except (TypeError, ValueError):
        confidence = 0.0

    rejection_reason = (raw.get("rejection_reason") or "").strip()[:255]

    return {
        "is_relevant": is_relevant,
        "topic": topic,
        "categories": categories,
        "confidence": confidence,
        "rejection_reason": rejection_reason,
    }


def classify_batch(items: list[dict], *, skip_if_recent: bool = True) -> dict:
    """批量分类。items = [{app_id, platform, name, publisher?, description?, category?, matched_keywords?}, ...]"""
    summary = {"total": len(items), "ok": 0, "cached": 0, "errors": 0, "results": []}
    for it in items:
        out = classify_app(
            app_id=it["app_id"],
            platform=it["platform"],
            name=it.get("name") or "",
            publisher=it.get("publisher") or "",
            description=it.get("description") or "",
            category=it.get("category") or "",
            matched_keywords=it.get("matched_keywords") or [],
            skip_if_recent=skip_if_recent,
        )
        if out.get("error"):
            summary["errors"] += 1
        elif out.get("_cached"):
            summary["cached"] += 1
        else:
            summary["ok"] += 1
        summary["results"].append(out)
    return summary
