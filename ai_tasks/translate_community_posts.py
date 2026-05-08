"""任务 9 — community_posts (Reddit + Twitter 原文绝大多数英语) → 中文。

社媒评论页"产品信号" tab 直接展示原帖标题和正文。原帖是英语用户阅读不便。
本任务把 title + selftext 翻译为中文，存到 title_zh / selftext_zh 列。
前端 fallback 链：title_zh → title；selftext_zh → selftext。

调用:
    from ai_tasks.translate_community_posts import translate_one, translate_pending
    translate_pending(limit=200)

存储: 写回 community_posts.title_zh / selftext_zh / translated_at
      （dao.community.update_post_translation）

铁律 4: fetch_untranslated_posts() 只取 translated_at IS NULL 的行。
铁律 5: 任一调用失败 → failed_ai_jobs。
"""

from __future__ import annotations

import logging
from typing import Any

from shared.ai_client import run_task
from shared.dao import community as dao_community
from shared.dao import failed_ai_jobs as dao_failed

log = logging.getLogger("ai_tasks.translate_community_posts")

# selftext 截断：避免过长 prompt 被中转路由 / 浪费 token
# 893 是 avg；max 65535（数据库列上限）。前 1500 字够展示用，再长用户也读不完
MAX_SELFTEXT_CHARS = 1500


def translate_one(
    *,
    post_id: int,
    title: str,
    selftext: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    """单条 post → 中文翻译 + 入库。失败则写 failed_ai_jobs。"""
    if not title and not selftext:
        return {"post_id": post_id, "error": "empty title+selftext"}

    # selftext 截断（避免过长 prompt）
    selftext_truncated = (selftext or "")[:MAX_SELFTEXT_CHARS]
    if len(selftext or "") > MAX_SELFTEXT_CHARS:
        selftext_truncated += "\n[... 后续省略]"

    context = {
        "title": (title or "")[:512],
        "selftext": selftext_truncated,
    }
    try:
        result = run_task("post_translate", context=context)
    except Exception as e:
        dao_failed.push(
            task_name="post_translate",
            payload={"post_id": post_id, "title": title[:200]},
            error_msg=str(e),
            error_kind="http",
        )
        log.warning(f"post_translate call failed post_id={post_id}: {e}")
        return {"post_id": post_id, "error": f"http: {e}"}

    if not isinstance(result, dict) or result.get("_parse_error"):
        dao_failed.push(
            task_name="post_translate",
            payload={"post_id": post_id, "title": title[:200]},
            error_msg=str(result)[:1000],
            error_kind="json_parse",
        )
        return {"post_id": post_id, "error": "json_parse"}

    title_zh = (result.get("title_zh") or "").strip()
    selftext_zh = (result.get("selftext_zh") or "").strip()

    # 校验：title_zh 必须非空（这是最关键字段，selftext_zh 允许空 — 原 selftext 就可能为空）
    if not title_zh:
        dao_failed.push(
            task_name="post_translate",
            payload={"post_id": post_id, "title": title[:200]},
            error_msg=f"empty title_zh; selftext_zh={selftext_zh!r}",
            error_kind="validation",
        )
        return {"post_id": post_id, "error": "empty_title_zh"}

    if persist:
        dao_community.update_post_translation(post_id, title_zh, selftext_zh)

    return {"post_id": post_id, "title_zh": title_zh,
            "selftext_zh_len": len(selftext_zh)}


def translate_pending(*, limit: int = 200, dry_run: bool = False) -> dict:
    """批量跑：取 translated_at IS NULL 的 post，逐条翻译。"""
    pending = dao_community.fetch_untranslated_posts(limit=limit)
    log.info(f"[post_translate] fetched {len(pending)} untranslated posts")

    if dry_run:
        return {"fetched": len(pending), "translated": 0, "errors": 0}

    translated = 0
    errors = 0
    for p in pending:
        out = translate_one(
            post_id=p["id"],
            title=p["title"] or "",
            selftext=p["selftext"] or "",
        )
        if out.get("error"):
            errors += 1
        else:
            translated += 1
        if translated % 20 == 0 and translated > 0:
            log.info(f"  translated {translated}/{len(pending)}")

    log.info(f"[post_translate] done · translated={translated} errors={errors}")
    return {
        "fetched": len(pending),
        "translated": translated,
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

    result = translate_pending(limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
