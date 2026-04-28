#!/usr/bin/env python3
"""auto_report.py — 兼容入口（薄壳）。

P0 拆分后职责：依次调 comment_fetch + comment_label。
- comment_fetch.py：抓 GP/iOS 评论 → data/raw/comments_raw.json
- comment_label.py：AI 翻译 + 打标 → data/competitor_comments.json

dashboard 上"滚动评论监测"按钮 / scripts/daily_sync.py 都仍然能调这个入口，
不破坏现有触发链路。

直接细粒度跑：
  python3 -m competitor_comment.comment_fetch
  python3 -m competitor_comment.comment_label [--force]
"""

from __future__ import annotations

import sys
from pathlib import Path

# 兼容多种调用方式：python -m competitor_comment.auto_report / 直接 python auto_report.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from competitor_comment import comment_fetch, comment_label  # noqa: E402


def main() -> None:
    print("=" * 60)
    print("Phase 1/2: 抓取评论（GP + iOS）...")
    print("=" * 60)
    comment_fetch.main()

    print("\n" + "=" * 60)
    print("Phase 2/2: AI 标签 + 摘要...")
    print("=" * 60)
    comment_label.main(force=False)

    print("\n[auto_report] 全部完成")


if __name__ == "__main__":
    sys.exit(main() or 0)
