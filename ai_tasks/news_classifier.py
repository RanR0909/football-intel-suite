"""任务 5 — Google News 商业新闻过滤 + 8 类 category 分类。

Spec: AI_tasks_spec_v4.md task #5
模型: claude-haiku-4-5

输入: {news_id, title, snippet, source, matched_keyword}
输出: {is_business: bool, category: str|None, competitors_mentioned: [...], confidence: float}

调用:
    from ai_tasks.news_classifier import classify_one, classify_pending
    classify_one(news_id=123, title="...", snippet="...", source="techcrunch.com", matched_keyword="funding")
    # 或批量：
    classify_pending(limit=200)

存储: 写回 news_items.is_business / business_category / competitors_mentioned /
      classification_confidence / classified_at（dao.news_items.update_classification）

铁律 4: fetch_unclassified() 只取 classified_at IS NULL 的行，不重复跑。
铁律 5: 任一调用失败 → failed_ai_jobs；最多重试 1 次（业务方循环里控制）。
"""

from __future__ import annotations

import logging
from typing import Any

from shared.ai_client import run_task
from shared.dao import failed_ai_jobs as dao_failed
from shared.dao import news_items as dao_news

log = logging.getLogger("ai_tasks.news_classifier")

VALID_CATEGORIES = {
    "funding", "acquisition", "partnership", "launch",
    "strategy", "hiring", "legal", "other",
}

# 已知竞品白名单（用于 competitors_mentioned 字段的清洗）
KNOWN_COMPETITORS = {
    "SofaScore", "FlashScore", "OneFootball", "365Scores", "FotMob",
    "LiveScore", "AiScore", "BeSoccer", "310Scores", "AllFootball",
    "ESPN", "DAZN", "Bet365",
}


def classify_one(
    *,
    news_id: int,
    title: str,
    snippet: str = "",
    source: str = "",
    matched_keyword: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    """单条新闻 → 分类结果 + 入库。失败则写 failed_ai_jobs。"""
    if not title or not title.strip():
        return {"news_id": news_id, "error": "empty title"}

    context = {
        "title": title.strip()[:512],
        "snippet": (snippet or "").strip()[:1500],
        "source": (source or "").strip()[:128],
        "matched_keyword": (matched_keyword or "").strip()[:128],
    }
    try:
        result = run_task("news_classifier", context=context)
    except Exception as e:
        dao_failed.push(
            task_name="news_classifier",
            payload={"news_id": news_id, "title": title, "source": source},
            error_msg=str(e),
            error_kind="http",
        )
        log.warning(f"news_classifier call failed news_id={news_id}: {e}")
        return {"news_id": news_id, "error": f"http: {e}"}

    if not isinstance(result, dict) or result.get("_parse_error"):
        dao_failed.push(
            task_name="news_classifier",
            payload={"news_id": news_id, "title": title},
            error_msg=str(result)[:1000],
            error_kind="json_parse",
        )
        return {"news_id": news_id, "error": "json_parse"}

    out = _normalize_result(result)
    out["news_id"] = news_id

    if persist:
        dao_news.update_classification(news_id, out)

    return out


def _normalize_result(raw: dict) -> dict:
    """验证 AI 输出 + 不合规字段兜底（spec 错误处理）。"""
    is_business = raw.get("is_business")
    if is_business is None:
        # 按"宁缺勿滥"原则：模型没明确说 true 就当 false（前端只展 true）
        is_business = False
    is_business = bool(is_business)

    category = (raw.get("category") or "").strip().lower()
    if not is_business:
        category = None
    elif category not in VALID_CATEGORIES:
        category = "other"

    comps_raw = raw.get("competitors_mentioned") or []
    if not isinstance(comps_raw, list):
        comps_raw = []
    # 大小写归一 + 白名单过滤
    comps_lookup = {c.lower(): c for c in KNOWN_COMPETITORS}
    competitors = []
    for x in comps_raw:
        n = str(x).strip()
        if n.lower() in comps_lookup:
            competitors.append(comps_lookup[n.lower()])
    # 去重保序
    seen = set()
    competitors = [c for c in competitors if not (c in seen or seen.add(c))]

    try:
        confidence = float(raw.get("confidence") or 0)
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "is_business": is_business,
        "category": category,
        "competitors_mentioned": competitors,
        "confidence": confidence,
    }


def classify_pending(*, limit: int = 200, dry_run: bool = False) -> dict:
    """批量跑：取 classified_at IS NULL 的条目，逐条分类（串行；本任务量小）。"""
    pending = dao_news.fetch_unclassified(limit=limit)
    log.info(f"[news_classifier] fetched {len(pending)} unclassified news items")

    if dry_run:
        return {"fetched": len(pending), "classified": 0, "errors": 0}

    classified = 0
    errors = 0
    for n in pending:
        out = classify_one(
            news_id=n["id"],
            title=n["title"],
            snippet=n.get("snippet") or "",
            source=n.get("source") or "",
            matched_keyword=n.get("matched_keyword") or "",
        )
        if out.get("error"):
            errors += 1
        else:
            classified += 1
        # 进度提示（每 50 条）
        if classified % 50 == 0 and classified > 0:
            log.info(f"  classified {classified}/{len(pending)}")

    log.info(f"[news_classifier] done · classified={classified} errors={errors}")
    return {
        "fetched": len(pending),
        "classified": classified,
        "errors": errors,
    }


if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    result = classify_pending(limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
