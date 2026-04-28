#!/usr/bin/env python3
"""weekly_sync.py — 每周日 03:00 自动跑（launchd 触发，紧跟在 02:00 daily_sync 后）。

只跑"周更"任务，不重复抓数据（daily_sync 已经把抓取做完）：
  1. weekly_review        — 7 天评论 AI 周报
  2. competitor_detail × 9 — 每竞品深度分析（串行）
  3. commercial_weekly    — 商业周报
  4. iap_pricing          — 价格 7 天才变一次，作为周更刷新
  5. generate_dashboard   — 重新聚合（覆盖 daily 的 dashboard_data）

CLI:
  python3 scripts/weekly_sync.py            # 正常跑
  python3 scripts/weekly_sync.py --force    # 全部重跑
  python3 scripts/weekly_sync.py --dry-run  # 只打印计划
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from shared.env_loader import load_env_file
    load_env_file()
except Exception:
    pass

# 复用 daily_sync 的 _run_one / _post_process / _notify
from scripts.daily_sync import _run_one, _post_process, _notify, _PROJECT_ROOT as PR  # noqa: E402
from shared import sync_state  # noqa: E402
from competitors import get_comment_competitors  # noqa: E402

WEEKLY_MAX_AGE_HOURS = 6 * 24  # 6 天内已成功的不重跑


def _should_skip(name: str, force: bool, max_age_hours: float) -> bool:
    if force:
        return False
    return sync_state.is_fresh(name, max_age_hours)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max-age-hours", type=float, default=WEEKLY_MAX_AGE_HOURS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    print(f"=== weekly_sync 开始 {datetime.now().isoformat(timespec='seconds')} ===")
    print(f"force={args.force}  max-age={args.max_age_hours}h  dry-run={args.dry_run}")

    competitors = list(get_comment_competitors().keys())

    # ---- 任务序列（全串行，AI 任务不并发避 Claude 限流） ----
    tasks = [
        ("iap_pricing", "IAP 定价（周更）",
            ["-m", "async_crawler", "--sources", "iap_pricing"], 600, "http"),
        ("weekly_review", "评论周报（AI）",
            [str(PR / "competitor_comment" / "weekly_review.py")], 1500, "ai"),
        ("commercial_weekly", "商业周报（AI）",
            [str(PR / "commercial_strategy" / "run_headless.py"), "--weekly"], 900, "ai"),
    ]
    # 9 个竞品深度
    for name in competitors:
        tasks.append((
            f"competitor_detail_{name}", f"竞品深度 · {name}",
            [str(PR / "competitor_comment" / "competitor_detail.py"), name], 300, "ai",
        ))
    # 最后聚合
    tasks.append((
        "generate_dashboard_weekly", "看板重生成",
        [str(PR / "main_dashboard" / "generate_dashboard.py")], 120, "aggregate",
    ))

    ok = fail = 0
    for name, label, sub_args, to, kind in tasks:
        if _should_skip(name, args.force, args.max_age_hours):
            print(f"[skip] {name}")
            continue
        if args.dry_run:
            print(f"[dry-run] {name} ({label}) timeout={to}s kind={kind}")
            continue
        print(f"\n[start] {name} ({label})")
        result = _run_one(name, label, sub_args, to)
        _post_process(result, kind)
        tag = "✓" if result["success"] else "✗"
        ekind = result.get("kind") or ""
        print(f"  [{tag}] {name}  {result['duration_sec']}s  exit={result['exit_code']}  {ekind}")
        if result["success"]:
            ok += 1
        else:
            fail += 1

    total = time.monotonic() - t0
    print("\n" + "=" * 70)
    print(f"=== weekly_sync 完成 — 总耗时 {total/60:.1f} min ===")
    print(f"  ok={ok}  fail={fail}")
    print("=" * 70)

    if fail >= 3:
        _notify("INTEL-OPS · 周更告警", f"周更 {fail} 个任务失败，详情见 sync_log")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
