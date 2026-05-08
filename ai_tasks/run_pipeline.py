"""run_pipeline — AI 管道批量驱动器（每日 02:30 在 daily_sync 后跑）。

顺序：
  1. comment pipeline（comment_label + entity_extract，主路径，~200 条/批）
  2. content classifier（task 5/6/7/8，独立可选，互不依赖 — 5 条铁律 §1）
     a. news_classifier      → 写 news_items.is_business / business_category / ...
     b. post_topic_classifier → 写 community_posts.primary_topic / ...
     c. ad_selling_point     → 写 ad_creatives.selling_points / audience / tone
     d. entity_translate     → 写 entity_aliases.chinese_name (GP Reviews 主题中文化)
  3. alert_engine 全 7 类规则

每个分支独立失败不阻塞其他（铁律 1 落地）。

CLI：
    python3 -m ai_tasks.run_pipeline                    # 跑全管道
    python3 -m ai_tasks.run_pipeline --limit 50         # 只跑 50 条评论
    python3 -m ai_tasks.run_pipeline --skip-alerts      # 跳过 alert_engine
    python3 -m ai_tasks.run_pipeline --skip-comments    # 跳过评论管道
    python3 -m ai_tasks.run_pipeline --skip-content     # 跳过 task 5/6/7/8
    python3 -m ai_tasks.run_pipeline --only news        # 只跑 news_classifier
    python3 -m ai_tasks.run_pipeline --only post        # 只跑 post_topic
    python3 -m ai_tasks.run_pipeline --only ads         # 只跑 ad_selling_point
    python3 -m ai_tasks.run_pipeline --only translate   # 只跑 entity_translate
    python3 -m ai_tasks.run_pipeline --dry-run          # 不调 AI 不入库
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from shared.env_loader import load_all as _load_env_all
    _load_env_all()
except Exception:
    pass

from ai_tasks.comment_label import label_and_persist, fetch_unlabeled  # noqa: E402
from ai_tasks.entity_extract import extract_entities  # noqa: E402
from ai_tasks.alert_engine import run_engine as run_alert_engine  # noqa: E402
from ai_tasks.news_classifier import classify_pending as run_news_classifier  # noqa: E402
from ai_tasks.post_topic import classify_pending as run_post_topic  # noqa: E402
from ai_tasks.ad_selling_point import classify_pending as run_ad_selling_point  # noqa: E402
from ai_tasks.post_entity_extract import classify_pending as run_post_entity  # noqa: E402
from ai_tasks.translate_entity_names import translate_pending as run_entity_translate  # noqa: E402
from ai_tasks.translate_community_posts import translate_pending as run_post_translate  # noqa: E402
from ai_tasks.translate_app_versions import translate_pending as run_version_translate  # noqa: E402
from ai_tasks.classify_app_versions import classify_pending as run_version_classify  # noqa: E402

log = logging.getLogger("ai_pipeline")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s · %(message)s")


def run_content_classifiers(*, limit: int = 200, dry_run: bool = False,
                            only: str | None = None) -> dict:
    """跑 task 5/6/7/8/9/10/11 + post_entity_extract — 8 个独立 content classifier。

    每个分支独立 try/except — 任一失败不阻塞其他（铁律 1：AI 队列内部各任务互不依赖）。

    only=None              跑全部八个
    only='news'            只跑 news_classifier
    only='post'            只跑 post_topic
    only='post_ent'        只跑 post_entity_extract（球员/联赛实体抽取）
    only='ads'             只跑 ad_selling_point
    only='translate'       只跑 entity_translate（entity_aliases 主题名翻中文）
    only='post_translate'  只跑 post_translate（community_posts title+selftext 翻中文）
    only='version_translate' 只跑 version_translate（app_versions release_notes 翻中文）
    only='version_classify'  只跑 version_classify（app_versions 类型 + 中文亮点 + 重要标记）
    """
    out = {"news": None, "post_topic": None, "post_entity": None,
           "ad_selling_point": None, "entity_translate": None,
           "post_translate": None, "version_translate": None,
           "version_classify": None}

    if only in (None, "news"):
        try:
            log.info("--- task 5 · news_classifier ---")
            out["news"] = run_news_classifier(limit=limit, dry_run=dry_run)
        except Exception as e:
            log.exception(f"news_classifier 整体失败: {e}")
            out["news"] = {"error": str(e)}

    if only in (None, "post"):
        try:
            log.info("--- task 6 · post_topic_classifier ---")
            out["post_topic"] = run_post_topic(limit=limit, dry_run=dry_run)
        except Exception as e:
            log.exception(f"post_topic 整体失败: {e}")
            out["post_topic"] = {"error": str(e)}

    if only in (None, "post_ent"):
        # task 2.5 — entity_extract on community_posts (migration 0016)
        # 给 Social 页的"球员/联赛"维度准备数据；和 post_topic 互补但独立
        try:
            log.info("--- task 2.5 · post_entity_extract (community_posts) ---")
            out["post_entity"] = run_post_entity(limit=limit, dry_run=dry_run)
        except Exception as e:
            log.exception(f"post_entity_extract 整体失败: {e}")
            out["post_entity"] = {"error": str(e)}

    if only in (None, "ads"):
        try:
            log.info("--- task 7 · ad_selling_point ---")
            out["ad_selling_point"] = run_ad_selling_point(limit=limit, dry_run=dry_run)
        except Exception as e:
            log.exception(f"ad_selling_point 整体失败: {e}")
            out["ad_selling_point"] = {"error": str(e)}

    if only in (None, "translate"):
        # task 8 — entity_aliases.primary_name → chinese_name (GP Reviews 主题中文化)
        # 需要在 entity_extract / post_entity_extract 跑完后才有意义
        try:
            log.info("--- task 8 · entity_translate ---")
            out["entity_translate"] = run_entity_translate(limit=limit, dry_run=dry_run)
        except Exception as e:
            log.exception(f"entity_translate 整体失败: {e}")
            out["entity_translate"] = {"error": str(e)}

    if only in (None, "post_translate"):
        # task 9 — community_posts.title / selftext → 中文（Social 产品信号 tab 展示用）
        try:
            log.info("--- task 9 · post_translate ---")
            out["post_translate"] = run_post_translate(limit=limit, dry_run=dry_run)
        except Exception as e:
            log.exception(f"post_translate 整体失败: {e}")
            out["post_translate"] = {"error": str(e)}

    if only in (None, "version_translate"):
        # task 10 — app_versions.release_notes → 中文（产品动态页展开看完整翻译）
        try:
            log.info("--- task 10 · version_translate ---")
            out["version_translate"] = run_version_translate(limit=limit, dry_run=dry_run)
        except Exception as e:
            log.exception(f"version_translate 整体失败: {e}")
            out["version_translate"] = {"error": str(e)}

    if only in (None, "version_classify"):
        # task 11 — app_versions → version_type + 中文亮点 + is_significant
        try:
            log.info("--- task 11 · version_classify ---")
            out["version_classify"] = run_version_classify(limit=limit, dry_run=dry_run)
        except Exception as e:
            log.exception(f"version_classify 整体失败: {e}")
            out["version_classify"] = {"error": str(e)}

    return out


def run_comments(limit: int = 200, dry_run: bool = False, concurrency: int = 8) -> dict:
    """批量跑 comment_label + entity_extract，并发 N 路（默认 8）。

    并发显著提速：单条 AI 调用 ~1.5s，串行 1939 条 ~50min；并发 8 路 ~6min。
    """
    pending = fetch_unlabeled(limit=limit)
    log.info(f"fetched {len(pending)} unlabeled reviews · 并发 {concurrency}")
    if dry_run:
        return {"fetched": len(pending), "labeled": 0, "extracted": 0, "errors": 0}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    counters = {"labeled": 0, "extracted": 0, "errors": 0, "consec_fail": 0, "aborted": False}
    MAX_CONSEC_FAIL = 20  # 并发场景里 fail 顺序乱，阈值放宽
    t0 = time.monotonic()

    def _process_one(r):
        """单条 review 全流程（label + entity）。Thread-safe — 每个调用独立 HTTP。"""
        rid = r["id"]
        content = r.get("content") or ""
        label_out = label_and_persist(rid, content)
        if label_out.get("error"):
            return {"rid": rid, "label_err": label_out.get("error")}
        ext = extract_entities(
            review_id=rid,
            raw_text=content,
            translated_text=label_out.get("translated_text") or "",
            label=label_out.get("label") or "",
        )
        return {"rid": rid, "extracted": (ext.get("stats") or {}).get("extracted", 0) if not ext.get("error") else None,
                "ent_err": ext.get("error")}

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {ex.submit(_process_one, r): r for r in pending}
        try:
            for fut in as_completed(futures):
                res = fut.result()
                if res.get("label_err"):
                    counters["errors"] += 1
                    counters["consec_fail"] += 1
                    if counters["consec_fail"] >= MAX_CONSEC_FAIL:
                        log.error(f"累计 {counters['consec_fail']} 条评论 label 失败 → abort")
                        counters["aborted"] = True
                        break
                    continue
                counters["labeled"] += 1
                counters["consec_fail"] = 0
                if res.get("ent_err"):
                    counters["errors"] += 1
                else:
                    counters["extracted"] += (res.get("extracted") or 0)
                # 进度提示（每 50 条打一次）
                if counters["labeled"] % 50 == 0:
                    log.info(f"  已处理 {counters['labeled']}/{len(pending)} (耗 {time.monotonic()-t0:.0f}s)")
        finally:
            # abort 时取消剩余 future（已发的 HTTP 还会跑完，但不再 collect）
            if counters["aborted"]:
                for f in futures: f.cancel()

    labeled = counters["labeled"]
    extracted = counters["extracted"]
    errors = counters["errors"]
    aborted = counters["aborted"]
    dt = time.monotonic() - t0
    if aborted:
        log.warning(f"comment pipeline 被 abort · 已处理 {labeled} 条")
    log.info(f"comment pipeline done · labeled={labeled} extracted={extracted} "
             f"errors={errors} duration={dt:.1f}s")
    return {
        "fetched": len(pending),
        "labeled": labeled,
        "extracted": extracted,
        "errors": errors,
        "duration_sec": round(dt, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200,
                    help="每个任务最多处理多少条未分类条目")
    ap.add_argument("--skip-comments", action="store_true",
                    help="跳过评论管道")
    ap.add_argument("--skip-alerts", action="store_true",
                    help="跳过 alert_engine")
    ap.add_argument("--skip-content", action="store_true",
                    help="跳过 task 5/6/7/8/9/10/11 + post_entity_extract (8 个内容分类器)")
    ap.add_argument("--only", choices=["news", "post", "post_ent", "ads", "translate",
                                       "post_translate", "version_translate", "version_classify"],
                    help="只跑 8 个内容分类器中的某一个")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    result = {"comments": None, "content": None, "alerts": None}

    # 注意：5 条铁律 §1 要求 AI 任务之间互相独立。每个分支用独立 try/except，
    # 任一失败不阻塞下一个。
    if not args.skip_comments and not args.only:
        try:
            result["comments"] = run_comments(limit=args.limit, dry_run=args.dry_run)
        except Exception as e:
            log.exception(f"comment pipeline 整体失败: {e}")
            result["comments"] = {"error": str(e)}

    if not args.skip_content:
        try:
            result["content"] = run_content_classifiers(
                limit=args.limit, dry_run=args.dry_run, only=args.only,
            )
        except Exception as e:
            log.exception(f"content classifiers 整体失败: {e}")
            result["content"] = {"error": str(e)}

    if not args.skip_alerts and not args.only:
        try:
            log.info("--- alert_engine ---")
            result["alerts"] = run_alert_engine(dry_run=args.dry_run)
        except Exception as e:
            log.exception(f"alert_engine 整体失败: {e}")
            result["alerts"] = {"error": str(e)}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
