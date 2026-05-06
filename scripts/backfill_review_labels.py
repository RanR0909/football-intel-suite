#!/usr/bin/env python3
"""把 data/competitor_comments.json 里 AI 已标的 label 回写到 reviews 表。

comment_label 任务跑完只写 JSON，没回写 MySQL → 这里补这一步。
匹配键：(competitor_id, region_code, score, content) — content 取整个文本，
应能精确匹配 reviews.content。

CLI: python3 scripts/backfill_review_labels.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

try:
    from shared.env_loader import load_all as _le
    _le()
except Exception:
    pass

from shared import db
from shared.dao import resolve_competitor_id
import sqlalchemy as sa

ZH_TO_EN = {
    "[问题抱怨]": "complaint",
    "[功能请求]": "feature_request",
    "[高价值功能请求]": "feature_request",
    "[竞品对比]": "competitor_compare",
    "[流失信号]": "churn_signal",
    "[正向反馈]": "positive",
    "[其他]": "other",
}


def main() -> int:
    fp = _ROOT / "data" / "competitor_comments.json"
    if not fp.exists():
        print(f"找不到 {fp}", file=sys.stderr)
        return 2
    blob = json.loads(fp.read_text(encoding="utf-8"))
    competitors = blob.get("competitors", {})

    total_seen = 0
    total_updated = 0
    skipped = 0
    unknown_label = 0

    with db.engine().begin() as conn:
        for comp_name, comp_block in competitors.items():
            cid = resolve_competitor_id(comp_name)
            if cid is None:
                print(f"[skip] {comp_name}: competitor_id 未找到")
                continue
            for region, region_block in (comp_block.get("regions") or {}).items():
                for rv in region_block.get("reviews") or []:
                    total_seen += 1
                    label_zh = (rv.get("label") or "").strip()
                    label_en = ZH_TO_EN.get(label_zh)
                    if not label_en:
                        unknown_label += 1
                        continue
                    content = rv.get("content") or ""
                    score = rv.get("score")
                    if not content or score is None:
                        skipped += 1
                        continue
                    res = conn.execute(sa.text("""
                        UPDATE reviews
                           SET label = :label, labeled_at = :ts
                         WHERE competitor_id = :cid
                           AND region_code = :region
                           AND score = :score
                           AND content = :content
                           AND label IS NULL
                    """), {
                        "label": label_en,
                        "ts": datetime.utcnow(),
                        "cid": cid, "region": region,
                        "score": score, "content": content,
                    })
                    total_updated += res.rowcount or 0

    print(f"扫描 {total_seen} 条 JSON review")
    print(f"  成功回写 label: {total_updated}")
    print(f"  未知中文 label: {unknown_label}")
    print(f"  缺字段跳过:   {skipped}")
    return 0 if total_updated else 1


if __name__ == "__main__":
    sys.exit(main())
