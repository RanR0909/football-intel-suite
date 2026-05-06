"""任务 6 — Reddit / Twitter 帖子主题分类（8 类）。

Spec: AI_tasks_spec_v4.md task #6
模型: claude-haiku-4-5

输入: {post_db_id, title, body, subreddit, score}
输出: {primary_topic, secondary_topics: [...], competitor_mentioned, confidence}

调用:
    from ai_tasks.post_topic import classify_one, classify_pending
    classify_pending(limit=200)

存储: 写回 community_posts 的 primary_topic / secondary_topics /
      competitor_mentioned / topic_classified_at / topic_confidence
      （dao.community.update_topic）

铁律：
- 4 (no double-classify): fetch_unclassified_topic() 过滤 topic_classified_at IS NULL
- 5 (dead-letter): 失败 → failed_ai_jobs
- 3 (no sentiment): prompt 明确禁止 — 标签里没有"好/坏"，只有主题分类
"""

from __future__ import annotations

import logging
from typing import Any

from shared.ai_client import run_task
from shared.dao import community as dao_community
from shared.dao import failed_ai_jobs as dao_failed

log = logging.getLogger("ai_tasks.post_topic")

VALID_TOPICS = {
    "player_drama", "match_result", "data_quality",
    "app_feature", "app_bug", "competitor_compare",
    "industry_news", "meme_humor",
}

KNOWN_COMPETITORS = {
    "SofaScore", "FlashScore", "OneFootball", "365Scores", "FotMob",
    "LiveScore", "AiScore", "BeSoccer", "310Scores", "AllFootball",
}


def classify_one(
    *,
    post_db_id: int,
    title: str = "",
    body: str = "",
    subreddit: str = "",
    score: int = 0,
    persist: bool = True,
) -> dict[str, Any]:
    """单条 post → 主题 + 命中竞品 + 入库。"""
    if not (title or body):
        return {"post_db_id": post_db_id, "error": "empty title and body"}

    context = {
        "title": (title or "").strip()[:512],
        "body": (body or "").strip()[:1500],
        "subreddit": (subreddit or "").strip()[:64],
        "score": int(score or 0),
    }
    try:
        result = run_task("post_topic_classifier", context=context)
    except Exception as e:
        dao_failed.push(
            task_name="post_topic_classifier",
            payload={"post_id": post_db_id, "title": title},
            error_msg=str(e),
            error_kind="http",
        )
        log.warning(f"post_topic call failed post_id={post_db_id}: {e}")
        return {"post_db_id": post_db_id, "error": f"http: {e}"}

    if not isinstance(result, dict) or result.get("_parse_error"):
        dao_failed.push(
            task_name="post_topic_classifier",
            payload={"post_id": post_db_id, "title": title},
            error_msg=str(result)[:1000],
            error_kind="json_parse",
        )
        return {"post_db_id": post_db_id, "error": "json_parse"}

    out = _normalize_result(result)
    out["post_db_id"] = post_db_id

    if persist:
        dao_community.update_topic(post_db_id, out)

    return out


def _normalize_result(raw: dict) -> dict:
    primary = (raw.get("primary_topic") or "").strip().lower()
    if primary not in VALID_TOPICS:
        primary = "match_result"      # 兜底归 match_result（最常见）

    sec_raw = raw.get("secondary_topics") or []
    if not isinstance(sec_raw, list):
        sec_raw = []
    secondary = []
    for x in sec_raw:
        n = str(x).strip().lower()
        if n in VALID_TOPICS and n != primary:
            secondary.append(n)
    # 限 0-2 个 + 去重
    seen = set()
    secondary = [s for s in secondary if not (s in seen or seen.add(s))][:2]

    comp_raw = raw.get("competitor_mentioned")
    competitor_mentioned = None
    if isinstance(comp_raw, str) and comp_raw.strip():
        n = comp_raw.strip()
        comps_lookup = {c.lower(): c for c in KNOWN_COMPETITORS}
        if n.lower() in comps_lookup:
            competitor_mentioned = comps_lookup[n.lower()]

    try:
        confidence = float(raw.get("confidence") or 0)
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "primary_topic": primary,
        "secondary_topics": secondary,
        "competitor_mentioned": competitor_mentioned,
        "confidence": confidence,
    }


def classify_pending(*, limit: int = 200, dry_run: bool = False,
                     concurrency: int = 4) -> dict:
    """批量跑（轻量并发，社媒帖子量大）。"""
    pending = dao_community.fetch_unclassified_topic(limit=limit)
    log.info(f"[post_topic] fetched {len(pending)} unclassified posts · concurrency {concurrency}")

    if dry_run:
        return {"fetched": len(pending), "classified": 0, "errors": 0}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    classified = 0
    errors = 0

    def _proc(p):
        return classify_one(
            post_db_id=p["id"],
            title=p.get("title") or "",
            body=p.get("body") or "",
            subreddit=p.get("subreddit") or "",
            score=p.get("score") or 0,
        )

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(_proc, p) for p in pending]
        for fut in as_completed(futures):
            res = fut.result()
            if res.get("error"):
                errors += 1
            else:
                classified += 1
            if classified % 50 == 0 and classified > 0:
                log.info(f"  classified {classified}/{len(pending)}")

    log.info(f"[post_topic] done · classified={classified} errors={errors}")
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
