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


def run_comments(limit: int = 200, dry_run: bool = False) -> dict:
    pending = fetch_unlabeled(limit=limit)
    log.info(f"fetched {len(pending)} unlabeled reviews")
    if dry_run:
        return {"fetched": len(pending), "labeled": 0, "extracted": 0, "errors": 0}

    labeled = 0
    extracted = 0
    errors = 0
    t0 = time.monotonic()
    for r in pending:
        rid = r["id"]
        content = r.get("content") or ""
        # 1. label + persist
        label_out = label_and_persist(rid, content)
        if label_out.get("error"):
            errors += 1
            continue
        labeled += 1

        # 2. entity_extract（用刚翻好的 translated_text 做主输入）
        ext = extract_entities(
            review_id=rid,
            raw_text=content,
            translated_text=label_out.get("translated_text") or "",
            label=label_out.get("label") or "",
        )
        if not ext.get("error"):
            extracted += (ext.get("stats") or {}).get("extracted", 0)
        else:
            errors += 1
    dt = time.monotonic() - t0
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
