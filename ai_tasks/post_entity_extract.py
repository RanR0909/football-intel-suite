"""任务 2.5 — entity_extract on community_posts (Reddit / Twitter).

复用 entity_extract.py 的 9 类实体抽取 + canonical_id 归一逻辑，
但写库到 community_post_entities (post_id 外键) 而不是 comment_entities (review_id)。

输入: {post_db_id, title, body}
   ↓ 拼成 raw_text = title + "\\n\\n" + body
   ↓
extract_entities(review_id=None, raw_text=..., translated_text="", label="")
   ↓ 拿到 entities 列表 (已经处理 entity_aliases 归一/新增)
   ↓
upsert_links(post_id, entities) 写到 community_post_entities
   ↓
mark_entity_extracted(post_db_id) 标记 entity_extracted_at = NOW()

铁律：
  · 4 (no double-extract): fetch_unentitied 过滤 entity_extracted_at IS NULL
  · 5 (dead-letter): 复用 extract_entities 内部 dao_failed.push (task_name=
    'entity_extract')；任务完成后才 mark — 失败的下次还能重试 1 次
"""

from __future__ import annotations

import logging

from ai_tasks.entity_extract import extract_entities
from shared.dao import community as dao_community
from shared.dao import community_post_entities as dao_post_ent
from shared.dao import failed_ai_jobs as dao_failed

log = logging.getLogger("ai_tasks.post_entity_extract")


def extract_for_post(*, post_db_id: int, title: str = "", body: str = "") -> dict:
    """单条帖子 → 实体抽取 + 写 community_post_entities + 标记 entity_extracted_at。"""
    raw_text = ((title or "") + "\n\n" + (body or "")).strip()
    if not raw_text:
        return {"post_db_id": post_db_id, "error": "empty title and body"}

    # 复用 entity_extract — review_id=None 表示不写 comment_entities
    out = extract_entities(
        review_id=None,
        raw_text=raw_text,
        translated_text="",   # 社媒帖子大部分英文，不必翻译
        label="",             # 帖子没有 6 类标签的概念
    )
    if out.get("error"):
        # extract_entities 内部已 push failed_ai_jobs (task_name='entity_extract')
        # 但 payload 里 review_id=None 看起来不像 post — 我们补一条更明确的
        dao_failed.push(
            task_name="post_entity_extract",
            payload={"post_id": post_db_id, "title": (title or "")[:200]},
            error_msg=str(out.get("error"))[:500],
            error_kind="forwarded",
        )
        return {"post_db_id": post_db_id, "error": out["error"]}

    entities = out.get("entities") or []
    if entities:
        dao_post_ent.upsert_links(post_db_id, entities)

    # 即使本次 0 条实体也标记 — 否则下次 fetch_unentitied 会再拉这条死磕
    dao_community.mark_entity_extracted(post_db_id)

    return {
        "post_db_id": post_db_id,
        "entities": entities,
        "stats": out.get("stats") or {},
    }


def classify_pending(*, limit: int = 200, dry_run: bool = False,
                     concurrency: int = 4) -> dict:
    """批量跑：取 entity_extracted_at IS NULL 的帖子。"""
    pending = dao_community.fetch_unentitied(limit=limit)
    log.info(f"[post_entity_extract] fetched {len(pending)} unentitied posts · concurrency {concurrency}")

    if dry_run:
        return {"fetched": len(pending), "extracted": 0, "errors": 0}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    extracted_total = 0
    errors = 0
    done_posts = 0

    def _proc(p):
        return extract_for_post(
            post_db_id=p["id"],
            title=p.get("title") or "",
            body=p.get("body") or "",
        )

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(_proc, p) for p in pending]
        for fut in as_completed(futures):
            res = fut.result()
            if res.get("error"):
                errors += 1
            else:
                done_posts += 1
                extracted_total += (res.get("stats") or {}).get("extracted", 0)
            if done_posts % 25 == 0 and done_posts > 0:
                log.info(f"  done {done_posts}/{len(pending)} · entities so far {extracted_total}")

    log.info(f"[post_entity_extract] done · posts={done_posts} entities={extracted_total} errors={errors}")
    return {
        "fetched": len(pending),
        "posts_processed": done_posts,
        "entities_extracted": extracted_total,
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
