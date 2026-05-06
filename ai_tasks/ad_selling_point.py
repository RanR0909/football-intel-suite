"""任务 7 — Meta 广告创意卖点 / 受众 / 语气分类。

Spec: AI_tasks_spec_v4.md task #7
模型: claude-haiku-4-5

输入: {ad_creative_id, competitor, country, creative_text, media_type}
输出: {selling_points: [...], audience, tone, confidence}

调用:
    from ai_tasks.ad_selling_point import classify_one, classify_pending
    classify_pending(limit=200)

存储: 写回 ad_creatives 的 selling_points / audience / tone /
      selling_classified_at / selling_confidence
      （dao.ads.update_selling）

铁律：
- 4 (no double-classify): fetch_unclassified_selling() 过滤 selling_classified_at IS NULL
- 5 (dead-letter): 失败 → failed_ai_jobs
- 3 (no judgment): prompt 明确禁止 — 不评广告好坏，不给投放建议
"""

from __future__ import annotations

import logging
from typing import Any

from shared.ai_client import run_task
from shared.dao import ads as dao_ads
from shared.dao import failed_ai_jobs as dao_failed

log = logging.getLogger("ai_tasks.ad_selling_point")

VALID_SELLING_POINTS = {
    "live_score", "local_league", "ai_prediction", "betting_funnel",
    "data_depth", "free_app", "premium_subscription", "content_unique",
}
VALID_AUDIENCES = {
    "casual_fan", "hardcore_fan", "bettor", "data_geek", "local_fan",
}
VALID_TONES = {"urgent", "narrative", "comparative", "numeric"}


def classify_one(
    *,
    ad_creative_id: int,
    competitor: str = "",
    country: str = "",
    creative_text: str = "",
    media_type: str = "image",
    persist: bool = True,
) -> dict[str, Any]:
    if not creative_text or not creative_text.strip():
        return {"ad_creative_id": ad_creative_id, "error": "empty creative_text"}

    context = {
        "competitor": (competitor or "").strip()[:64],
        "country": (country or "").strip()[:8].upper(),
        "creative_text": creative_text.strip()[:1500],
    }
    try:
        result = run_task("ad_selling_point", context=context)
    except Exception as e:
        dao_failed.push(
            task_name="ad_selling_point",
            payload={"ad_id": ad_creative_id, "competitor": competitor, "country": country},
            error_msg=str(e),
            error_kind="http",
        )
        log.warning(f"ad_selling_point call failed ad_id={ad_creative_id}: {e}")
        return {"ad_creative_id": ad_creative_id, "error": f"http: {e}"}

    if not isinstance(result, dict) or result.get("_parse_error"):
        dao_failed.push(
            task_name="ad_selling_point",
            payload={"ad_id": ad_creative_id, "competitor": competitor},
            error_msg=str(result)[:1000],
            error_kind="json_parse",
        )
        return {"ad_creative_id": ad_creative_id, "error": "json_parse"}

    out = _normalize_result(result)
    out["ad_creative_id"] = ad_creative_id

    if persist:
        dao_ads.update_selling(ad_creative_id, out)

    return out


def _normalize_result(raw: dict) -> dict:
    sp_raw = raw.get("selling_points") or []
    if not isinstance(sp_raw, list):
        sp_raw = []
    selling_points = []
    seen = set()
    for x in sp_raw:
        n = str(x).strip().lower()
        if n in VALID_SELLING_POINTS and n not in seen:
            selling_points.append(n)
            seen.add(n)
    if not selling_points:
        # 全部不合规 → 默认 live_score（最普适，避免空数组）
        selling_points = ["live_score"]

    audience = (raw.get("audience") or "").strip().lower()
    if audience not in VALID_AUDIENCES:
        audience = "casual_fan"

    tone = (raw.get("tone") or "").strip().lower()
    if tone not in VALID_TONES:
        tone = "narrative"

    try:
        confidence = float(raw.get("confidence") or 0)
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "selling_points": selling_points,
        "audience": audience,
        "tone": tone,
        "confidence": confidence,
    }


def classify_pending(*, limit: int = 200, dry_run: bool = False,
                     concurrency: int = 4) -> dict:
    pending = dao_ads.fetch_unclassified_selling(limit=limit)
    log.info(f"[ad_selling_point] fetched {len(pending)} unclassified ads · concurrency {concurrency}")

    if dry_run:
        return {"fetched": len(pending), "classified": 0, "errors": 0}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    classified = 0
    errors = 0

    def _proc(a):
        return classify_one(
            ad_creative_id=a["id"],
            competitor=a.get("competitor") or "",
            country=a.get("country") or "",
            creative_text=a.get("creative_text") or "",
            media_type=a.get("media_type") or "image",
        )

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(_proc, a) for a in pending]
        for fut in as_completed(futures):
            res = fut.result()
            if res.get("error"):
                errors += 1
            else:
                classified += 1
            if classified % 50 == 0 and classified > 0:
                log.info(f"  classified {classified}/{len(pending)}")

    log.info(f"[ad_selling_point] done · classified={classified} errors={errors}")
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
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    result = classify_pending(
        limit=args.limit, dry_run=args.dry_run, concurrency=args.concurrency,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
