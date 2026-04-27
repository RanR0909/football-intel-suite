#!/usr/bin/env python3
"""市场排名 headless runner（v2 — 改用 AppMagic 替代 iTunes RSS）。

流程：
    1. 跑 scrape_appmagic.cmd_scrape() → appmagic_output/sports_news_<TS>.json
    2. 跑 appmagic_adapter.adapt() → data/market_rank.json + by_country.json + history

登录态失效时退出码 = 2，由 dashboard_server 捕获并提示用户重新登录。
旧版 iTunes RSS 实现（market_rank.py）仍保留为 fallback 模块，未启用。
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_SCRIPT_DIR.parent))

from market_rank.scrape_appmagic import cmd_scrape, LoginRequired
from market_rank import appmagic_adapter


def main() -> None:
    print("=" * 60)
    print(f"市场排名 v2 (AppMagic) — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    print("[1/2] AppMagic scraping ...")
    try:
        json_path = asyncio.run(cmd_scrape(headed=False))
    except LoginRequired as e:
        print(f"❌ 登录态失效：{e}", file=sys.stderr)
        print("   请运行：python3 -m market_rank.scrape_appmagic login", file=sys.stderr)
        sys.exit(2)

    print(f"\n[2/2] 适配输出 → data/ ...")
    summary = appmagic_adapter.adapt(json_path)
    print(f"  ✓ market_rank.json (tracked={summary['tracked_count']})")
    print(f"  ✓ market_rank_by_country.json (countries={summary['country_count']})")
    print(f"  ✓ ranking_history.json")

    print("完成")


if __name__ == "__main__":
    main()
