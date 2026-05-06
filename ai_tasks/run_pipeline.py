"""run_pipeline — 评论 AI 管道批量驱动器（每日 02:30 在 daily_sync 后跑）。

顺序：
  1. fetch unlabeled reviews（reviews.labeled_at IS NULL）
  2. for each review:
     a. comment_label → 写 reviews.label / language / translated_text / labeled_at
     b. entity_extract → 写 entity_aliases (新 canonical) + comment_entities
  3. 跑 alert_engine 全 7 类规则

CLI：
    python3 -m ai_tasks.run_pipeline                    # 跑全管道（默认 200 条评论 + alerts）
    python3 -m ai_tasks.run_pipeline --limit 50         # 只跑 50 条评论
    python3 -m ai_tasks.run_pipeline --skip-alerts      # 只跑评论管道
    python3 -m ai_tasks.run_pipeline --skip-comments    # 只跑 alert_engine
    python3 -m ai_tasks.run_pipeline --dry-run          # 不调 AI 不入库（仅看会处理多少条）
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

log = logging.getLogger("ai_pipeline")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s · %(message)s")


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
                    help="本次最多处理多少条未标签评论")
    ap.add_argument("--skip-comments", action="store_true",
                    help="跳过评论管道（只跑 alert_engine）")
    ap.add_argument("--skip-alerts", action="store_true",
                    help="跳过 alert_engine（只跑评论管道）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    result = {"comments": None, "alerts": None}

    if not args.skip_comments:
        result["comments"] = run_comments(limit=args.limit, dry_run=args.dry_run)

    if not args.skip_alerts:
        log.info("--- alert_engine ---")
        result["alerts"] = run_alert_engine(dry_run=args.dry_run)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
